"""以 miniaudio 為核心的播放引擎。

**絕對不要改用 ``miniaudio.decode_file``。** 它內部把路徑用
``sys.getfilesystemencoding()`` 編成 bytes 再交給 C 的 ``fopen``，
在 Windows 上會以 ANSI 代碼頁解讀，只要路徑含非 ASCII 字元就會回
``MA_DOES_NOT_EXIST(-7)``。已實測：``D:\\音樂撥放器\\…`` 全數失敗。
``stream_file`` 走的是另一個 C 入口，中文路徑正常，而且支援 ``seek_frame``。
``tests/test_engine.py`` 有一條專門守這件事的回歸測試。

為什麼不用 Qt 的 QMediaPlayer：它拿不到 PCM，頻譜與音質分析就只能造假。
"""

from __future__ import annotations

import array
import contextlib
import threading
from collections.abc import Generator
from typing import Any

import miniaudio
import numpy as np
import numpy.typing as npt

from aurora.audio.analyzer import Analyzer
from aurora.core.constants import (
    FALLBACK_SAMPLE_RATE,
    FRAMES_PER_CHUNK,
    OUTPUT_CHANNELS,
    VOLUME_RAMP_FRAMES,
)
from aurora.core.models import AudioFormat

FloatArray = npt.NDArray[np.float32]

#: 裝置緩衝長度。miniaudio 預設 200ms 對視覺化來說延遲太明顯；
#: 60ms 在 Python 回呼下實測仍然穩定，再低就容易斷續。
_BUFFER_MSEC = 60


class AudioEngine:
    """單曲播放器：載入 → 播放／暫停 → 跳轉 → 播畢通知。

    所有公開方法都可以從 Qt 主執行緒安全呼叫。內部狀態以 ``RLock`` 保護，
    音訊回呼只會碰 :meth:`_process` 與少數純量屬性。
    """

    def __init__(self, sample_rate: int | None = None) -> None:
        self._lock = threading.RLock()
        self._sample_rate = sample_rate or FALLBACK_SAMPLE_RATE
        self._channels = OUTPUT_CHANNELS

        self._device: miniaudio.PlaybackDevice | None = None
        self._callback: Generator[Any, int, None] | None = None
        self._path: str | None = None
        self._duration = 0.0

        self._frames_played = 0
        self._playing = False
        self._finished = False

        self._volume = 1.0
        self._applied_volume = 1.0
        self._muted = False

        self.analyzer = Analyzer(self._sample_rate, self._channels)

    # ------------------------------------------------------------ 狀態

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def output_format(self) -> AudioFormat:
        """引擎實際跑的格式。音質面板用它顯示訊號鏈中段。"""
        return AudioFormat(self._sample_rate, self._channels, 32, is_float=True)

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        """播放位置（秒）。由實際送出的樣本數推算，不是牆鐘時間。"""
        return self._frames_played / self._sample_rate if self._sample_rate else 0.0

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = min(max(float(value), 0.0), 1.0)

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        self._muted = bool(value)

    @property
    def _target_gain(self) -> float:
        return 0.0 if self._muted else self._volume

    def take_finished(self) -> bool:
        """消費「這首播完了」的旗標。UI 每幀輪詢一次，讀到就自動清除。"""
        with self._lock:
            finished, self._finished = self._finished, False
        return finished

    # ------------------------------------------------------------ 裝置

    def configure_output(self, sample_rate: int) -> bool:
        """把輸出裝置切到指定取樣率。

        跟輸出端點對齊可以少一次重取樣。裝置已在跑的話會先停再重建，
        並從目前位置無縫接續。回傳是否真的有變更。
        """
        with self._lock:
            if sample_rate == self._sample_rate or sample_rate <= 0:
                return False
            resume_at = self.position if self._path else 0.0
            was_playing = self._playing

            self._teardown_device()
            self._sample_rate = sample_rate
            self.analyzer.reconfigure(sample_rate, self._channels)

            if self._path:
                self._rebuild_stream(int(resume_at * sample_rate))
                if was_playing:
                    self.play()
            return True

    def _ensure_device(self) -> miniaudio.PlaybackDevice | None:
        if self._device is not None:
            return self._device
        try:
            self._device = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.FLOAT32,
                nchannels=self._channels,
                sample_rate=self._sample_rate,
                buffersize_msec=_BUFFER_MSEC,
                app_name="Aurora",
            )
        except miniaudio.MiniaudioError:
            self._device = None
        return self._device

    def _teardown_device(self) -> None:
        self._playing = False
        if self._device is not None:
            with contextlib.suppress(miniaudio.MiniaudioError, OSError):
                self._device.stop()
                self._device.close()
            self._device = None
        self._callback = None

    # ------------------------------------------------------------ 載入

    def load(self, path: str, duration_sec: float = 0.0) -> bool:
        """載入曲目但不開始播放。

        ``duration_sec`` 由音樂庫從標籤讀出後傳進來 —— 那條路徑用 mutagen，
        不必解碼整個檔案。傳 0 時才退回讓 miniaudio 自己探。
        """
        with self._lock:
            self.stop()
            self._path = path
            self._duration = duration_sec if duration_sec > 0 else _probe_duration(path)
            self._frames_played = 0
            self._finished = False
            self.analyzer.reset_track()
            return self._rebuild_stream(0)

    def _rebuild_stream(self, seek_frame: int) -> bool:
        """建立解碼器與回呼產生器，起點為 ``seek_frame``。"""
        if self._path is None:
            return False
        try:
            source = miniaudio.stream_file(
                self._path,
                output_format=miniaudio.SampleFormat.FLOAT32,
                nchannels=self._channels,
                sample_rate=self._sample_rate,
                frames_to_read=FRAMES_PER_CHUNK,
                seek_frame=max(0, seek_frame),
            )
        except (miniaudio.MiniaudioError, OSError, FileNotFoundError):
            self._callback = None
            return False

        callback = miniaudio.stream_with_callbacks(
            source,
            frame_process_method=self._process,
            end_callback=self._on_end,
        )
        next(callback)  # miniaudio 要求傳入前先啟動產生器
        self._callback = callback
        self._frames_played = max(0, seek_frame)
        return True

    # ------------------------------------------------------------ 傳輸控制

    def play(self) -> bool:
        with self._lock:
            if self._callback is None or self._path is None:
                return False
            device = self._ensure_device()
            if device is None:
                return False
            if self._playing:
                return True
            try:
                device.start(self._callback)
            except miniaudio.MiniaudioError:
                return False
            self._playing = True
            return True

    def pause(self) -> None:
        """暫停。

        ``PlaybackDevice.stop()`` 只是停掉裝置並丟掉它對產生器的參照，
        產生器本身還活著，所以續播時把同一個產生器再 ``start()`` 進去
        就能從中斷處接續，不需要重建解碼器。
        """
        with self._lock:
            if not self._playing or self._device is None:
                return
            with contextlib.suppress(miniaudio.MiniaudioError):
                self._device.stop()
            self._playing = False

    def toggle(self) -> bool:
        if self._playing:
            self.pause()
        else:
            self.play()
        return self._playing

    def stop(self) -> None:
        with self._lock:
            self._teardown_device()
            self._frames_played = 0

    def seek(self, seconds: float) -> bool:
        """跳到指定秒數。以新的起點重建解碼器，在鎖內抽換。"""
        with self._lock:
            if self._path is None:
                return False
            target = min(max(seconds, 0.0), self._duration) if self._duration else max(seconds, 0.0)
            was_playing = self._playing

            if self._device is not None and self._playing:
                with contextlib.suppress(miniaudio.MiniaudioError):
                    self._device.stop()
                self._playing = False

            if not self._rebuild_stream(int(target * self._sample_rate)):
                return False
            self._finished = False
            self.analyzer.reset_track()

            if was_playing:
                self.play()
            return True

    def pump(self, frames: int = FRAMES_PER_CHUNK) -> int:
        """手動推進一批樣本，完全不經過音訊裝置。

        兩個用途：無頭測試（不需要音效卡、也不會發出聲音），
        以及截圖模式（要有真實的頻譜資料，但不必出聲）。
        回傳實際處理的框數，``0`` 代表串流已到結尾。
        """
        with self._lock:
            if self._callback is None:
                return 0
            before = self._frames_played
            try:
                self._callback.send(frames)
            except StopIteration:
                self._on_end()
                return 0
            return self._frames_played - before

    # ------------------------------------------------------------ 音訊回呼

    def _process(self, frame: Any) -> bytes:
        """在音訊回呼執行緒上執行。只做 O(n) 的 numpy 運算。

        送給分析器的是**施加音量之前**的訊號 —— 音質量測要看檔案本身，
        不該被音量旋鈕影響；視覺化也因此在小音量下依然有生氣。
        """
        samples = np.frombuffer(frame, dtype=np.float32).copy()
        if samples.size == 0:
            return b""

        self.analyzer.push_interleaved(samples)
        self._frames_played += samples.size // self._channels

        gain = self._target_gain
        if gain != 1.0 or self._applied_volume != gain:
            samples *= self._gain_ramp(samples.size, gain)
            self._applied_volume = gain
        return samples.tobytes()

    def _gain_ramp(self, count: int, target: float) -> FloatArray:
        """在區塊內把增益從上次的值平滑過渡到目標值，避免調音量時爆音。"""
        start = self._applied_volume
        if start == target:
            return np.full(count, target, dtype=np.float32)
        ramp_length = min(count, VOLUME_RAMP_FRAMES * self._channels)
        ramp = np.full(count, target, dtype=np.float32)
        ramp[:ramp_length] = np.linspace(start, target, ramp_length, dtype=np.float32)
        return ramp

    def _on_end(self) -> None:
        """解碼器耗盡。只設旗標，讓 UI 執行緒去處理換下一首。"""
        self._finished = True
        self._playing = False

    # ------------------------------------------------------------ 清理

    def close(self) -> None:
        with self._lock:
            self._teardown_device()
            self._path = None

    def __enter__(self) -> AudioEngine:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _probe_duration(path: str) -> float:
    """沒有標籤資訊時的時長退路。

    ``get_file_info`` 對部分容器（實測 OGG）在非 ASCII 路徑上會失敗，
    所以查不到就回 0，讓 UI 顯示「--:--」而不是崩潰。
    """
    try:
        return float(miniaudio.get_file_info(path).duration)
    except (miniaudio.MiniaudioError, OSError, AttributeError):
        return 0.0


def decode_all(path: str, sample_rate: int, channels: int = 2) -> FloatArray:
    """把整個檔案解碼成交錯的 float32。

    離線分析用（例如一次算完整首的波形）。同樣走 ``stream_file``，
    因為 ``decode_file`` 不支援非 ASCII 路徑。
    """
    try:
        source = miniaudio.stream_file(
            path,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=channels,
            sample_rate=sample_rate,
            frames_to_read=4096,
        )
        next(source)
    except (miniaudio.MiniaudioError, OSError, FileNotFoundError):
        return np.zeros(0, dtype=np.float32)

    collected = array.array("f")
    while True:
        try:
            chunk = source.send(4096)
        except StopIteration:
            break
        if not len(chunk):
            break
        collected.extend(chunk)
    return np.frombuffer(collected, dtype=np.float32)
