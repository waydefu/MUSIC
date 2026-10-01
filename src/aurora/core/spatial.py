"""Spatial P1：以主成分分解為基礎的虛擬 5.1 upmix。

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
環境音加寬、立體聲寬度。**前後定位與頭外化是 P2 的 HRTF renderer**，
這裡刻意不做，也做不到。

程式碼刻意分成 :meth:`_build_scene` 與 :meth:`_render_stereo` 兩步，
即使中間沒有停留。這樣之後解除強制 stereo 時，要換的只有 renderer ——
章程 §4 的「Content Analysis / Scene / Renderer 邏輯責任分離」。

## 每一格拆成「直達」與「環境」

每個頻率格被看成「一個有方向的直達聲 + 左右不相關、等功率的環境音」。
左右的 2×2 共變異矩陣做特徵分解（primary–ambient extraction，Merimaa／
Goodwin／Jot 那一路的做法）：

* **主特徵向量**是直達聲的方向。置中的人聲是 ``[1, 1]``，偏左的吉他是
  ``[1, 0.5]``，AB 麥克風錄的時間差立體聲是帶相位的 ``[1, e^{-jφ}]`` ——
  全部都是「同一個方向」，所以全部都被認成直達聲。
* **次特徵值**就是環境音在每個方向上的功率。主方向上的能量扣掉它，才是
  直達聲的能量；兩者的比值就是這一格有多少是直達（Wiener 權重）。

距離機制把**直達成分**整個往後推（mid 與 side 一起壓，聲像不動）；
加寬只作用在**環境成分**的 side 上。

### 為什麼不再用「coherence」

以前用的是 ``(|M|² − |S|²) / (|M|² + |S|²) = 2·Re(L·R*) / (|L|² + |R|²)``，
那是 Avendaño 的 *similarity*，不是相關性。它同時被「偏位」與「相位」拉動，
量出來三個問題：

* 偏左 6 dB 的乾樂器被當成一半的環境音拿去去相關，左右相關從 1.000 掉到
  0.362 —— 混音師擺好的位置被抹散。
* 距離機制只壓 mid，偏位樂器的 side 沒動，等於把它往外推：ILD 6.0 → 10.9 dB。
* 用 ``Re`` 讓時間差立體聲的判定隨頻率在 +1 與 −1 之間來回擺（0.5 ms 時
  1 kHz 是 −1、2 kHz 是 +1），輸出的 mid 多出 6 dB 的梳狀起伏。

特徵分解同時解掉這三個：方向由特徵向量表示（偏位、相位都只是方向的一部分），
直達多少由特徵值表示，而對 mid 與 side 施加的是**同一個**投影。

## 為什麼在 M/S 域算

``M = (L+R)/2``、``S = (L−R)/2`` 是 ``[L, R]`` 乘上一個正交矩陣再縮放
``1/√2``，所以 M/S 的共變異矩陣與 L/R 的有相同的特徵向量結構、特徵值只差
一個固定倍數。直接在 M/S 上分解，每框仍然只要 2 次正向、2 次反向 FFT。
在 A2 量到 EQ 已吃掉 9.22% p99 的情況下，這種省法是必要的。

## 完美重建

``surround_level = 0``、``width = 1``、``depth_db = 0`` 時，整條鏈退化成
``L = M + S``，也就是原訊號。這不是巧合而是設計：它讓「處理器沒開時完全
透明」變成一條可以自動跑的測試，也讓 amount=0 真的等於 bypass。
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    DSP_REFERENCE_RATE,
    HRTF_CUE_STRENGTH,
    SPATIAL_CENTRE_SMOOTHING_OCTAVE,
    SPATIAL_COHERENCE_SMOOTHING,
    SPATIAL_DECORRELATION_DELAY_MS,
    SPATIAL_DECORRELATION_HP_HZ,
    SPATIAL_DECORRELATION_SPREAD_MS,
    SPATIAL_DEPTH_CURVE,
    SPATIAL_DEPTH_DB,
    SPATIAL_FFT_SIZE,
    SPATIAL_HOP,
    SPATIAL_MAKEUP_CEILING,
    SPATIAL_MAKEUP_SMOOTHING,
    SPATIAL_SURROUND_LEVEL,
    SPATIAL_WIDTH,
)
from aurora.core.hrtf import (
    HrtfFilters,
    load_filters,
    resolve_profile,
    synthetic_filters,
)
from aurora.core.rates import scaled_fft_size

FloatArray = npt.NDArray[np.float32]
ComplexArray = npt.NDArray[np.complex128]
RealArray = npt.NDArray[np.float64]
#: 雙耳 renderer 需要的一整組：濾波器，以及置中補償的（對數振幅，相位）。
#: 綁在一起發佈 —— 切換 profile 時回呼不會讀到不配對的兩半。
BinauralState = tuple[HrtfFilters, RealArray, RealArray]

_EPS = 1e-12


def decorrelation_filter(
    rng: np.random.Generator, fft_size: int, sample_rate: int
) -> ComplexArray:
    """單位振幅、群延遲被限制在一段區間內的去相關濾波器（rfft 長度）。

    每一格的群延遲 ``τ_k`` 在 ``[DELAY, DELAY + SPREAD]`` 毫秒之間均勻亂數，
    相位是它的累積：``φ_k = −Σ τ_i · Δω``。振幅恆為 1（不染色），而脈衝
    響應被關在那段時間裡 —— 環形卷積繞回負時間的能量因此只剩幾 %，
    不會出現預回音。理由與實測見 :data:`SPATIAL_DECORRELATION_DELAY_MS`。
    """
    bins = fft_size // 2 + 1
    start = SPATIAL_DECORRELATION_DELAY_MS * sample_rate / 1000.0
    spread = SPATIAL_DECORRELATION_SPREAD_MS * sample_rate / 1000.0
    delays = rng.uniform(start, start + spread, bins)
    step = -delays * (2.0 * np.pi / fft_size)
    phase = np.concatenate(([0.0], np.cumsum(step[1:])))
    response = np.asarray(np.exp(1j * phase), dtype=np.complex128)
    response[0] = 1.0  # DC 不去相關，否則會產生直流偏移
    response[-1] = 1.0  # Nyquist 必須是實數
    return response


class SpatialUpmix:
    """直達／環境感知的虛擬 5.1 upmix，折回立體聲。滿足 ``AudioProcessor``。

    ``amount`` 是乾濕比：0 完全透明（且不宣稱延遲），1 為全效果。

    ``fft_size`` 與 ``hop`` 是**參考取樣率**下的長度；:meth:`prepare` 會依
    實際取樣率縮放（見 :func:`aurora.core.rates.scaled_fft_size`）。
    """

    def __init__(
        self,
        fft_size: int = SPATIAL_FFT_SIZE,
        hop: int = SPATIAL_HOP,
    ) -> None:
        if fft_size % hop != 0 or fft_size // hop != 2:
            raise ValueError("目前只支援 50% 重疊（fft_size 必須是 hop 的兩倍）")
        self._base_fft = fft_size
        self._amount = 0.0
        self._surround = SPATIAL_SURROUND_LEVEL
        self._depth_db = SPATIAL_DEPTH_DB
        self._width = SPATIAL_WIDTH
        self._channels = 0
        self._ready = False
        # P2 HRTF。預設關閉 —— 關著的時候一格濾波器都不算，
        # 回呼成本與 P1 相同（§9.9 的預算決定因此不受影響）。
        self._binaural = False
        self._binaural_state: BinauralState | None = None
        self._hrtf_measured = False
        self._hrtf_profile = ""
        self._cue_strength = HRTF_CUE_STRENGTH
        self._sample_rate = 0
        self._configure(fft_size, DSP_REFERENCE_RATE, max_frames=0)

    def _configure(self, fft_size: int, sample_rate: int, max_frames: int) -> None:
        """配置所有與視窗長度、取樣率綁定的東西。只在主執行緒、回呼沒在跑時呼叫。"""
        self._fft = fft_size
        self._hop = fft_size // 2
        bins = fft_size // 2 + 1

        # sqrt-Hann 用於分析與合成。平方後就是 Hann，而 Hann 在 50% 重疊下
        # 相加剛好為 1 —— 這是完美重建的來源。
        window = np.hanning(fft_size + 1)[:fft_size]
        self._window = np.sqrt(window)

        # 平滑係數是「每個參考 hop」的值。hop 的秒數不同時換算成同一個時間
        # 常數；參考取樣率下指數恰好是 1，數值與以前逐位元相同。
        hop_ratio = (self._hop / sample_rate) / (SPATIAL_HOP / DSP_REFERENCE_RATE)
        self._smoothing = SPATIAL_COHERENCE_SMOOTHING**hop_ratio
        self._makeup_smoothing = SPATIAL_MAKEUP_SMOOTHING**hop_ratio

        # M/S 共變異矩陣 [[a, x], [x*, b]] 的三個元素（時間平滑後）。
        self._smoothed_m = np.zeros(bins)
        self._smoothed_s = np.zeros(bins)
        self._smoothed_cross = np.zeros(bins, dtype=np.complex128)
        self._makeup = 1.0

        # 雙耳 renderer 的環繞饋給。P1 折回立體聲時 SL/SR 是 ±u（完全反相），
        # 在立體聲下那只是加寬；但反相的一對在 M/S 推導裡「和」恆為 0，經過
        # HRTF 之後只剩純反相的 side，實測耳間相關性掉到 −0.45 —— 聽起來是
        # 「在頭裡面」。真實的 5.1 環繞是兩條互不相關的訊號，所以這裡給兩條
        # 獨立的去相關濾波器，並預先算好和／差，回呼上只花兩次複數乘法。
        # 固定種子：固定而非時變，這樣不會產生飄移感，而且每次開機聽起來一樣。
        rng = np.random.default_rng(20260823)
        first = decorrelation_filter(rng, fft_size, sample_rate)
        second = decorrelation_filter(rng, fft_size, sample_rate)
        self._surround_feed_sum = (first + second) * 0.5
        self._surround_feed_diff = (first - second) * 0.5

        # 低頻護欄：環境音加寬只作用在 SPATIAL_DECORRELATION_HP_HZ 以上。
        # 用 raised-cosine 淡入而不是硬切，硬邊會在時域造成鈴振。
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
        low = SPATIAL_DECORRELATION_HP_HZ * 0.5
        span = max(SPATIAL_DECORRELATION_HP_HZ - low, 1.0)
        ramp = np.clip((freqs - low) / span, 0.0, 1.0)
        self._lf_guard = 0.5 - 0.5 * np.cos(np.pi * ramp)
        self._lf_guard_sq = np.square(self._lf_guard)

        # 置中權重沿頻率平滑用的視窗邊界（對數頻率上的固定寬度，同 hrtf._smooth_octaves）。
        ratio = 2.0 ** (SPATIAL_CENTRE_SMOOTHING_OCTAVE / 2.0)
        index = np.arange(bins, dtype=np.float64)
        self._weight_low = np.maximum(0, np.floor(index / ratio)).astype(np.int64)
        self._weight_high = np.minimum(bins, np.ceil(index * ratio).astype(np.int64) + 1)

        # 全部預先配置。先前這三個用 np.concatenate 每個 hop 增長一次 ——
        # 那違反 dsp_graph 契約的規則 2（不得有可避免的穩態配置）。
        # 待處理緩衝要容得下「一次最大回呼 + 一個未滿的視窗」。
        self._pending = np.zeros((max_frames + fft_size, 2))
        self._pending_len = 0
        self._overlap = np.zeros((fft_size, 2))
        # 輸出佇列要容得下預填的一個視窗、加上一次回呼可能產生的所有 hop。
        self._emitted = np.zeros((fft_size + max_frames + self._hop, 2))
        self._emit_head = 0
        self._emit_len = 0

    # ------------------------------------------------------------ 設定

    @property
    def amount(self) -> float:
        return self._amount

    @amount.setter
    def amount(self, value: float) -> None:
        amount = float(np.clip(value, 0.0, 1.0))
        # 從關到開時緩衝裡是它上次開著時的舊東西，不重設會少掉預填的靜音、
        # 前一個視窗的輸出也會錯位。**先重設、再改 amount**：amount 還是 0 時
        # 回呼一碰到 process 就直接返回，不會與這裡的重設同時動到 buffer。
        if amount > 1e-6 and not self.active and self._ready:
            self.reset()
        self._amount = amount

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
            self._load_hrtf(self._sample_rate)

    @property
    def hrtf_is_measured(self) -> bool:
        """目前用的是使用者自備的實測資料，還是內建的合成頭模型。

        UI 要照實顯示這件事。合成模型沒有耳廓，做不出可靠的前後區分與真正
        的頭外化 —— 讓它冒充「HRTF 已完成」會讓使用者以為功能壞了。
        """
        return self._hrtf_measured

    @property
    def hrtf_profile(self) -> str:
        """目前選用的 HRTF profile。空字串＝自動，``"synthetic"``＝內建模型。"""
        return self._hrtf_profile

    @hrtf_profile.setter
    def hrtf_profile(self, name: str) -> None:
        self._hrtf_profile = str(name)
        if self._binaural and self._sample_rate:
            self._load_hrtf(self._sample_rate)

    @property
    def cue_strength(self) -> float:
        """頻譜線索強度，1.0 ＝ 資料集原樣、0.0 ＝ 只留粗略輪廓。

        交換的是**定位準確度與音色自然度**，不是在做等化 —— 詳見
        ``core/hrtf.py`` 的 :meth:`HrtfFilters.with_cue_strength`。
        """
        return self._cue_strength

    @cue_strength.setter
    def cue_strength(self, value: float) -> None:
        self._cue_strength = float(np.clip(value, 0.0, 1.0))
        if self._binaural and self._sample_rate:
            self._load_hrtf(self._sample_rate)

    def _load_hrtf(self, sample_rate: int) -> None:
        """依 profile 載入實測資料，沒有或壞掉就退回合成模型。

        ``load_filters`` 保證不拋例外：缺檔案是正常狀態，不是錯誤。
        選了一個不存在的 profile 也一樣降級 —— 使用者刪掉檔案之後
        播放器不該就此打不開。
        """
        path = resolve_profile(self._hrtf_profile)
        measured = load_filters(sample_rate, self._fft, path) if path is not None else None
        self._hrtf_measured = measured is not None
        chosen = (measured or synthetic_filters(sample_rate, self._fft)).with_cue_strength(
            self._cue_strength
        )
        log_magnitude, phase = chosen.centre_compensation()
        self._binaural_state = (chosen, log_magnitude, phase)

    @property
    def surround_level(self) -> float:
        """環境音加寬的強度。定義見 :data:`SPATIAL_SURROUND_LEVEL`。"""
        return self._surround

    @surround_level.setter
    def surround_level(self, value: float) -> None:
        self._surround = float(max(0.0, value))

    @property
    def depth_db(self) -> float:
        """全開時把直達成分壓低多少 dB。設 0 可關掉距離機制。"""
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
        self._configure(scaled_fft_size(self._base_fft, sample_rate), sample_rate, max_frames)
        # 濾波器與 STFT 綁在同一個 fft_size 上，取樣率一變就得重算 ——
        # 實測 HRIR 也要跟著重新取樣，所以走同一條路。
        if self._binaural:
            self._load_hrtf(sample_rate)
        else:
            self._binaural_state = None
            self._hrtf_measured = False
        # 只處理立體聲。單聲道沒有左右差可分析，多聲道不在 P1 範圍。
        self._ready = channels == 2
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

        primary_mid, primary_side = self._analyse(mid, side)
        scene = self._build_scene(mid, side, primary_mid, primary_side)
        if self._binaural and self._binaural_state is not None:
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

    def _analyse(self, mid: ComplexArray, side: ComplexArray) -> tuple[ComplexArray, ComplexArray]:
        """估計這一框每一格的**直達成分**，回傳它的 ``(mid, side)``。

        M/S 共變異矩陣 ``[[a, x], [x*, b]]``（``a = ⟨|M|²⟩``、``b = ⟨|S|²⟩``、
        ``x = ⟨M·S*⟩``）的特徵值是::

            λ₁,₂ = (a+b)/2 ± d,     d = √(((a−b)/2)² + |x|²)

        模型是「一個有方向的直達聲 + 各方向等功率的環境音」，所以 ``λ₂`` 就是
        環境音在每個方向上的功率，主方向上的直達比例是 ``(λ₁ − λ₂)/λ₁``。
        直達成分 = 主方向上的投影 × 那個比例（Wiener 權重）。

        幾個會踩到的邊界，全部由特徵分解自己處理，不需要額外的閘門：

        * 純置中：方向 ``[1, 0]``（全在 mid），比例 1 ⇒ 整個 mid 都是直達。
        * 硬左偏（R 恆為 0）：``M = S``，``λ₂ = 0`` ⇒ 整格都是直達，環境成分
          是 0，一點都不會漏到右聲道。以前這要靠 panning 閘門另外擋。
        * 完全擴散：``λ₁ ≈ λ₂`` ⇒ 比例 ≈ 0，整格都是環境音。
        * 靜音：``d = 0`` ⇒ 比例 0，投影也是 0。

        **一定要時間平滑。** 逐框的瞬時共變異只有秩 1，任何一格看起來都是
        「純直達」；而且不平滑的增益會讓穩定的人聲每 20 ms 被推一下，聽起來
        像有東西在呼吸。平滑係數見 :data:`SPATIAL_COHERENCE_SMOOTHING`。
        """
        alpha = self._smoothing
        self._smoothed_m = alpha * self._smoothed_m + (1.0 - alpha) * np.abs(mid) ** 2
        self._smoothed_s = alpha * self._smoothed_s + (1.0 - alpha) * np.abs(side) ** 2
        self._smoothed_cross = alpha * self._smoothed_cross + (1.0 - alpha) * (mid * np.conj(side))

        a, b, x = self._smoothed_m, self._smoothed_s, self._smoothed_cross
        half_gap = 0.5 * (a - b)
        spread = np.sqrt(half_gap**2 + np.abs(x) ** 2)
        largest = 0.5 * (a + b) + spread
        # (λ₁−λ₂)·P = C−λ₂·I，所以 Wiener 投影直接是 (C−λ₂·I)/λ₁。
        # 不必建特徵向量再正規化，也不必除以四次方單位的 norm。舊版把 norm
        # 夾到 1e-12，安靜的純直達聲因此被誤認成環境音（音量一變，分類也變）。
        # 唯一的零除情況是精確靜音；不對非零能量設定絕對振幅下限。
        scale = np.zeros_like(largest)
        np.divide(1.0, largest, out=scale, where=largest > 0.0)
        primary_mid = ((spread + half_gap) * mid + x * side) * scale
        primary_side = (np.conj(x) * mid + (spread - half_gap) * side) * scale
        return primary_mid, primary_side

    def _build_scene(
        self,
        mid: ComplexArray,
        side: ComplexArray,
        primary_mid: ComplexArray,
        primary_side: ComplexArray,
    ) -> tuple[ComplexArray, ComplexArray, ComplexArray]:
        """由 M/S 與直達成分建出虛擬 5.1 場景。

        回傳 ``(primary_mid, primary_side, ambience_side)``：直達聲在 mid 與
        side 上的分量，以及要送去環繞喇叭的環境音 side。之所以不是六聲道
        陣列，是因為左右在 M/S 域是對稱的：``FL/FR`` 由 mid ± side 得到，
        ``SL/SR`` 由 ``±ambience_side`` 得到。用 M/S 表示同一個場景，
        可以少一半的運算。

        環繞只拿環境成分的 **side**：直達聲不進環繞（混音師擺好的位置不該被
        搬走），而環境音的 mid 本來就在前方留著。純置中的內容 side 恆為 0，
        人聲與低頻因此天然被保護。

        **LFE 在 P1 是空的。** 折回立體聲時它只會原封不動加回兩個聲道，
        什麼都不會改變；要等真正的多聲道輸出才有意義。
        """
        return primary_mid, primary_side, side - primary_side

    def _render_stereo(
        self,
        primary_mid: ComplexArray,
        primary_side: ComplexArray,
        ambience_side: ComplexArray,
        dry_mid: ComplexArray,
        dry_side: ComplexArray,
    ) -> tuple[ComplexArray, ComplexArray]:
        """Basic Stereo Renderer：把場景折回兩聲道。

        * **距離**：直達成分的 mid 與 side 一起往後推，聲像不動。
        * **加寬**：環境音的 side 乘上 ``√(1 + (g·guard)²)``。

        加寬以前是「把隨機相位的環境音副本加回 side」。副本與原訊號同源，
        相加其實是乘上 ``1 + g·D`` 這個濾波器：每一格的增益落在
        ``|1 − g|``～``1 + g`` 之間（實測有音高的立體聲鋪底，各音高差到
        −20～+9 dB），「以功率相加」只在平均上成立；而且隨機相位的脈衝響應
        鋪滿整個視窗，瞬態前 25 ms 就開始出聲。折回立體聲時兩個環繞聲道本來
        就要以 ±u 疊回 side，去相關在這裡沒有任何作用（side 與自己的濾波
        副本相加，耳間相關性一點都沒變）—— 它剩下的只有染色與預回音。
        直接乘上同樣的**能量倍率**，平均效果完全相同，兩個副作用都消失。

        ``surround_level = 0``、``width = 1``、``depth_db = 0`` 時結果恰好是
        原訊號 —— 所有修正項的係數都是精確的 0。這個恆等式是
        「沒開就完全透明」那條測試的基礎。

        P2 的 HRTF renderer 會取代這個方法，場景建構那一步不動。
        """
        gain, width, depth = self._wet_coefficients()
        pushback = self._amount * (1.0 - depth)
        widen = np.sqrt(1.0 + (gain * gain) * self._lf_guard_sq) - 1.0

        out_mid = dry_mid - primary_mid * pushback
        out_side = dry_side * width - primary_side * pushback + ambience_side * widen

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
        # 環繞以能量倍率 1 + g² 作用：側能量是 √(1+g²)。直接讓 g = amount
        # 的話這條曲線在低端幾乎是平的 —— 實測滑桿拉到 50% 只走完 25.8% 的
        # 效果、25% 更只有 5.4%，前半段像壞掉一樣。
        #
        # 所以反過來解：先決定「側能量要走到哪」，再回推需要多少增益。
        peak = math.hypot(1.0, self._surround)      # 全開時的側能量比
        target = 1.0 + amount * (peak - 1.0)        # 想要的線性進度
        gain = math.sqrt(max(0.0, target * target - 1.0))

        # 寬度是同相成分，本來就以振幅相加，線性內插即可。
        width = 1.0 + (self._width - 1.0) * amount

        # 距離機制：把**直達成分**往後推，擴散成分不動。
        #
        # 在這之前直達聲在任何 amount 下都一動也沒動 —— 那就是「聽起來沒有
        # 拉遠」的成因：實測 D/R 從 0 到 100% 只變 −0.62 dB，遠低於可察覺門檻。
        depth = 10.0 ** (self._depth_db * amount**SPATIAL_DEPTH_CURVE / 20.0)
        return gain, width, depth

    def _render_binaural(
        self,
        primary_mid: ComplexArray,
        primary_side: ComplexArray,
        ambience_side: ComplexArray,
        dry_mid: ComplexArray,
        dry_side: ComplexArray,
    ) -> tuple[ComplexArray, ComplexArray]:
        """HRTF Renderer：把同一個場景改用頭部轉移函數送到兩耳。

        場景與 :meth:`_render_stereo` 完全相同，差別只在虛擬喇叭不再是直接
        折回左右聲道，而是各自經過該方位角的 HRTF。因為場景是 M/S 表示，
        整段可以留在 M/S 域，只要四條濾波器 —— 推導寫在 ``core/hrtf.py``
        的模組 docstring，並由 ``tests/test_hrtf.py`` 對逐喇叭參考實作驗證。

        **直達聲只走 ±30° 那一對，沒有 0° 中置喇叭。** 這等於把立體聲當成
        兩支真喇叭來聽：左聲道在 −30°、右聲道在 +30°，置中的人聲是兩支喇叭
        在中間形成的 phantom center，偏位的樂器則保留混音師用兩聲道音量差
        擺好的位置。

        以前直達聲的 mid 會按「有多置中」分一份進 0° 中置喇叭。同一個聲源同時
        走 0° 與 ±30° 兩條路徑，複數相加的干涉把偏位樂器的 ILD 吃掉了：偏左
        6 dB 的輸入在 2–6 kHz 是 −1.4 dB，方向反過來（正確是 +4.0 dB，全頻
        +0.7 對 +4.0 dB）。把 ``centred`` 取 4 次方、8 次方都修不好 —— 那是
        結構問題，不是曲線的問題。

        只拿掉中置喇叭的代價是 phantom center 的音色：置中內容在 1.5 kHz
        凹 8.5 dB。所以直達聲在這條路徑上另外乘一個**左右耳共用的複數因子**
        （:meth:`HrtfFilters.centre_compensation`），依這一格有多置中加權：
        置中時補回中置喇叭的響應，偏位時完全不動。共用的因子不改變兩耳的
        振幅比與相位差，所以補償不會碰到 ILD 與 ITD。

        **與 stereo renderer 的一個刻意差異**：這裡的 side 也跟乾訊號做
        交叉淡入。stereo renderer 把 width 直接乘在乾 side 上（``width=1``
        時那就是原訊號，天然透明），但 HRTF 會改變 side 的頻譜，
        不淡入的話 ``amount=0`` 就不再是旁通了。
        """
        state = self._binaural_state
        assert state is not None  # 呼叫端已經檢查過
        hrtf, log_magnitude, phase = state
        amount = self._amount
        gain, width, depth = self._wet_coefficients()

        # 距離：直達成分整個往後推，與 stereo renderer 同一個定義。
        push = 1.0 - depth
        near_mid = dry_mid - primary_mid * push
        near_side = dry_side - primary_side * push

        # 這一格的直達聲有多置中：``2·|P_L|·|P_R| / (|P_L|² + |P_R|²)``，
        # 置中是 1、偏左 6 dB 是 0.8、硬偏位是 0。只看左右振幅不看相位 ——
        # 看相位的話，時間差立體聲又會隨頻率在置中與偏位之間來回跳。
        direct_l = np.abs(primary_mid + primary_side) ** 2
        direct_r = np.abs(primary_mid - primary_side) ** 2
        power = direct_l + direct_r
        centred = 2.0 * np.sqrt(direct_l * direct_r) / np.maximum(power, _EPS)

        # **權重要沿頻率平滑**（直達功率加權）。它會變成相位的乘數 ``w·φ``，
        # 每一格各自算的話相鄰格的 ``w`` 差很多，相位在頻率方向上亂跳，脈衝
        # 響應鋪滿視窗而繞回負時間 —— 實測擴散瞬態前的能量被抬到 −15 dB。
        # 見 :data:`SPATIAL_CENTRE_SMOOTHING_OCTAVE`。
        weighted = np.concatenate(([0.0], np.cumsum(centred * power)))
        total = np.concatenate(([0.0], np.cumsum(power)))
        low, high = self._weight_low, self._weight_high
        weight = (weighted[high] - weighted[low]) / np.maximum(total[high] - total[low], _EPS)
        shared = np.exp(weight * (log_magnitude + 1j * phase))

        # 兩對喇叭走同一條規則：餵法的和進 mid、差進 side。環繞餵的是兩條
        # 去相關訊號（見 _configure 的說明），所以它**也**有 mid 成分 ——
        # 那是不讓音場塌成純反相的關鍵。
        surround = ambience_side * (gain * self._lf_guard)
        wet_mid = (
            near_mid * hrtf.front_sum * shared
            + surround * self._surround_feed_sum * hrtf.surround_sum
        )
        wet_side = (
            near_side * width * hrtf.front_diff * shared
            + surround * self._surround_feed_diff * hrtf.surround_diff
        )

        out_mid = dry_mid * (1.0 - amount) + wet_mid * amount
        out_side = dry_side * (1.0 - amount) + wet_side * amount
        return self._compensate(out_mid, out_side, dry_mid, dry_side)

    def _compensate(
        self,
        out_mid: ComplexArray,
        out_side: ComplexArray,
        dry_mid: ComplexArray,
        dry_side: ComplexArray,
    ) -> tuple[ComplexArray, ComplexArray]:
        """把總能量拉回處理前的水準，但不動 mid 與 side 的比例。"""
        before = float(np.sum(np.abs(dry_mid) ** 2) + np.sum(np.abs(dry_side) ** 2))
        after = float(np.sum(np.abs(out_mid) ** 2) + np.sum(np.abs(out_side) ** 2))
        if after > _EPS and before > _EPS:
            target = min(math.sqrt(before / after), SPATIAL_MAKEUP_CEILING)
        else:
            target = 1.0
        # 平滑，否則逐框變動會聽成抽吸。
        alpha = self._makeup_smoothing
        self._makeup = alpha * self._makeup + (1.0 - alpha) * target
        return out_mid * self._makeup, out_side * self._makeup
