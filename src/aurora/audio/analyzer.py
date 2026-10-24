"""即時分析：環形緩衝 + 頻譜 + 音質量測。

分工的理由：FFT 很貴，放進音訊回呼會造成斷續。所以回呼執行緒只做一次
memcpy 把單聲道樣本寫進環形緩衝，其餘全部由 UI 執行緒每幀取用。

緩衝滿一圈時舊資料會被覆寫。以 UI 60 Hz 的節奏與一秒的容量來說，
要落後 60 幀才會掉樣本 —— 而即使真的掉了，頻譜截止與響度都是統計量，
少數樣本不影響結論。
"""

from __future__ import annotations

import threading

import numpy as np
import numpy.typing as npt

from aurora.core.constants import FFT_SIZE, SPECTRUM_BARS
from aurora.core.dsp import LevelMeter, RolloffAnalyzer, SpectrumProcessor, mix_to_mono
from aurora.core.models import LevelStats, RolloffResult, SpectrumFrame
from aurora.core.onset import OnsetDetector

FloatArray = npt.NDArray[np.float32]

#: 環形緩衝容量（秒）。要遠大於一個 UI 幀的間隔，才不會掉樣本。
_BUFFER_SECONDS = 1.0
#: 鼓點旗標在觸發後維持這麼多秒為真，讓 UI 有時間看到它。
_ONSET_LATCH_SEC = 0.08


class RingBuffer:
    """單寫入者／單讀取者的浮點環形緩衝。"""

    def __init__(self, capacity: int) -> None:
        self._data = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._written = 0
        self._lock = threading.Lock()

    @property
    def written(self) -> int:
        """自建立以來寫入的總樣本數，也是讀取端的游標基準。"""
        with self._lock:
            return self._written

    def write(self, samples: FloatArray) -> None:
        """由音訊回呼呼叫。只做取模與複製，不做分析。"""
        if samples.size == 0:
            return

        total = int(samples.size)
        skipped = max(0, total - self._capacity)
        chunk = samples[skipped:]
        with self._lock:
            # oversized write 仍要讓絕對 cursor 前進完整輸入長度；儲存位置
            # 對應被保留下來的最後一圈，而不是假裝前面的樣本沒存在過。
            start = (self._written + skipped) % self._capacity
            end = start + chunk.size
            if end <= self._capacity:
                self._data[start:end] = chunk
            else:
                split = self._capacity - start
                self._data[start:] = chunk[:split]
                self._data[: end - self._capacity] = chunk[split:]
            self._written += total

    def _copy_latest_locked(self, count: int, written: int) -> FloatArray:
        """在已持有鎖時，複製截至 written 的最後 count 個樣本。"""
        available = min(count, written, self._capacity)
        if available <= 0:
            return np.zeros(0, dtype=np.float32)
        start = (written - available) % self._capacity
        end = start + available
        if end <= self._capacity:
            return self._data[start:end].copy()
        return np.concatenate((self._data[start:], self._data[: end - self._capacity]))

    def latest(self, count: int) -> FloatArray:
        """最新的 count 個樣本，依時間順序排列。不足則前面補零。"""
        with self._lock:
            view = self._copy_latest_locked(count, self._written)

        if view.size >= count:
            return view.astype(np.float32, copy=False)
        padded = np.zeros(count, dtype=np.float32)
        padded[count - view.size :] = view
        return padded

    def read_since(self, cursor: int) -> tuple[FloatArray, int]:
        """原子取得 cursor 之後的新樣本與對應的新 cursor。

        written、視窗範圍與資料 copy 都在同一次 lock 內決定，避免 writer
        插在先讀 cursor、再 latest 的中間，造成新資料提早混入、之後又重複。
        落後超過容量時只回最後一圈，但 cursor 仍前進到真實 written 位置。
        """
        with self._lock:
            written = self._written
            pending = written - cursor
            if pending <= 0:
                return np.zeros(0, dtype=np.float32), written
            count = min(pending, self._capacity)
            return self._copy_latest_locked(count, written), written


class Analyzer:
    """把 PCM 變成畫面要的數字，以及音質面板要的結論。"""

    def __init__(self, sample_rate: int, channels: int = 2) -> None:
        self._setup(sample_rate, channels)

    def _setup(self, sample_rate: int, channels: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._ring = RingBuffer(int(sample_rate * _BUFFER_SECONDS))
        self._cursor = 0
        # 電表另外吃一份交錯的原始樣本：削波與峰值是每個聲道各自的性質，
        # 單聲道混音會把單邊撞頂藏起來（見 LevelMeter 的 docstring）。
        self._level_ring = RingBuffer(int(sample_rate * _BUFFER_SECONDS) * channels)
        self._level_cursor = 0

        self._spectrum = SpectrumProcessor(sample_rate)
        self._rolloff = RolloffAnalyzer(sample_rate)
        self._levels = LevelMeter()
        self._onset = OnsetDetector(sample_rate)
        self._onset_latch = 0.0
        self._frame = SpectrumFrame(bars=(0.0,) * SPECTRUM_BARS, peaks=(0.0,) * SPECTRUM_BARS)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    # ------------------------------------------------------- 音訊執行緒

    def push_interleaved(self, samples: FloatArray) -> None:
        """由音訊回呼呼叫。只混單聲道與寫緩衝，不做 FFT。"""
        self._ring.write(mix_to_mono(samples, self._channels))
        self._level_ring.write(samples)

    # ------------------------------------------------------- UI 執行緒

    def tick(self, dt: float) -> SpectrumFrame:
        """推進一個畫面幀。把累積的新樣本餵給慢速分析，再算出視覺化資料。"""
        fresh, self._cursor = self._ring.read_since(self._cursor)
        if fresh.size:
            self._rolloff.feed(fresh)
            if self._onset.feed(fresh):
                self._onset_latch = _ONSET_LATCH_SEC
        interleaved, self._level_cursor = self._level_ring.read_since(self._level_cursor)
        if interleaved.size:
            self._levels.feed(interleaved, self._channels)

        self._onset_latch = max(0.0, self._onset_latch - dt)
        frame = self._spectrum.process(self._ring.latest(FFT_SIZE), dt)
        self._frame = SpectrumProcessor.with_onset(frame, self._onset_latch > 0.0)
        return self._frame

    @property
    def frame(self) -> SpectrumFrame:
        """最近一次 :meth:`tick` 的結果。"""
        return self._frame

    # ------------------------------------------------------- 音質結論

    def rolloff(
        self, *, lossless_container: bool, source_sample_rate: int | None = None
    ) -> RolloffResult:
        return self._rolloff.result(lossless_container, source_sample_rate)

    def levels(self) -> LevelStats:
        return self._levels.stats()

    @property
    def analysed_frames(self) -> int:
        """已納入平均頻譜的分析框數。UI 用它顯示「量測中…」的進度。"""
        return self._rolloff.frames

    # ------------------------------------------------------- 生命週期

    def reset_track(self) -> None:
        """換歌時呼叫。清掉與曲目綁定的統計，但保留視覺化的平滑狀態，
        這樣切歌時頻譜不會整個掉到零再彈起來。"""
        self._rolloff.reset()
        self._levels.reset()
        self._onset.reset()
        self._onset_latch = 0.0
        self._cursor = self._ring.written
        self._level_cursor = self._level_ring.written

    def reconfigure(self, sample_rate: int, channels: int) -> None:
        """輸出裝置換了取樣率時重建所有分析器。

        分頻邊界、FFT 視窗、環形緩衝容量全都跟取樣率綁定，
        沒有部分更新的餘地，直接整組重建最單純。
        """
        if sample_rate == self._sample_rate and channels == self._channels:
            return
        self._setup(sample_rate, channels)
