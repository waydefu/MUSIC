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
* **低頻解析度有限。** 1023 抽頭 @48k 約 47 Hz 解析度，31 與 62 Hz 兩段
  落在同一個解析度格子裡：頻段中心修正（見下）能讓被拉的那一段到位，
  但相鄰那一段會被一起帶動（單拉 62 Hz +12 dB 時 31 Hz 約 +7 dB）。
  要真正分開只能加長核心，也就是加延遲。

## 頻段中心修正

在對數頻率上把各段增益內插成曲線、再加窗截斷，窗的主瓣會把窄的起伏抹掉
一截 —— 以前單拉 62 Hz +12 dB 實際只得到 +5.4 dB，低音棚架也差 1.3 dB。
所以設計時反覆量「頻段中心實際得到多少」，把差額補回控制點，直到誤差小於
0.05 dB 或達到迭代上限（:data:`EQ_DESIGN_ITERATIONS`）。實務上的曲線幾次之內
就收斂到 0.2 dB 以內。這只在主執行緒設定增益時跑，回呼上的成本不變。

## 抽頭數跟著取樣率走

1023 抽頭是 48 kHz 下的**時間長度**。固定樣本數的話 192k 下解析度只剩
188 Hz，62 Hz +12 dB 實測只剩 +0.0 dB。所以抽頭數依 ``core/rates.py``
換算，延遲（毫秒）與解析度（Hz）在任何取樣率下都相同。

## 自動餘裕

任何正增益都可能讓訊號超過滿刻度。這裡不是「之後再用限幅器救」，而是
**先把整條曲線壓下來**：preamp = −max(0, 最大增益)，再依核心**實際的**最大
響應補一刀，讓振幅響應在設計格點上處處 ≤ 0 dB（格點之間實測最多再高 0.005 dB）。

注意這只保證**頻域**不放大，不保證**樣本峰值**不變大：振幅 ≤ 1 的濾波器
仍然會因為相位改變與振鈴讓峰值上升（實測只有衰減的 EQ 把一段削波過的
母帶從 0.950 推到 0.971）。所以限幅器不只是理論上的保險 —— 它是真的會
動作的那一道防線。

章程風險 R6（EQ + Spatial 增益疊加削波）講的就是漏掉這一步的後果。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    EQ_BAND_HZ,
    EQ_DESIGN_ITERATIONS,
    EQ_DESIGN_MAX_CORRECTION_DB,
    EQ_FIR_TAPS,
    EQ_GAIN_LIMIT_DB,
    EQ_WINDOW_BETA,
)
from aurora.core.rates import scaled_taps

FloatArray = npt.NDArray[np.float32]


#: 修正迴圈的收斂門檻（dB）。
_CONVERGED_DB = 0.05
#: 只修正低於 Nyquist 這個比例的頻段 —— 更高的頻段在這個取樣率下不存在。
_USABLE_NYQUIST_RATIO = 0.95


def design_kernel(
    gains_db: Sequence[float],
    sample_rate: int,
    taps: int | None = None,
) -> npt.NDArray[np.float64]:
    """由各段增益做出線性相位 FIR 核心，並套上自動餘裕。

    做法：在對數頻率上把各段增益內插成完整的振幅響應 → 反 FFT 得到零相位
    脈衝響應 → 取中央 ``taps`` 個樣本成為因果的對稱核心 → 加 Kaiser 窗。
    然後量頻段中心的實際增益、把差額補回控制點，重複到收斂（見模組 docstring）。

    ``taps`` 省略時依取樣率換算 :data:`EQ_FIR_TAPS`。回傳的核心已經含 preamp，
    振幅響應在設計格點上 ≤ 0 dB（格點之間最多再高約 0.005 dB）。
    """
    if taps is None:
        taps = scaled_taps(EQ_FIR_TAPS, sample_rate)
    if taps % 2 == 0:
        raise ValueError("taps 必須是奇數，線性相位的群延遲才會是整數")
    gains = np.clip(np.asarray(gains_db, dtype=np.float64), -EQ_GAIN_LIMIT_DB, EQ_GAIN_LIMIT_DB)
    if gains.size != len(EQ_BAND_HZ):
        raise ValueError(f"需要 {len(EQ_BAND_HZ)} 段增益，收到 {gains.size}")

    # 自動餘裕：整條曲線先減掉最大的正增益。
    desired = gains - max(0.0, float(gains.max()))

    # 設計用的格點要比核心密得多，頻段中心附近的形狀才取樣得到 —— 以前
    # 直接用核心長度當格點，48k 下格點是 0、47、94 Hz，62 Hz 根本不在上面。
    grid = 1 << (8 * taps - 1).bit_length()
    freqs = np.fft.rfftfreq(grid, d=1.0 / sample_rate)
    log_freqs = np.log10(np.maximum(freqs, 1.0))
    nyquist = sample_rate / 2.0
    # 控制點 = 十個頻段中心，外加 DC 與 Nyquist 兩個錨點（值沿用最外側那一段，
    # 等同低／高頻棚架）。沒有錨點的話，修正 31 Hz 時被抬高的控制點會把 DC
    # 一帶推過 0 dB（實測低音棚架 +1.25 dB），最後的峰值正規化再把整條曲線
    # 一起壓下去 —— 形狀是對的，卻平白多了 1 dB 的 preamp。
    bands = np.asarray((1.0, *EQ_BAND_HZ, nyquist), dtype=np.float64)
    desired = np.concatenate(([desired[0]], desired, [desired[-1]]))
    anchors = np.zeros(bands.size, dtype=bool)
    anchors[0] = anchors[-1] = True
    # 低取樣率下 Nyquist 會落在 16 kHz 那段**之前**，所以排序後錨點不一定在
    # 頭尾 —— 位置一律跟著 anchors 走，不靠索引。
    order = np.argsort(bands, kind="stable")
    bands, desired, anchors = bands[order], desired[order], anchors[order]
    log_bands = np.log10(bands)
    window = np.kaiser(taps, EQ_WINDOW_BETA)
    half = taps // 2

    # 錨點實際量在 0 Hz 與 Nyquist 的 95%；Nyquist 以上的頻段在這個取樣率下
    # 不存在，不修正。
    top = nyquist * _USABLE_NYQUIST_RATIO
    probe_hz = np.where(anchors, np.where(bands < nyquist, 0.0, top), bands)
    usable = anchors | (bands <= top)
    offsets = np.arange(taps) - half
    probe = np.exp(-2j * np.pi * np.outer(probe_hz[usable] / sample_rate, offsets))
    # 錨點只負責「不准冒出去」：實際值高於目標才往下拉，低於目標不管。
    # 雙向修正的話它會與相鄰的 31 Hz 搶同一個解析度格子，兩邊都修不準。
    anchor = anchors[usable]

    def build(controls: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        # 兩端用最外側那一段的值延伸，等同低／高頻棚架。
        magnitude = np.power(10.0, np.interp(log_freqs, log_bands, controls) / 20.0)
        impulse = np.fft.irfft(magnitude, grid)
        # 零相位脈衝響應的中央段：負時間在緩衝區尾端，接到前面成為對稱核心。
        centred = np.concatenate((impulse[-half:], impulse[: half + 1]))
        return np.asarray(centred * window, dtype=np.float64)

    controls = desired.copy()
    kernel = build(controls)
    for _ in range(EQ_DESIGN_ITERATIONS):
        realized = 20.0 * np.log10(np.maximum(np.abs(probe @ kernel), 1e-12))
        error = desired[usable] - realized
        error[anchor] = np.minimum(error[anchor], 0.0)
        if float(np.abs(error).max()) < _CONVERGED_DB:
            break
        controls[usable] = np.clip(
            controls[usable] + error,
            desired[usable] - EQ_DESIGN_MAX_CORRECTION_DB,
            desired[usable] + EQ_DESIGN_MAX_CORRECTION_DB,
        )
        kernel = build(controls)

    # 修正會讓頻段之間的曲線略微隆起，所以最後依實際最大響應再壓一次，
    # 讓振幅響應在設計格點上 ≤ 0 dB。
    peak = float(np.abs(np.fft.rfft(kernel, grid)).max())
    return kernel / max(1.0, peak)


class GraphicEqualizer:
    """10 段圖形等化器，滿足 :class:`~aurora.core.dsp_graph.AudioProcessor`。

    增益由主執行緒設定，核心也在主執行緒重算；回呼執行緒只做 FFT 與加總，
    不配置記憶體、不重算係數。
    """

    def __init__(self, taps: int = EQ_FIR_TAPS) -> None:
        #: 參考取樣率下的抽頭數；實際用的在 prepare 依取樣率換算。
        self._reference_taps = taps
        self._taps = taps
        self._max_frames = 0
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
        if clipped == self._gains and self._enabled and self._spectrum is not None:
            # 音效面板每動一格任何滑桿都會重送一次整條曲線；增益沒變就不必
            # 重跑頻段中心修正（每次數毫秒，在主執行緒上）。
            return
        self._gains = clipped
        enabled = any(abs(value) > 1e-6 for value in clipped)
        if not enabled:
            # 先關再清：回呼看到 _enabled 為 False 就不會再碰核心。
            self._enabled = False
            self._spectrum = None
            return
        spectrum = self._design()
        if not self._enabled and self._tail is not None:
            # 關著的時候尾巴留著上次開著時的殘響；不清的話重新打開的第一個
            # 回呼會混進 10 ms 的舊音訊。此刻 _enabled 仍是 False，回呼不會碰它。
            self._tail.fill(0.0)
        # 核心先就位、最後才打開 —— 回呼永遠看到一組完整的狀態。
        self._spectrum = spectrum
        self._enabled = True

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._taps = scaled_taps(self._reference_taps, sample_rate)
        # overlap-add 需要 nfft ≥ 區塊長度 + 核心長度 − 1。
        self._nfft = 1 << (max_frames + self._taps - 1).bit_length()
        self._max_frames = max_frames
        self._tail = np.zeros((channels, self._taps - 1), dtype=np.float64)
        self._spectrum = self._design() if self._enabled else None

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

    def _design(self) -> npt.NDArray[np.complex128] | None:
        """目前增益的核心頻譜。還沒 prepare 時回 ``None``。"""
        if self._sample_rate <= 0 or self._nfft <= 0:
            return None
        kernel = design_kernel(self._gains, self._sample_rate, self._taps)
        return np.fft.rfft(kernel, self._nfft)


def band_label(index: int) -> str:
    """給 UI 用的頻段標籤。1000 Hz 以上顯示成 kHz。"""
    hz = EQ_BAND_HZ[index]
    if hz >= 1000.0:
        return f"{hz / 1000.0:g}k"
    return f"{hz:g}"

