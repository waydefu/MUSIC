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

import math

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    SPATIAL_COHERENCE_SMOOTHING,
    SPATIAL_DECORRELATION_HP_HZ,
    SPATIAL_DEPTH_CURVE,
    SPATIAL_DEPTH_DB,
    SPATIAL_FFT_SIZE,
    SPATIAL_HOP,
    SPATIAL_MAKEUP_CEILING,
    SPATIAL_MAKEUP_SMOOTHING,
    SPATIAL_PANNING_KNEE,
    SPATIAL_SURROUND_LEVEL,
    SPATIAL_WIDTH,
)
from aurora.core.hrtf import HrtfFilters, synthetic_filters

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
        self._depth_db = SPATIAL_DEPTH_DB
        self._width = SPATIAL_WIDTH
        self._channels = 0
        self._ready = False
        # P2 HRTF。預設關閉 —— 關著的時候一格濾波器都不算，
        # 回呼成本與 P1 逐位元相同（§9.9 的預算決定因此不受影響）。
        self._binaural = False
        self._hrtf: HrtfFilters | None = None
        self._sample_rate = 0

        # sqrt-Hann 用於分析與合成。平方後就是 Hann，而 Hann 在 50% 重疊下
        # 相加剛好為 1 —— 這是完美重建的來源。
        window = np.hanning(fft_size + 1)[:fft_size]
        self._window = np.sqrt(window)

        bins = fft_size // 2 + 1
        self._smoothed_m = np.zeros(bins)
        self._smoothed_s = np.zeros(bins)
        self._smoothed_cross = np.zeros(bins)
        self._makeup = 1.0
        # 固定的隨機相位當去相關器。固定而非時變，這樣不會產生飄移感。
        phase = np.random.default_rng(20260822).uniform(-np.pi, np.pi, bins)
        self._decorrelator = np.exp(1j * phase)
        self._decorrelator[0] = 1.0  # DC 不去相關，否則會產生直流偏移
        self._decorrelator[-1] = 1.0

        # binaural 的環繞饋給。P1 折回立體聲時 SL/SR 是 ±u（完全反相），在
        # 立體聲下那只是加寬；但反相的一對在 M/S 推導裡「和」恆為 0，經過 HRTF
        # 之後只剩純反相的 side，實測耳間相關性掉到 −0.45 —— 聽起來是「在頭裡面」，
        # 正好是頭外化的反面。真實的 5.1 環繞是兩條互不相關的訊號，所以這裡給
        # 兩組獨立的隨機相位，並預先算好和／差，回呼上只花兩次複數乘法。
        #
        # 種子與上面的去相關器不同，否則兩者相位一致，等於沒有第二條訊號。
        surround_rng = np.random.default_rng(20260823)
        first = np.exp(1j * surround_rng.uniform(-np.pi, np.pi, bins))
        second = np.exp(1j * surround_rng.uniform(-np.pi, np.pi, bins))
        for fixed in (first, second):
            fixed[0] = 1.0     # DC 不去相關，否則會產生直流偏移
            fixed[-1] = 1.0
        self._surround_feed_sum = (first + second) * 0.5
        self._surround_feed_diff = (first - second) * 0.5

        self._lf_guard = np.ones(bins)
        # 全部預先配置。先前這三個用 np.concatenate 每個 hop 增長一次 ——
        # 那違反 dsp_graph 契約的規則 2（不得有可避免的穩態配置），而且
        # 在 2880 框的回呼下每次要跑 5.6 個 hop，配置成本會被放大。
        self._pending = np.zeros((0, 2))
        self._pending_len = 0
        self._overlap = np.zeros((fft_size, 2))
        self._emitted = np.zeros((0, 2))
        self._emit_head = 0
        self._emit_len = 0

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
    def binaural(self) -> bool:
        """是否用 HRTF renderer 取代 Basic Stereo Renderer。

        **場景建構那一步不受影響**（``_build_scene`` 原地重用），換掉的只有
        renderer —— 這正是 §9.4 要求的「與 Spatial 共用同一個 STFT」。
        """
        return self._binaural

    @binaural.setter
    def binaural(self, value: bool) -> None:
        self._binaural = bool(value)
        if self._binaural and self._sample_rate:
            self._hrtf = synthetic_filters(self._sample_rate, self._fft)

    @property
    def surround_level(self) -> float:
        """去相關環繞成分折回立體聲時的音量。"""
        return self._surround

    @surround_level.setter
    def surround_level(self, value: float) -> None:
        self._surround = float(max(0.0, value))

    @property
    def depth_db(self) -> float:
        """全開時把置中直達成分壓低多少 dB。設 0 可關掉距離機制。"""
        return self._depth_db

    @depth_db.setter
    def depth_db(self, value: float) -> None:
        self._depth_db = float(min(0.0, value))

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
        self._sample_rate = sample_rate
        # 濾波器與 STFT 綁在同一個 fft_size 上，取樣率一變就得重算。
        self._hrtf = synthetic_filters(sample_rate, self._fft) if self._binaural else None
        # 只處理立體聲。單聲道沒有左右差可分析，多聲道不在 P1 範圍。
        self._ready = channels == 2

        # 低頻護欄：去相關只作用在 SPATIAL_DECORRELATION_HP_HZ 以上。
        # 隨機相位打在低頻會讓低音聲像散開（內部研究稱 low-frequency
        # phase chaos），實測未加時 <200 Hz 的 side 能量被推高 1.09 倍。
        # 用 raised-cosine 淡入而不是硬切，硬邊會在時域造成鈴振。
        freqs = np.fft.rfftfreq(self._fft, d=1.0 / sample_rate)
        low = SPATIAL_DECORRELATION_HP_HZ * 0.5
        span = max(SPATIAL_DECORRELATION_HP_HZ - low, 1.0)
        ramp = np.clip((freqs - low) / span, 0.0, 1.0)
        self._lf_guard = 0.5 - 0.5 * np.cos(np.pi * ramp)

        # 待處理緩衝要容得下「一次最大回呼 + 一個未滿的視窗」。
        self._pending = np.zeros((max_frames + self._fft, 2))
        # 輸出佇列要容得下預填的一個視窗、加上一次回呼可能產生的所有 hop。
        self._emitted = np.zeros((self._fft + max_frames + self._hop, 2))

        self.reset()

    def reset(self) -> None:
        self._pending_len = 0
        self._overlap.fill(0.0)
        # 預填一整個視窗的靜音。不能用 self.latency_frames —— reset() 會在
        # prepare() 裡被呼叫，那時 amount 還沒設，屬性會回 0。
        self._emitted.fill(0.0)
        self._emit_head = 0
        self._emit_len = self._fft
        self._smoothed_m.fill(0.0)
        self._smoothed_s.fill(0.0)
        self._smoothed_cross.fill(0.0)
        self._makeup = 1.0

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
        if self._pending_len + frames > self._pending.shape[0]:
            # 回呼比 prepare 宣告的還大時分批做，而不是在回呼裡重新配置。
            step = self._pending.shape[0] - self._fft
            for start in range(0, buf.size, step * self._channels):
                self.process(buf[start : start + step * self._channels])
            return
        self._pending[self._pending_len : self._pending_len + frames] = view
        self._pending_len += frames

        while self._pending_len >= self._fft:
            self._advance()

        # 預填保證了這裡永遠取得到，但仍留一條安全路徑：真的不夠時把靜音
        # 補在**前面**（等同多一點延遲），而不是補在後面 —— 補後面會把
        # 串流的時間順序打亂，那比多一點延遲糟糕得多。
        if self._emit_len >= frames:
            view[:] = self._emitted[self._emit_head : self._emit_head + frames]
            self._emit_head += frames
            self._emit_len -= frames
        else:
            # 預填保證了這裡取得到，但仍留安全路徑：真的不夠時把靜音補在
            # **前面**（等同多一點延遲），補在後面會打亂串流的時間順序。
            have = self._emit_len
            view[: frames - have] = 0.0
            view[frames - have :] = self._emitted[self._emit_head : self._emit_head + have]
            self._emit_head += have
            self._emit_len = 0

    # ------------------------------------------------------------ 內部

    def _advance(self) -> None:
        """處理一個 STFT 框，並吐出一個 hop 的輸出。"""
        block = self._pending[: self._fft].copy()
        # 就地左移而不是重新配置。
        self._pending[: self._pending_len - self._hop] = self._pending[
            self._hop : self._pending_len
        ]
        self._pending_len -= self._hop

        windowed = block * self._window[:, None]
        left, right = windowed[:, 0], windowed[:, 1]
        mid = np.fft.rfft((left + right) * 0.5, self._fft)
        side = np.fft.rfft((left - right) * 0.5, self._fft)

        coherence, ambience = self._analyse(mid, side)
        scene = self._build_scene(mid, side, coherence, ambience)
        if self._binaural and self._hrtf is not None:
            out_mid, out_side = self._render_binaural(*scene, mid, side)
        else:
            out_mid, out_side = self._render_stereo(*scene, mid, side)

        synth_l = np.fft.irfft(out_mid + out_side, self._fft)
        synth_r = np.fft.irfft(out_mid - out_side, self._fft)
        synth = np.stack([synth_l, synth_r], axis=1) * self._window[:, None]

        self._overlap += synth

        # 輸出佇列：先把已消費的部分往前壓實，再附加新的一個 hop。
        if self._emit_head + self._emit_len + self._hop > self._emitted.shape[0]:
            self._emitted[: self._emit_len] = self._emitted[
                self._emit_head : self._emit_head + self._emit_len
            ]
            self._emit_head = 0
        tail = self._emit_head + self._emit_len
        self._emitted[tail : tail + self._hop] = self._overlap[: self._hop]
        self._emit_len += self._hop

        # overlap 就地左移並把尾巴清零，取代 concatenate。
        self._overlap[: -self._hop] = self._overlap[self._hop :]
        self._overlap[-self._hop :] = 0.0

    def _analyse(
        self, mid: npt.NDArray[np.complex128], side: npt.NDArray[np.complex128]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """算出每格的相關性與環境音權重。

        回傳 ``(coherence, ambience_weight)``：

        ``coherence`` ∈ −1..1
            左右有多相似。1 = 置中，0 = 不相關。

        ``ambience_weight`` ∈ 0..1
            這一格有多「無方向」，由 panning index 導出。

        **為什麼需要第二個量。** 只用 coherence 分不出「硬左偏的乾樂器」與
        「真正的環境音」—— 兩者的 coherence 都是 0（實測 0.000 對 0.006）。
        把硬左偏的樂器當環境音去相關，它就會漏到另一個聲道，定位被抹散。
        實測未修正前，硬左偏素材有 39.5% 的能量跑到原本靜音的右聲道。

        這正是文獻上的標準做法：Avendaño 與 Jot 的 upmix 框架同時使用
        inter-channel coherence 與 panning index（similarity measure），
        兩者缺一不可。章程 §1.3 從 Sennheiser 學到的
        「mix intent preservation」講的也是同一件事 —— 混音師把樂器擺在
        左邊是有意圖的，處理器不該把它搬走。

        panning index 由已有的量推出來，不必額外做 FFT::

            |L|² − |R|² = 4·Re(M·conj(S))
            |L|² + |R|² = 2(|M|² + |S|²)
            Δ = 2·Re(M·conj(S)) / (|M|² + |S|²)

        Δ = ±1 是硬左／硬右，0 是置中或左右平衡。

        **三個量都必須時間平滑。** 逐框的瞬時值抖動很大：未平滑時真環境音
        的 |Δ| 量到 0.497，跟硬左偏的 1.0 分不太開；平滑後掉到 0.168，
        差距變成 6 倍。而且不平滑的增益會讓穩定的人聲每 20 ms 被推一下，
        聽起來像有東西在呼吸。
        """
        alpha = SPATIAL_COHERENCE_SMOOTHING
        self._smoothed_m = alpha * self._smoothed_m + (1.0 - alpha) * np.abs(mid) ** 2
        self._smoothed_s = alpha * self._smoothed_s + (1.0 - alpha) * np.abs(side) ** 2
        self._smoothed_cross = alpha * self._smoothed_cross + (1.0 - alpha) * np.real(
            mid * np.conj(side)
        )

        total = np.maximum(self._smoothed_m + self._smoothed_s, _EPS)
        coherence = (self._smoothed_m - self._smoothed_s) / total
        panning = np.abs(2.0 * self._smoothed_cross / total)
        # 軟膝而不是線性。線性閘門會連「輕微偏位」的內容一起保護，而真實
        # 混音本來就充滿各種偏位的樂器 —— 實測兩支 Dolby Atmos 測試片，
        # 線性閘門平均只放行 48–66%，加寬因此幾乎聽不出來。需要保護的
        # 其實只有硬定位（|Δ|→1）。
        return coherence, np.clip(1.0 - panning**SPATIAL_PANNING_KNEE, 0.0, 1.0)

    def _build_scene(
        self,
        mid: npt.NDArray[np.complex128],
        side: npt.NDArray[np.complex128],
        coherence: npt.NDArray[np.float64],
        ambience: npt.NDArray[np.float64],
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

        # 環繞餵的是 side 乘上**環境音權重**，不是乘 (1 − centre_weight)。
        #
        # 那是一道多餘且有害的閘門：side 已經就是「左右不相關」的成分，
        # 再用相關性掐一次等於平方衰減。實測真實素材上這道閘門的中位數只有
        # 0.19，而且因為環繞副本是隨機相位、以功率相加，0.12 的相對振幅只
        # 換來 √(1+0.12²) ≈ 0.7% 的側能量 —— 效果等於零。
        #
        # 拿掉之後安全性質完全沒有退步，因為 **side 本身就是天然的閘門**：
        # 純置中的內容 side 恆為 0，人聲與低頻自動被保護。實測（surround=1.0）
        # 側能量 1.26x、人聲相關性仍為 1.000、低頻折單聲道 1.00x、瞬態集中 1.00。
        # ambience 只在「硬定位」的格子上關閉（實測硬左偏 0.000），
        # 真實混音上仍有 0.900、真環境音 0.834 —— 效果幾乎完整保留。
        # 這與被移除的 coherence 閘門正好相反：那道閘門是在**相關內容**上
        # 關閉，而相關內容就是音樂的大部分，所以它殺掉的是效果本身。
        surround_side = side * ambience * self._lf_guard * self._decorrelator
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
        amount = self._amount
        gain, width, depth = self._wet_coefficients()
        wet_mid = centre * depth + front_mid

        out_mid = dry_mid * (1.0 - amount) + wet_mid * amount
        out_side = dry_side * width + surround_side * gain

        # 響度補償：對 mid 與 side **等量**施加，所以總響度回到原本，
        # 而 D/R 比保留下來。不補的話使用者會把「變小聲」誤認成「變遠」。
        return self._compensate(out_mid, out_side, dry_mid, dry_side)

    def _wet_coefficients(self) -> tuple[float, float, float]:
        """濕訊號的三個係數：環繞增益、寬度、距離衰減。

        抽出來是因為 HRTF renderer 要用同一組值。這三條公式各自都有踩過坑
        的理由（見下面的註解），複製一份到另一個 renderer 遲早會走鐘。
        """
        amount = self._amount

        # 乾濕比要**依聽感線性**，不能直接拿去乘增益。
        #
        # 環繞副本是隨機相位，與原始 side 以功率相加：側能量是 √(1+g²)。
        # 直接讓 g = amount 的話這條曲線在低端幾乎是平的 —— 實測滑桿拉到
        # 50% 只走完 25.8% 的效果、25% 更只有 5.4%，前半段像壞掉一樣。
        #
        # 所以反過來解：先決定「側能量要走到哪」，再回推需要多少增益。
        peak = math.hypot(1.0, self._surround)      # 全開時的側能量比
        target = 1.0 + amount * (peak - 1.0)        # 想要的線性進度
        gain = math.sqrt(max(0.0, target * target - 1.0))

        # 寬度是同相成分，本來就以振幅相加，線性內插即可。
        width = 1.0 + (self._width - 1.0) * amount

        # 距離機制：把**置中的直達成分**往後推，擴散成分不動。
        #
        # 在這之前 centre + front_mid 恆等於 mid，於是
        # dry_mid*(1-a) + wet_mid*a 也恆等於 mid —— 直達聲在任何 amount 下
        # 都一動也沒動。那條恆等式就是「聽起來沒有拉遠」的成因：
        # 實測 D/R 從 0 到 100% 只變 −0.62 dB，遠低於可察覺門檻。
        depth = 10.0 ** (self._depth_db * amount**SPATIAL_DEPTH_CURVE / 20.0)
        return gain, width, depth

    def _render_binaural(
        self,
        centre: npt.NDArray[np.complex128],
        front_mid: npt.NDArray[np.complex128],
        surround_side: npt.NDArray[np.complex128],
        dry_mid: npt.NDArray[np.complex128],
        dry_side: npt.NDArray[np.complex128],
    ) -> tuple[npt.NDArray[np.complex128], npt.NDArray[np.complex128]]:
        """HRTF Renderer：把同一個場景改用頭部轉移函數送到兩耳。

        場景與 :meth:`_render_stereo` 完全相同，差別只在虛擬喇叭不再是直接
        折回左右聲道，而是各自經過該方位角的 HRTF。因為場景是 M/S 表示，
        整段可以留在 M/S 域，只要五條濾波器 —— 推導寫在 ``core/hrtf.py``
        的模組 docstring，並由 ``tests/test_hrtf.py`` 對逐喇叭參考實作驗證。

        **與 stereo renderer 的一個刻意差異**：這裡的 side 也跟乾訊號做
        交叉淡入。stereo renderer 把 width 直接乘在乾 side 上（``width=1``
        時那就是原訊號，天然透明），但 HRTF 會改變 side 的頻譜，
        不淡入的話 ``amount=0`` 就不再是旁通了。
        """
        hrtf = self._hrtf
        assert hrtf is not None  # 呼叫端已經檢查過
        amount = self._amount
        gain, width, depth = self._wet_coefficients()

        # 兩對喇叭走同一條規則：餵法的和進 mid、差進 side。環繞餵的是兩條
        # 去相關訊號（見 __init__ 的說明），所以它**也**有 mid 成分 ——
        # 那是不讓音場塌成純反相的關鍵。
        surround = surround_side * gain
        wet_mid = (
            centre * depth * hrtf.centre
            + front_mid * hrtf.front_sum
            + surround * self._surround_feed_sum * hrtf.surround_sum
        )
        wet_side = (
            dry_side * width * hrtf.front_diff
            + surround * self._surround_feed_diff * hrtf.surround_diff
        )

        out_mid = dry_mid * (1.0 - amount) + wet_mid * amount
        out_side = dry_side * (1.0 - amount) + wet_side * amount
        return self._compensate(out_mid, out_side, dry_mid, dry_side)

    def _compensate(
        self,
        out_mid: npt.NDArray[np.complex128],
        out_side: npt.NDArray[np.complex128],
        dry_mid: npt.NDArray[np.complex128],
        dry_side: npt.NDArray[np.complex128],
    ) -> tuple[npt.NDArray[np.complex128], npt.NDArray[np.complex128]]:
        """把總能量拉回處理前的水準，但不動 mid 與 side 的比例。"""
        before = float(np.sum(np.abs(dry_mid) ** 2) + np.sum(np.abs(dry_side) ** 2))
        after = float(np.sum(np.abs(out_mid) ** 2) + np.sum(np.abs(out_side) ** 2))
        if after > _EPS and before > _EPS:
            target = min(math.sqrt(before / after), SPATIAL_MAKEUP_CEILING)
        else:
            target = 1.0
        # 平滑，否則逐框變動會聽成抽吸。
        alpha = SPATIAL_MAKEUP_SMOOTHING
        self._makeup = alpha * self._makeup + (1.0 - alpha) * target
        return out_mid * self._makeup, out_side * self._makeup
