"""Spatial P1：以頻譜相關性為基礎的虛擬 5.1 upmix。

## 邊界（``PROJECT_PLAN.md`` §5.1，這一節不可以含糊）

::

    Stereo
      → Virtual 5.1 Scene      （FL FR C LFE SL SR，**僅為內部表示**）
      → Basic Stereo Renderer
      → 2ch output

**5.1 在 P1 是中介表示，不是輸出格式。** 解碼器目前強制 stereo
（``engine.py`` 把 ``OUTPUT_CHANNELS`` 直接餵給 ``stream_file``），
根本沒有 5.1 輸出路徑可走 —— folding 回 stereo 是唯一選項，不是妥協。

P1 的 Basic Stereo Renderer 只負責：中置／前方重建、ambience folding、
去相關的環繞貢獻、立體聲寬度。**前後定位與頭外化是 P2 的 HRTF renderer**，
這裡刻意不做，也做不到。

程式碼刻意分成 :meth:`_build_scene` 與 :meth:`_render_stereo` 兩步，
即使中間沒有停留。這樣之後解除強制 stereo 時，要換的只有 renderer ——
章程 §4 的「Content Analysis / Scene / Renderer 邏輯責任分離」。

## 為什麼在 M/S 域算

L/R 的相關性可以完全由 M/S 推出來（已驗證）::

    Re(L·conj(R)) == |M|² − |S|²
    |L|² + |R|²   == 2(|M|² + |S|²)

所以每個 STFT 框只要 2 次正向、2 次反向 FFT，不必分別轉 L 與 R。
在 A2 量到 EQ 已吃掉 9.22% p99 的情況下，這種省法是必要的。

## 相關性怎麼讀

``c = (|M|² − |S|²) / (|M|² + |S|²)``，時間平滑後落在 −1..1：

* ``c ≈ 1``：左右幾乎相同 —— 人聲、貝斯、大鼓這類置中內容。
* ``c ≈ 0``：左右不相關 —— 殘響、環境音、寬鋪底。
* ``c < 0``：反相 —— 刻意的相位技巧，或有問題的母帶。

置中的部分要**保持穩定**（拉歪人聲是最容易被聽出來的失敗），
不相關的部分才拿去做環繞。這就是「coherence-aware」的意思。

## 完美重建

``surround_level = 0``、``width = 1`` 時，整條鏈退化成 ``L = M + S``，
也就是原訊號。這不是巧合而是設計：它讓「處理器沒開時完全透明」
變成一條可以自動跑的測試，也讓 amount=0 真的等於 bypass。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    SPATIAL_COHERENCE_SMOOTHING,
    SPATIAL_FFT_SIZE,
    SPATIAL_HOP,
    SPATIAL_SURROUND_LEVEL,
    SPATIAL_WIDTH,
)

FloatArray = npt.NDArray[np.float32]

_EPS = 1e-12


class SpatialUpmix:
    """相關性感知的虛擬 5.1 upmix，折回立體聲。滿足 ``AudioProcessor``。

    ``amount`` 是乾濕比：0 完全透明（且不宣稱延遲），1 為全效果。
    """

    def __init__(
        self,
        fft_size: int = SPATIAL_FFT_SIZE,
        hop: int = SPATIAL_HOP,
    ) -> None:
        if fft_size % hop != 0 or fft_size // hop != 2:
            raise ValueError("目前只支援 50% 重疊（fft_size 必須是 hop 的兩倍）")
        self._fft = fft_size
        self._hop = hop
        self._amount = 0.0
        self._surround = SPATIAL_SURROUND_LEVEL
        self._width = SPATIAL_WIDTH
        self._channels = 0
        self._ready = False

        # sqrt-Hann 用於分析與合成。平方後就是 Hann，而 Hann 在 50% 重疊下
        # 相加剛好為 1 —— 這是完美重建的來源。
        window = np.hanning(fft_size + 1)[:fft_size]
        self._window = np.sqrt(window)

        bins = fft_size // 2 + 1
        self._smoothed_m = np.zeros(bins)
        self._smoothed_s = np.zeros(bins)
        # 固定的隨機相位當去相關器。固定而非時變，這樣不會產生飄移感。
        phase = np.random.default_rng(20260822).uniform(-np.pi, np.pi, bins)
        self._decorrelator = np.exp(1j * phase)
        self._decorrelator[0] = 1.0  # DC 不去相關，否則會產生直流偏移
        self._decorrelator[-1] = 1.0

        self._pending = np.zeros((0, 2))
        self._overlap = np.zeros((fft_size, 2))
        self._emitted = np.zeros((0, 2))

    # ------------------------------------------------------------ 設定

    @property
    def amount(self) -> float:
        return self._amount

    @amount.setter
    def amount(self, value: float) -> None:
        was_active = self.active
        self._amount = float(np.clip(value, 0.0, 1.0))
        # 從關到開時緩衝是空的，不重設會少掉預填的靜音，
        # 前 1024 框的輸出就會錯位。
        if self.active and not was_active:
            self.reset()

    @property
    def surround_level(self) -> float:
        """去相關環繞成分折回立體聲時的音量。"""
        return self._surround

    @surround_level.setter
    def surround_level(self, value: float) -> None:
        self._surround = float(max(0.0, value))

    @property
    def width(self) -> float:
        """原始 side 成分的寬度倍率。1.0 = 不改變原本的立體聲寬度。"""
        return self._width

    @width.setter
    def width(self, value: float) -> None:
        self._width = float(max(0.0, value))

    @property
    def active(self) -> bool:
        return self._amount > 1e-6 and self._ready

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._channels = channels
        # 只處理立體聲。單聲道沒有左右差可分析，多聲道不在 P1 範圍。
        self._ready = channels == 2
        self.reset()

    def reset(self) -> None:
        self._pending = np.zeros((0, 2))
        self._overlap = np.zeros((self._fft, 2))
        # 預填一整個視窗的靜音。不能用 self.latency_frames —— reset() 會在
        # prepare() 裡被呼叫，那時 amount 還沒設，屬性會回 0。
        self._emitted = np.zeros((self._fft, 2))
        self._smoothed_m.fill(0.0)
        self._smoothed_s.fill(0.0)

    @property
    def latency_frames(self) -> int:
        """延遲等於一整個視窗，**不是** ``fft − hop``。

        ``fft − hop`` 是 STFT 的演算法延遲，但輸出只能以 hop 為單位產生，
        而回呼大小是裝置決定的任意值。要讓任何 block 大小都不 underrun，
        輸出佇列必須預填滿一個完整視窗 —— 已用模擬驗證 ``fft − hop``
        的預填在 block=64／2880 時會 underrun。

        那多出來的一個 hop 一樣是聽得到的延遲，所以要誠實申報進來。
        amount=0 時沒有處理，也就沒有延遲。
        """
        return 0 if not self.active else self._fft

    def process(self, buf: FloatArray) -> None:
        if not self.active:
            return
        frames = buf.size // self._channels
        if frames == 0:
            return

        view = buf.reshape(frames, self._channels)
        self._pending = np.concatenate([self._pending, view.astype(np.float64)])

        while self._pending.shape[0] >= self._fft:
            self._advance()

        # 預填保證了這裡永遠取得到，但仍留一條安全路徑：真的不夠時把靜音
        # 補在**前面**（等同多一點延遲），而不是補在後面 —— 補後面會把
        # 串流的時間順序打亂，那比多一點延遲糟糕得多。
        if self._emitted.shape[0] >= frames:
            wet = self._emitted[:frames]
            self._emitted = self._emitted[frames:]
        else:
            have = self._emitted.shape[0]
            wet = np.zeros((frames, 2))
            wet[frames - have :] = self._emitted
            self._emitted = self._emitted[have:]

        view[:] = wet.astype(np.float32)

    # ------------------------------------------------------------ 內部

    def _advance(self) -> None:
        """處理一個 STFT 框，並吐出一個 hop 的輸出。"""
        block = self._pending[: self._fft]
        self._pending = self._pending[self._hop :]

        windowed = block * self._window[:, None]
        left, right = windowed[:, 0], windowed[:, 1]
        mid = np.fft.rfft((left + right) * 0.5, self._fft)
        side = np.fft.rfft((left - right) * 0.5, self._fft)

        coherence = self._coherence(mid, side)
        scene = self._build_scene(mid, side, coherence)
        out_mid, out_side = self._render_stereo(*scene, mid, side)

        synth_l = np.fft.irfft(out_mid + out_side, self._fft)
        synth_r = np.fft.irfft(out_mid - out_side, self._fft)
        synth = np.stack([synth_l, synth_r], axis=1) * self._window[:, None]

        self._overlap += synth
        self._emitted = np.concatenate([self._emitted, self._overlap[: self._hop]])
        self._overlap = np.concatenate(
            [self._overlap[self._hop :], np.zeros((self._hop, 2))]
        )

    def _coherence(
        self, mid: npt.NDArray[np.complex128], side: npt.NDArray[np.complex128]
    ) -> npt.NDArray[np.float64]:
        """時間平滑的每格相關性，落在 −1..1。

        一定要平滑。逐框的瞬時值抖動很大，直接拿去當增益會讓穩定的人聲
        每 20 ms 就被推一下，聽起來像有東西在呼吸。
        """
        power_m = np.abs(mid) ** 2
        power_s = np.abs(side) ** 2
        alpha = SPATIAL_COHERENCE_SMOOTHING
        self._smoothed_m = alpha * self._smoothed_m + (1.0 - alpha) * power_m
        self._smoothed_s = alpha * self._smoothed_s + (1.0 - alpha) * power_s
        total = self._smoothed_m + self._smoothed_s
        return (self._smoothed_m - self._smoothed_s) / np.maximum(total, _EPS)

    def _build_scene(
        self,
        mid: npt.NDArray[np.complex128],
        side: npt.NDArray[np.complex128],
        coherence: npt.NDArray[np.float64],
    ) -> tuple[
        npt.NDArray[np.complex128],
        npt.NDArray[np.complex128],
        npt.NDArray[np.complex128],
    ]:
        """由 M/S 與相關性建出虛擬 5.1 場景。

        回傳 ``(centre, front_mid, surround_side)``。之所以只有三個而不是
        六聲道陣列，是因為左右在 M/S 域是對稱的：``FL/FR`` 由
        ``front_mid ± side`` 得到，``SL/SR`` 由 ``±surround_side`` 得到。
        用 M/S 表示同一個場景，可以少一半的運算。

        **LFE 在 P1 是空的。** 折回立體聲時它只會原封不動加回兩個聲道，
        什麼都不會改變；要等真正的多聲道輸出才有意義。
        """
        centre_weight = np.clip(coherence, 0.0, 1.0)
        centre = mid * centre_weight
        front_mid = mid * (1.0 - centre_weight)
        # 不相關的成分拿去做環繞，並用固定隨機相位去相關，
        # 否則折回立體聲時它會塌回中間，等於什麼都沒做。
        surround_side = side * (1.0 - centre_weight) * self._decorrelator
        return centre, front_mid, surround_side

    def _render_stereo(
        self,
        centre: npt.NDArray[np.complex128],
        front_mid: npt.NDArray[np.complex128],
        surround_side: npt.NDArray[np.complex128],
        dry_mid: npt.NDArray[np.complex128],
        dry_side: npt.NDArray[np.complex128],
    ) -> tuple[npt.NDArray[np.complex128], npt.NDArray[np.complex128]]:
        """Basic Stereo Renderer：把場景折回兩聲道。

        ``surround_level = 0`` 且 ``width = 1`` 時結果恰好是原訊號 ——
        ``centre + front_mid == mid``，``side`` 原樣通過。這個恆等式是
        「沒開就完全透明」那條測試的基礎。

        P2 的 HRTF renderer 會取代這個方法，場景建構那一步不動。
        """
        wet_mid = centre + front_mid
        wet_side = dry_side * self._width + surround_side * self._surround
        amount = self._amount
        return (
            dry_mid * (1.0 - amount) + wet_mid * amount,
            dry_side * (1.0 - amount) + wet_side * amount,
        )
