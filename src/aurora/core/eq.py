"""10 段圖形等化器。

## 為什麼是 FIR 而不是 biquad

教科書做法是 biquad 級聯，但 IIR 在時間上是遞迴的，numpy 無法向量化 ——
只能寫 Python 迴圈。實測（2880 框、兩聲道、10 段）：

===================  ==========  ==============
做法                 平均         佔 60 ms deadline
===================  ==========  ==============
Python biquad 迴圈   394 ms      658 %
FFT overlap-add      0.414 ms    0.69 %
===================  ==========  ==============

biquad 是整個預算的 6.5 倍，不是「有點慢」而是完全不可行。所以這裡走
**線性相位 FIR + FFT overlap-add**：全程向量化，成本落在量測過的餘裕內
（S2 量到 p99 還有約 13 ms 空間）。

這是量出來的決定，不是偏好。章程 §4 的 Measure Before Optimize 要的就是
這個順序：先 profile，再決定要不要下沉 native —— 而這裡連 native 都不必。

## 代價，講清楚

* **延遲 511 框（10.6 ms）。** 線性相位 FIR 的群延遲是 ``(N-1)/2``。
  這在播放器上可以接受，在即時監聽上不行。延遲有申報，
  ``core/abcompare.py`` 可以實測驗證申報值正確。
* **預振鈴（pre-ringing）。** 線性相位的固有特性：能量會在瞬態**之前**
  就出現，最多提前 10.6 ms。中等增益下通常聽不出來，低頻段拉到 ±12 dB
  時可能可以。要根除只能改用最小相位核心，那是之後可以做的改良。
* **低頻解析度有限。** 1023 抽頭 @48k 約 47 Hz 解析度，所以 31 Hz 那一段
  實際行為接近低頻棚架而不是精確的峰值濾波。

## 自動餘裕

任何正增益都可能讓訊號超過滿刻度。這裡不是「之後再用限幅器救」，而是
**先把整條曲線壓下來**：preamp = −max(0, 最大增益)。這樣等化後的峰值
永遠不會比輸入高，限幅器就真的只是最後一道保險，不會天天在工作。

章程風險 R6（EQ + Spatial 增益疊加削波）講的就是漏掉這一步的後果。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from aurora.core.constants import EQ_BAND_HZ, EQ_FIR_TAPS, EQ_GAIN_LIMIT_DB

FloatArray = npt.NDArray[np.float32]


def design_kernel(
    gains_db: Sequence[float],
    sample_rate: int,
    taps: int = EQ_FIR_TAPS,
) -> npt.NDArray[np.float64]:
    """由各段增益做出線性相位 FIR 核心，並套上自動餘裕。

    做法：在對數頻率上把各段增益內插成完整的振幅響應 → 反 FFT 得到脈衝
    響應 → 平移成因果的對稱核心 → 加 Hann 窗抑制截斷造成的漣波。

    回傳的核心已經含 preamp，所以最大增益永遠 ≤ 0 dB。
    """
    if taps % 2 == 0:
        raise ValueError("taps 必須是奇數，線性相位的群延遲才會是整數")
    gains = np.clip(np.asarray(gains_db, dtype=np.float64), -EQ_GAIN_LIMIT_DB, EQ_GAIN_LIMIT_DB)
    if gains.size != len(EQ_BAND_HZ):
        raise ValueError(f"需要 {len(EQ_BAND_HZ)} 段增益，收到 {gains.size}")

    # 自動餘裕：整條曲線先減掉最大的正增益。EQ 之後的峰值不會比輸入高。
    headroom_db = -max(0.0, float(gains.max()))
    curve_db = gains + headroom_db

    # 在對數頻率上內插。人耳與 EQ 段距都是對數的，線性內插會讓低頻擠成一團。
    bins = taps  # 用與核心等長的 FFT 設計，避免再做一次重取樣
    freqs = np.fft.rfftfreq(bins, d=1.0 / sample_rate)
    log_freqs = np.log10(np.maximum(freqs, 1.0))
    log_bands = np.log10(np.asarray(EQ_BAND_HZ, dtype=np.float64))
    # 兩端用最外側那一段的值延伸，等同低／高頻棚架。
    magnitude_db = np.interp(log_freqs, log_bands, curve_db)
    magnitude = np.power(10.0, magnitude_db / 20.0)

    # 零相位響應 → 反 FFT → 用 fftshift 轉成因果的對稱核心。
    impulse = np.fft.irfft(magnitude, bins)
    impulse = np.roll(impulse, bins // 2)
    impulse *= np.hanning(bins)
    return impulse


class GraphicEqualizer:
    """10 段圖形等化器，滿足 :class:`~aurora.core.dsp_graph.AudioProcessor`。

    增益由主執行緒設定，核心也在主執行緒重算；回呼執行緒只做 FFT 與加總，
    不配置記憶體、不重算係數。
    """

    def __init__(self, taps: int = EQ_FIR_TAPS) -> None:
        self._taps = taps
        self._gains: tuple[float, ...] = (0.0,) * len(EQ_BAND_HZ)
        self._sample_rate = 0
        self._channels = 0
        self._nfft = 0
        self._spectrum: npt.NDArray[np.complex128] | None = None
        self._tail: npt.NDArray[np.float64] | None = None
        self._enabled = False

    # ------------------------------------------------------------ 設定

    @property
    def gains_db(self) -> tuple[float, ...]:
        return self._gains

    @property
    def headroom_db(self) -> float:
        """自動套用的 preamp（dB，永遠 ≤ 0）。UI 顯示用。"""
        return -max(0.0, max(self._gains))

    @property
    def is_flat(self) -> bool:
        """全部為 0 dB。此時 :meth:`process` 直接返回，不做任何運算。"""
        return not self._enabled

    def set_gains(self, gains_db: Sequence[float]) -> None:
        """設定各段增益並重算核心。**只能從主執行緒呼叫。**"""
        clipped = tuple(
            float(np.clip(value, -EQ_GAIN_LIMIT_DB, EQ_GAIN_LIMIT_DB)) for value in gains_db
        )
        if len(clipped) != len(EQ_BAND_HZ):
            raise ValueError(f"需要 {len(EQ_BAND_HZ)} 段增益，收到 {len(clipped)}")
        self._gains = clipped
        self._enabled = any(abs(value) > 1e-6 for value in clipped)
        self._rebuild()

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        # overlap-add 需要 nfft ≥ 區塊長度 + 核心長度 − 1。
        self._nfft = 1 << (max_frames + self._taps - 1).bit_length()
        self._max_frames = max_frames
        self._tail = np.zeros((channels, self._taps - 1), dtype=np.float64)
        self._rebuild()

    def reset(self) -> None:
        """清掉 overlap 尾巴。不清的話 seek 之後會聽到上一段的殘響。"""
        if self._tail is not None:
            self._tail.fill(0.0)

    @property
    def latency_frames(self) -> int:
        """線性相位對稱核心的群延遲。全平時沒有處理，也就沒有延遲。"""
        return 0 if not self._enabled else (self._taps - 1) // 2

    def process(self, buf: FloatArray) -> None:
        if not self._enabled or self._spectrum is None or self._tail is None:
            return
        frames = buf.size // self._channels
        if frames == 0:
            return
        # 區塊比 prepare 宣告的還大時分批做，而不是在回呼裡重新配置。
        if frames > self._max_frames:
            step = self._max_frames * self._channels
            for start in range(0, buf.size, step):
                self.process(buf[start : start + step])
            return

        view = buf.reshape(frames, self._channels)
        for channel in range(self._channels):
            spectrum = np.fft.rfft(view[:, channel], self._nfft)
            convolved = np.fft.irfft(spectrum * self._spectrum, self._nfft)
            overlap = self._tail[channel]
            convolved[: overlap.size] += overlap
            view[:, channel] = convolved[:frames].astype(np.float32)
            tail = convolved[frames : frames + overlap.size]
            overlap[: tail.size] = tail
            overlap[tail.size :] = 0.0

    # ------------------------------------------------------------ 內部

    def _rebuild(self) -> None:
        if self._sample_rate <= 0 or self._nfft <= 0 or not self._enabled:
            self._spectrum = None
            return
        kernel = design_kernel(self._gains, self._sample_rate, self._taps)
        self._spectrum = np.fft.rfft(kernel, self._nfft)


def band_label(index: int) -> str:
    """給 UI 用的頻段標籤。1000 Hz 以上顯示成 kHz。"""
    hz = EQ_BAND_HZ[index]
    if hz >= 1000.0:
        return f"{hz / 1000.0:g}k"
    return f"{hz:g}"


def gain_to_linear(db: float) -> float:
    return float(math.pow(10.0, db / 20.0))
