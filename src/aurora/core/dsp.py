"""訊號處理：即時頻譜、頻譜截止量測、響度與削波統計。

這裡的每個類別都是純狀態機 —— 餵 PCM 進去、拿數字出來，不碰 Qt 也不碰音訊裝置。
所以可以直接對合成訊號（已知截止頻率的低通噪音、滿刻度方波）做單元測試。
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    ANALYSIS_FFT_SIZE,
    BAR_ATTACK,
    BAR_DECAY,
    CLIP_RUN_LENGTH,
    CLIP_THRESHOLD,
    FAKE_LOSSLESS_CUTOFF_HZ,
    FFT_SIZE,
    PEAK_GRAVITY,
    PEAK_HOLD_SEC,
    ROLLING_MAX_DECAY,
    ROLLOFF_ANALYSIS_LIMIT_RATIO,
    ROLLOFF_FLOOR_DB,
    ROLLOFF_LIMITED_LABEL,
    ROLLOFF_MIN_FRAMES,
    ROLLOFF_TIERS,
    SPECTRUM_BARS,
    SPECTRUM_FREQ_MAX,
    SPECTRUM_FREQ_MIN,
)
from aurora.core.models import LevelStats, RolloffResult, SpectrumFrame

FloatArray = npt.NDArray[np.float32]

#: 條狀圖的 dB 底線。低於此值視為靜音。
_BAR_FLOOR_DB = -72.0
#: RMS 顯示的 dB 底線。
_RMS_FLOOR_DB = -60.0
#: 自動增益的上下限，避免安靜段落被放大成雜訊牆。
_GAIN_MIN, _GAIN_MAX = 1.0, 2.5
#: 低頻脈動取樣的上限頻率。
_BASS_MAX_HZ = 150.0
#: 分析框的能量門檻；低於此值不計入平均頻譜（避免靜音前奏拉低平均）。
_ANALYSIS_MIN_RMS = 1e-4

_EPS = 1e-10


def mix_to_mono(interleaved: FloatArray, channels: int) -> FloatArray:
    """把交錯的多聲道 PCM 混成單聲道。長度不整除時捨去尾巴的殘框。"""
    if channels <= 1:
        return np.asarray(interleaved, dtype=np.float32)
    usable = (interleaved.size // channels) * channels
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = interleaved[:usable].reshape(-1, channels)
    return np.asarray(frames.mean(axis=1), dtype=np.float32)


def log_band_edges(
    sample_rate: int,
    bars: int = SPECTRUM_BARS,
    fft_size: int = FFT_SIZE,
    freq_min: float = SPECTRUM_FREQ_MIN,
    freq_max: float = SPECTRUM_FREQ_MAX,
) -> npt.NDArray[np.int32]:
    """算出 ``bars + 1`` 個對數分佈的 FFT 分箱邊界，並保證嚴格遞增。

    低頻處多個頻段會落在同一個分箱上，這時強制往上推一格 ——
    寧可讓最低幾條的頻率略偏，也不要出現寬度為零的空條。
    """
    nyquist = sample_rate / 2.0
    top = min(freq_max, nyquist * 0.99)
    edges_hz = np.logspace(math.log10(freq_min), math.log10(top), bars + 1)
    bin_width = sample_rate / fft_size
    edges = np.round(edges_hz / bin_width).astype(np.int32)

    max_bin = fft_size // 2
    for index in range(1, edges.size):
        if edges[index] <= edges[index - 1]:
            edges[index] = edges[index - 1] + 1
    return np.clip(edges, 0, max_bin).astype(np.int32)


class SpectrumProcessor:
    """即時視覺化用的頻譜處理器：快攻慢放 + 峰值重力 + 自動增益。"""

    def __init__(
        self,
        sample_rate: int,
        bars: int = SPECTRUM_BARS,
        fft_size: int = FFT_SIZE,
    ) -> None:
        self._sample_rate = sample_rate
        self._bars = bars
        self._fft_size = fft_size
        self._window = np.hanning(fft_size).astype(np.float32)
        self._edges = log_band_edges(sample_rate, bars, fft_size)
        self._values = np.zeros(bars, dtype=np.float32)
        self._peaks = np.zeros(bars, dtype=np.float32)
        self._peak_velocity = np.zeros(bars, dtype=np.float32)
        self._hold = np.zeros(bars, dtype=np.float32)
        self._rolling_max = 0.5
        bass_limit = float(np.searchsorted(self._edges, _BASS_MAX_HZ * fft_size / sample_rate))
        self._bass_bands = max(1, int(bass_limit))

    @property
    def band_edges(self) -> npt.NDArray[np.int32]:
        return self._edges

    def _raw_bands(self, mono: FloatArray) -> FloatArray:
        """單聲道 PCM → 每個頻段的正規化強度（0..1，尚未平滑）。"""
        if mono.size < self._fft_size:
            padded = np.zeros(self._fft_size, dtype=np.float32)
            padded[: mono.size] = mono
        else:
            padded = mono[-self._fft_size :].astype(np.float32, copy=False)

        spectrum = np.abs(np.fft.rfft(padded * self._window)) / (self._fft_size / 2)
        decibels = 20.0 * np.log10(np.maximum(spectrum, _EPS))
        normalized = np.clip((decibels - _BAR_FLOOR_DB) / -_BAR_FLOOR_DB, 0.0, 1.0)

        bands = np.zeros(self._bars, dtype=np.float32)
        for index in range(self._bars):
            low, high = int(self._edges[index]), int(self._edges[index + 1])
            segment = normalized[low:high]
            if segment.size:
                bands[index] = segment.max()
        return bands

    def process(self, mono: FloatArray, dt: float) -> SpectrumFrame:
        """推進一幀。``dt`` 是距離上一幀的秒數，用來讓峰值下墜與畫面更新率脫鉤。"""
        bands = self._raw_bands(mono)

        # 自動增益：讓安靜的曲子也填得滿，但設上限避免把底噪放大成雜訊牆
        frame_max = float(bands.max()) if bands.size else 0.0
        self._rolling_max = max(self._rolling_max * ROLLING_MAX_DECAY, frame_max)
        gain = float(np.clip(1.0 / max(self._rolling_max, 0.35), _GAIN_MIN, _GAIN_MAX))
        bands = np.clip(bands * gain, 0.0, 1.0)

        # 快攻慢放
        rising = bands > self._values
        coefficient = np.where(rising, BAR_ATTACK, BAR_DECAY).astype(np.float32)
        self._values += (bands - self._values) * coefficient

        # 峰值標記：被頂上去後停留一段時間，然後以固定重力落下
        bumped = self._values >= self._peaks
        self._peaks = np.where(bumped, self._values, self._peaks)
        self._peak_velocity = np.where(bumped, 0.0, self._peak_velocity + PEAK_GRAVITY * dt)
        self._hold = np.where(bumped, PEAK_HOLD_SEC, np.maximum(self._hold - dt, 0.0))
        falling = (~bumped) & (self._hold <= 0.0)
        self._peaks = np.where(falling, self._peaks - self._peak_velocity * dt, self._peaks)
        self._peaks = np.maximum(self._peaks, self._values)

        rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
        rms_db = 20.0 * math.log10(max(rms, _EPS))
        rms_norm = float(np.clip((rms_db - _RMS_FLOOR_DB) / -_RMS_FLOOR_DB, 0.0, 1.0))
        bass = float(self._values[: self._bass_bands].mean()) if self._bars else 0.0

        return SpectrumFrame(
            bars=tuple(float(value) for value in self._values),
            peaks=tuple(float(value) for value in np.clip(self._peaks, 0.0, 1.0)),
            rms=rms_norm,
            bass=bass,
        )

    def reset(self) -> None:
        self._values[:] = 0.0
        self._peaks[:] = 0.0
        self._peak_velocity[:] = 0.0
        self._hold[:] = 0.0
        self._rolling_max = 0.5

    @staticmethod
    def with_onset(frame: SpectrumFrame, onset: bool) -> SpectrumFrame:
        """把鼓點旗標併入一幀。onset 由 :mod:`aurora.core.onset` 另外算。"""
        return replace(frame, onset=onset)


class RolloffAnalyzer:
    """累積長窗平均頻譜，量測這首歌實際的頻譜截止頻率。

    這是真正從 PCM 量出來的音質指標 —— 它抓得到「副檔名是 FLAC，
    但其實是 128kbps MP3 轉檔」這種假無損檔案。
    """

    def __init__(self, sample_rate: int, fft_size: int = ANALYSIS_FFT_SIZE) -> None:
        self._sample_rate = sample_rate
        self._fft_size = fft_size
        self._window = np.hanning(fft_size).astype(np.float32)
        self._accumulator = np.zeros(fft_size // 2 + 1, dtype=np.float64)
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames = 0

    @property
    def frames(self) -> int:
        return self._frames

    def reset(self) -> None:
        self._accumulator[:] = 0.0
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames = 0

    def feed(self, mono: FloatArray) -> None:
        """餵入單聲道 PCM。內部自行切窗，呼叫端不必對齊。"""
        if mono.size:
            self._pending = np.concatenate((self._pending, mono.astype(np.float32, copy=False)))

        while self._pending.size >= self._fft_size:
            block = self._pending[: self._fft_size]
            self._pending = self._pending[self._fft_size :]
            # 近乎靜音的區塊不計入，否則會把平均頻譜整個壓低
            if float(np.sqrt(np.mean(np.square(block)))) < _ANALYSIS_MIN_RMS:
                continue
            magnitude = np.abs(np.fft.rfft(block * self._window))
            self._accumulator += magnitude
            self._frames += 1

    def cutoff_hz(self) -> float | None:
        """回傳能量高於底線的最高頻率；資料不足回傳 ``None``。"""
        if self._frames < ROLLOFF_MIN_FRAMES:
            return None
        average = self._accumulator / self._frames
        peak = float(average.max())
        if peak <= 0.0:
            return None
        decibels = 20.0 * np.log10(np.maximum(average / peak, _EPS))
        above = np.flatnonzero(decibels > ROLLOFF_FLOOR_DB)
        if above.size == 0:
            return None
        return float(above[-1]) * self._sample_rate / self._fft_size

    def result(
        self,
        lossless_container: bool,
        source_sample_rate: int | None = None,
    ) -> RolloffResult:
        """把量到的截止頻率翻譯成人看得懂的結論。"""
        cutoff = self.cutoff_hz()
        if cutoff is None:
            return RolloffResult(enough_data=False)
        return classify_rolloff(
            cutoff,
            lossless_container=lossless_container,
            source_sample_rate=source_sample_rate or self._sample_rate,
            # 分析器跑在引擎的取樣率上，不是檔案的。兩者不同時這件事決定了
            # 量測結果能不能拿來下結論，所以一定要往下傳。
            analysis_sample_rate=self._sample_rate,
        )


def _analysis_ceiling_reached(
    cutoff_hz: float, source_sample_rate: int, analysis_sample_rate: int
) -> bool:
    """量到的截止是不是分析鏈自己的天花板，而不是內容的收斂。

    只有引擎取樣率低於來源時才可能發生：高頻在重取樣那一步就沒了，
    分析器再怎麼量都只會量到自己的 Nyquist 附近。
    """
    if analysis_sample_rate <= 0 or analysis_sample_rate >= source_sample_rate:
        return False
    return cutoff_hz >= analysis_sample_rate / 2.0 * ROLLOFF_ANALYSIS_LIMIT_RATIO


def classify_rolloff(
    cutoff_hz: float,
    *,
    lossless_container: bool,
    source_sample_rate: int,
    analysis_sample_rate: int | None = None,
) -> RolloffResult:
    """把截止頻率對照成品質級距，並判斷是否為假無損。

    ``analysis_sample_rate`` 是**量測當下**的取樣率（引擎的，不是檔案的）。
    引擎被對齊到比來源低的端點時，高頻在進分析器之前就被重取樣濾掉了，
    這時拿量到的截止去查表會得到「12 kHz ⇒ 96 kbps 以下」這種完全錯誤的
    結論，甚至反過來指控一個真無損檔案是轉檔的。回報過的案例：端點短暫報出
    24 kHz、引擎跟著切下去，一首 320 kbps 的 MP3 就被標成「96 kbps 以下」。
    不傳這個參數時行為與以前完全相同。
    """
    # 撞到天花板時，量到的截止是**下界**而不是實際值：真正的截止只會更高。
    # 下界本身就落在最高級距時（例：96 kHz 來源跑在 48 kHz 引擎上，天花板
    # 24 kHz），「至少到 20.5 kHz」這個結論仍然成立，照常判定；只有下界落在
    # 較低級距時，查表才會把分析鏈的限制誤讀成「來源只有這麼好」。
    if (
        analysis_sample_rate is not None
        and cutoff_hz < ROLLOFF_TIERS[0][0]
        and _analysis_ceiling_reached(cutoff_hz, source_sample_rate, analysis_sample_rate)
    ):
        return RolloffResult(
            enough_data=True,
            cutoff_hz=cutoff_hz,
            label=ROLLOFF_LIMITED_LABEL,
            analysis_limited=True,
        )

    label = ROLLOFF_TIERS[-1][1]
    estimated: int | None = ROLLOFF_TIERS[-1][2]
    for threshold, tier_label, kbps in ROLLOFF_TIERS:
        if cutoff_hz >= threshold:
            label, estimated = tier_label, kbps
            break

    nyquist = source_sample_rate / 2.0
    suspected = (
        lossless_container
        and nyquist > FAKE_LOSSLESS_CUTOFF_HZ
        and cutoff_hz < FAKE_LOSSLESS_CUTOFF_HZ
    )
    return RolloffResult(
        enough_data=True,
        cutoff_hz=cutoff_hz,
        label=label,
        estimated_kbps=estimated,
        suspected_transcode=suspected,
    )


class LevelMeter:
    """累積式響度／削波統計。

    「動態範圍」這裡採波峰因數（peak − RMS），不是 EBU R128 或 TT-DR 的
    正式定義 —— UI 上會照實標注，不假裝是官方指標。

    削波數的語意是**事件數**：一段連續超過滿刻度的樣本算一次，
    連段跨區塊也會正確接續。所以一首整段爆掉的歌不會顯示幾十萬，
    而是顯示它實際有幾處撞頂。
    """

    def __init__(self) -> None:
        self._square_sum = 0.0
        self._samples = 0
        self._peak = 0.0
        self._clipped = 0
        self._run = 0

    def reset(self) -> None:
        self._square_sum = 0.0
        self._samples = 0
        self._peak = 0.0
        self._clipped = 0
        self._run = 0

    def feed(self, mono: FloatArray) -> None:
        if mono.size == 0:
            return
        magnitude = np.abs(mono)
        self._square_sum += float(np.sum(np.square(mono, dtype=np.float64)))
        self._samples += int(mono.size)
        self._peak = max(self._peak, float(magnitude.max()))
        self._count_clipping(magnitude >= CLIP_THRESHOLD)

    def _count_clipping(self, hot: npt.NDArray[np.bool_]) -> None:
        """數出長度達 ``CLIP_RUN_LENGTH`` 的滿刻度連段，狀態跨區塊延續。"""
        for value in hot:
            if value:
                self._run += 1
                if self._run == CLIP_RUN_LENGTH:
                    self._clipped += 1
            else:
                self._run = 0

    def stats(self) -> LevelStats:
        if self._samples == 0:
            return LevelStats(
                rms_db=-math.inf,
                peak_db=-math.inf,
                dynamic_range_db=0.0,
                clipped_runs=0,
            )
        rms = math.sqrt(self._square_sum / self._samples)
        rms_db = 20.0 * math.log10(max(rms, _EPS))
        peak_db = 20.0 * math.log10(max(self._peak, _EPS))
        return LevelStats(
            rms_db=rms_db,
            peak_db=peak_db,
            dynamic_range_db=max(0.0, peak_db - rms_db),
            clipped_runs=self._clipped,
        )
