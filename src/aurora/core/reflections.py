"""早期反射：兩個離散抽頭，用來給出「舞台深度」。

## 這一級要解決什麼

D/R 控制（``core/spatial.py`` 的 depth）已經能把直達聲往後推，但那只改變
「遠近」的**比例**，沒有給出「這是一個空間」的線索。人耳判斷空間大小
靠的是**最早幾個反射的到達時間**——牆越遠，第一次反射越晚。

所以這裡放兩個離散抽頭，時間差就是空間尺度。

## 絕對不做 reverb 尾巴

只有兩個抽頭、**沒有回授**。一旦加入回授就會長出殘響尾巴，而那會立刻
把「空間感」變成「浴室」——那是這一級最容易搞砸的方式，也是它刻意
保持簡陋的原因。

## 為什麼不增加延遲

直達聲**原樣通過**，反射是加在它後面的。所以 :attr:`latency_frames`
是 0——這一級可以白拿，不必付延遲代價。這是它與 STFT 類處理的根本差別。

## 頻段限制

反射會做帶通：

* **高通**——低頻反射只會讓聲音變糊，而且低頻的方向性線索本來就弱。
  這與 ``spatial.py`` 的低頻護欄是同一個理由。
* **低通**——真實牆面反射會損失高頻（空氣吸收 + 材質吸收），
  這本身就是一個距離線索。不做的話反射會聽起來像數位回音。

## 兩條 renderer

**立體聲（``binaural`` 關閉）**：左聲道的反射主要送到**右**聲道，反之亦然。
這模擬側牆反射的路徑（聲音打到右牆再回到左耳），也是「空間變寬」的來源。
同相直接疊回原聲道只會變成梳狀濾波，聽起來像相位問題而不是空間。

**雙耳（``binaural`` 開啟）**：交叉餵送是「沒有 HRTF 可用時對側牆路徑的
近似」。有 HRTF 之後就不必近似了——兩個抽頭改成兩面**虛擬牆**（左牆、
右牆），各自經過該方位角的頭部轉移函數。

頭外化靠的正是這件事：直達聲與反射來自**不同方向**，而不是同一個方向的
兩份延遲副本。實機聽測剩下的缺口是後方聲源「在腦裡」（PROJECT_PLAN §10.4），
交叉餵送做不出來，因為它給兩耳的差別只有振幅，既沒有 ITD 也沒有頻譜線索。

### 為什麼只要兩次卷積

左右牆對稱，所以可以直接套用 ``core/hrtf.py`` 那條 M/S 捷徑——
**餵法的和進 mid、差進 side**::

    L = s0*h_i + s1*h_c          M = (s0+s1)/2 * (h_i+h_c)
    R = s0*h_c + s1*h_i     =>   S = (s0-s1)/2 * (h_i-h_c)

``h_i±h_c`` 正是 renderer 已經算好的 ``surround_sum`` / ``surround_diff``，
所以佈局音色補償與空間精準度自動跟著走，這裡不另立第二套 HRTF 處理。
卷積次數因此是 **2 次**，而不是「兩個抽頭 × 兩耳 = 4 次」。

濾波器與帶通在 :meth:`prepare` 就先合成成一條核心（頻域相乘一次），
回呼上看到的只是一條 :data:`REFLECTION_HRTF_TAPS` 抽頭的 FIR。
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    HRTF_CUE_STRENGTH,
    REFLECTION_CROSSFEED,
    REFLECTION_DECAY,
    REFLECTION_HP_HZ,
    REFLECTION_HRTF_FFT_SIZE,
    REFLECTION_HRTF_TAPS,
    REFLECTION_KERNEL_TAPS,
    REFLECTION_LEVEL,
    REFLECTION_LP_HZ,
    REFLECTION_NEAR_SHARE,
    REFLECTION_TAP_MS,
)
from aurora.core.hrtf import load_filters, resolve_profile, synthetic_filters

FloatArray = npt.NDArray[np.float32]
Kernels = tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]

#: 避免除以零。
_EPS = 1e-12


def _bandpass_kernel(
    taps: int, sample_rate: int, low_hz: float, high_hz: float
) -> npt.NDArray[np.float64]:
    """窗化 sinc 帶通核心。

    用 FIR 而不是一階遞迴濾波器，理由與 ``core/eq.py`` 選 FIR 相同：
    IIR 在時間上遞迴，numpy 無法向量化，只能寫 Python 迴圈。
    """
    if taps % 2 == 0:
        raise ValueError("taps 必須是奇數，這樣群延遲才是整數")
    n = np.arange(taps) - (taps - 1) // 2

    def sinc_lowpass(cutoff: float) -> npt.NDArray[np.float64]:
        f = cutoff / sample_rate
        return np.asarray(2.0 * f * np.sinc(2.0 * f * n), dtype=np.float64)

    kernel = sinc_lowpass(high_hz) - sinc_lowpass(low_hz)
    kernel *= np.hamming(taps)
    return np.asarray(kernel, dtype=np.float64)


class EarlyReflections:
    """兩個離散早期反射，滿足 ``AudioProcessor``。

    ``amount`` 與空間音效共用同一個使用者滑桿；0 時完全透明。
    ``binaural`` 跟著空間音效的耳機空間化開關走——反射的 renderer 要與
    直達聲的 renderer 一致，否則兩者的空間線索會互相矛盾。
    """

    def __init__(self) -> None:
        self._amount = 0.0
        self._level = REFLECTION_LEVEL
        self._channels = 0
        self._sample_rate = 0
        self._delays: tuple[int, ...] = ()
        self._line: npt.NDArray[np.float64] | None = None
        self._write = 0
        self._kernel: npt.NDArray[np.float64] = np.zeros(0)
        self._tail: npt.NDArray[np.float64] | None = None
        self._capacity = 0

        # 雙耳 renderer。預設關閉——關著的時候與 P1 逐位元相同。
        self._binaural = False
        self._hrtf_profile = ""
        self._cue_strength = HRTF_CUE_STRENGTH
        self._hrtf_measured = False
        # 兩條合成核心（和／差）。None 代表走立體聲交叉餵送那條路。
        self._binaural_kernels: Kernels | None = None
        self._binaural_tail: npt.NDArray[np.float64] | None = None

        # 工作 buffer 一律在 prepare 配好（dsp_graph 契約規則 2）。
        self._summed: npt.NDArray[np.float64] = np.zeros((0, 2))
        self._pad: npt.NDArray[np.float64] = np.zeros((0, 2))
        self._feed: npt.NDArray[np.float64] = np.zeros((0, 2))

    # ------------------------------------------------------------ 設定

    @property
    def amount(self) -> float:
        return self._amount

    @amount.setter
    def amount(self, value: float) -> None:
        self._amount = float(np.clip(value, 0.0, 1.0))

    @property
    def level(self) -> float:
        """反射相對直達聲的音量。刻意保守 —— 過量就會變成回音。"""
        return self._level

    @level.setter
    def level(self, value: float) -> None:
        self._level = float(max(0.0, value))

    @property
    def binaural(self) -> bool:
        """反射是否經過 HRTF。跟著空間音效的耳機空間化開關。"""
        return self._binaural

    @binaural.setter
    def binaural(self, value: bool) -> None:
        if bool(value) == self._binaural:
            return
        self._binaural = bool(value)
        self._build_binaural_kernels()

    @property
    def hrtf_profile(self) -> str:
        return self._hrtf_profile

    @hrtf_profile.setter
    def hrtf_profile(self, name: str) -> None:
        if name == self._hrtf_profile:
            return
        self._hrtf_profile = name
        self._build_binaural_kernels()

    @property
    def cue_strength(self) -> float:
        return self._cue_strength

    @cue_strength.setter
    def cue_strength(self, value: float) -> None:
        strength = float(np.clip(value, 0.0, 1.0))
        if strength == self._cue_strength:
            return
        self._cue_strength = strength
        self._build_binaural_kernels()

    @property
    def hrtf_is_measured(self) -> bool:
        """反射用的是實測資料還是合成模型。診斷用。"""
        return self._hrtf_measured

    @property
    def active(self) -> bool:
        return self._amount > 1e-6 and self._channels == 2 and self._line is not None

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        if channels != 2:
            # 交叉餵送與左右牆都需要兩聲道。單聲道沒有「側牆」可言。
            self._line = None
            self._binaural_kernels = None
            return

        self._delays = tuple(int(ms * sample_rate / 1000.0) for ms in REFLECTION_TAP_MS)
        # 延遲線要容得下最長的抽頭加一次完整回呼，否則寫入會追上讀取。
        # 比 max_frames 更大的回呼由 process() 切塊處理，不在回呼上重配。
        self._capacity = max(1, max_frames)
        capacity = max(self._delays) + self._capacity + 1
        self._line = np.zeros((capacity, channels), dtype=np.float64)
        self._write = 0
        self._kernel = _bandpass_kernel(
            REFLECTION_KERNEL_TAPS, sample_rate, REFLECTION_HP_HZ, REFLECTION_LP_HZ
        )
        self._tail = np.zeros((REFLECTION_KERNEL_TAPS - 1, channels), dtype=np.float64)
        self._binaural_tail = np.zeros((REFLECTION_HRTF_TAPS - 1, channels), dtype=np.float64)

        longest = max(REFLECTION_KERNEL_TAPS, REFLECTION_HRTF_TAPS) - 1
        self._summed = np.zeros((self._capacity, channels))
        self._feed = np.zeros((self._capacity, channels))
        self._pad = np.zeros((longest + self._capacity, channels))
        self._build_binaural_kernels()

    def _build_binaural_kernels(self) -> None:
        """把 HRTF 與帶通合成成兩條時域核心。**主執行緒**，不在回呼上。

        合成在頻域做一次（``irfft(H * B)``），回呼上就只剩一條 FIR。
        截斷長度見 :data:`REFLECTION_HRTF_TAPS` 的註解——那個數字是量出來的。

        任何問題都退回合成模型，與 ``spatial.py`` 的 ``_load_hrtf`` 同一個
        原則：缺檔案是正常狀態，不是錯誤。
        """
        if not self._binaural or self._sample_rate <= 0 or self._kernel.size == 0:
            self._binaural_kernels = None
            self._hrtf_measured = False
            return

        size = REFLECTION_HRTF_FFT_SIZE
        path = resolve_profile(self._hrtf_profile)
        measured = load_filters(self._sample_rate, size, path) if path is not None else None
        self._hrtf_measured = measured is not None
        filters = (measured or synthetic_filters(self._sample_rate, size)).with_cue_strength(
            self._cue_strength
        )

        # 借用環繞那一對——REFLECTION_AZIMUTH_DEG 與 HRTF_SURROUND_AZIMUTH_DEG
        # 刻意相同（有測試釘住這個關係），所以不必再解析一次資料集。
        #
        # 要的是**近耳／遠耳**而不是 ``surround_sum``／``surround_diff``：
        # 後者含有 ``_PAIR_SHARE`` 的 0.5，那個 0.5 屬於 renderer 的場景代數
        # （``centre + front_mid == mid`` 這個恆等式給一對喇叭的權重是 1），
        # 反射這裡沒有那條恆等式。直接拿來用會讓每面牆各少 6 dB。
        _, _, _, ipsi, contra = filters.ear_responses()
        band = np.fft.rfft(self._kernel, n=size)
        taps = REFLECTION_HRTF_TAPS
        kernel_sum = np.asarray(np.fft.irfft((ipsi + contra) * band, n=size)[:taps])
        kernel_diff = np.asarray(np.fft.irfft((ipsi - contra) * band, n=size)[:taps])

        # 與立體聲那條路等響度。**這不是調味，是 A/B 的前提**：兩條 renderer
        # 之間應該只差「方向」，夾帶音量差的話盲測比到的會是音量（章程 §15
        # 的 0.5 dB 門檻）。
        #
        # 倍率是推出來的，不是試出來的。置中內容下兩面牆收到同樣的訊號，
        # 而兩個抽頭的延遲不同、能量上可視為互不相關，於是::
        #
        #     雙耳總能量 = (E0+E1)·(|h_i|² + |h_c|²)
        #     立體聲總能量 = (E0+E1)·2        （交叉餵送的權重和為 1，兩聲道）
        #
        # 所以要讓 ``|h_i|² + |h_c|²`` 回到 2。用和／差表示是同一件事
        # （``|a+b|² + |a−b|² == 2|a|² + 2|b|²``），省一次 irfft。
        #
        # 兩條核心乘**同一個**倍率——分開正規化會改動 mid／side 的比例，
        # 那等於偷偷改掉空間感，而那正是要拿來比較的東西。
        # 用算的而不是寫死常數：頭部遮蔽的深度每個 profile 都不同。
        energy = float(np.sum(np.square(kernel_sum)) + np.sum(np.square(kernel_diff)))
        scale = 2.0 * float(np.sqrt(np.sum(np.square(self._kernel)))) / max(
            math.sqrt(energy), _EPS
        )
        self._binaural_kernels = (kernel_sum * scale, kernel_diff * scale)

    def reset(self) -> None:
        """換歌或 seek 時清掉延遲線，否則會聽到上一段的殘留反射。"""
        if self._line is not None:
            self._line.fill(0.0)
        if self._tail is not None:
            self._tail.fill(0.0)
        if self._binaural_tail is not None:
            self._binaural_tail.fill(0.0)
        self._write = 0

    @property
    def latency_frames(self) -> int:
        """0。直達聲原樣通過，反射是加在它後面的。

        雙耳 renderer 也是 0：HRTF 的延遲全都落在**反射**上，直達聲那一路
        一個樣本都沒被碰。
        """
        return 0

    def process(self, buf: FloatArray) -> None:
        if not self.active or self._line is None or self._tail is None:
            return
        frames = buf.size // self._channels
        if frames == 0:
            return

        view = buf.reshape(frames, self._channels)
        # 回呼可能比 prepare 宣告的 max_frames 大（例如離線推進）。切塊處理，
        # 而不是在回呼上重新配置延遲線——後者才是真正會咬人的那一個。
        start = 0
        while start < frames:
            stop = min(start + self._capacity, frames)
            self._process_block(view[start:stop])
            start = stop

    def _process_block(self, view: npt.NDArray[np.float32]) -> None:
        assert self._line is not None and self._tail is not None
        frames = view.shape[0]
        capacity = self._line.shape[0]

        # 1. 把這一塊寫進環形延遲線。
        indices = (self._write + np.arange(frames)) % capacity
        self._line[indices] = view

        # 2. 讀出兩個抽頭。時間差就是空間尺度。
        summed = self._summed[:frames]
        summed.fill(0.0)
        binaural = self._binaural_kernels
        for order, delay in enumerate(self._delays):
            taps = (self._write - delay + np.arange(frames)) % capacity
            echo = self._line[taps]
            # 越晚的反射越弱，這是自然的能量衰減。
            decay = REFLECTION_DECAY**order
            if binaural is None:
                # 交叉餵送：左聲道的反射主要落在右聲道，模擬側牆路徑。
                mixed = (
                    echo * (1.0 - REFLECTION_CROSSFEED)
                    + echo[:, ::-1] * REFLECTION_CROSSFEED
                )
                # 奇數號抽頭再對調一次左右，兩次反射才不會堆在同一側 ——
                # 都在同一側聽起來會像單邊回音，而不是一個空間。
                if order % 2 == 1:
                    mixed = mixed[:, ::-1]
                summed += mixed * decay
            else:
                # 每個抽頭是一面牆：偶數號在左牆、奇數號在右牆。牆會反射
                # 整個節目，只是近側的內容佔多數——只餵一個聲道的話那面牆
                # 會漏掉對側的內容，兩條 renderer 的響度也就對不起來。
                # 對側**耳**的路徑不必在這裡處理，遠耳響應 h_c 會算。
                wall = order % 2
                near = echo[:, wall] * REFLECTION_NEAR_SHARE
                far = echo[:, 1 - wall] * (1.0 - REFLECTION_NEAR_SHARE)
                summed[:, wall] += (near + far) * decay

        self._write = (self._write + frames) % capacity

        if binaural is None:
            self._render_stereo(view, summed)
        else:
            self._render_binaural(view, summed, binaural)

    def _render_stereo(
        self, view: npt.NDArray[np.float32], summed: npt.NDArray[np.float64]
    ) -> None:
        """帶通之後直接疊回去。低頻反射只會糊，高頻損失則是距離線索。"""
        assert self._tail is not None
        filtered = self._convolve(summed, self._kernel, self._tail)
        # 直達聲完全沒被動過 —— 這是延遲為 0 的原因。
        view += (filtered * (self._level * self._amount)).astype(np.float32)

    def _render_binaural(
        self,
        view: npt.NDArray[np.float32],
        summed: npt.NDArray[np.float64],
        kernels: Kernels,
    ) -> None:
        """兩面虛擬牆各自經過自己方位角的 HRTF。

        和／差在卷積**之前**就先做掉，所以兩條核心各卷積一次就夠——
        推導見模組 docstring。帶通已經合進核心裡，這裡不再另外做一次。
        """
        assert self._binaural_tail is not None
        frames = summed.shape[0]
        feed = self._feed[:frames]
        # 和進 mid、差進 side。寫進 feed 而不是就地改 summed —— 第二行還要
        # 讀原本的值，就地做會拿到已經被覆寫的 mid。用 out= 直接寫進預先
        # 配置的 buffer，省掉四個中間陣列。
        np.add(summed[:, 0], summed[:, 1], out=feed[:, 0])
        np.subtract(summed[:, 0], summed[:, 1], out=feed[:, 1])
        feed *= 0.5

        rendered = self._convolve(feed, kernels, self._binaural_tail)
        mid = rendered[:, 0]
        side = rendered[:, 1]

        gain = self._level * self._amount
        view[:, 0] += ((mid + side) * gain).astype(np.float32)
        view[:, 1] += ((mid - side) * gain).astype(np.float32)

    def _convolve(
        self,
        signal: npt.NDArray[np.float64],
        kernel: npt.NDArray[np.float64] | Kernels,
        tail: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """逐聲道 overlap-save 卷積，結果就地寫回 ``signal``。

        ``kernel`` 給單一陣列時兩個聲道共用，給 tuple 時逐聲道各一條。
        pad buffer 在 prepare 配好，所以這裡不再 ``np.concatenate``——
        那是每個回呼一次的可避免配置（dsp_graph 契約規則 2）。
        """
        frames = signal.shape[0]
        for channel in range(signal.shape[1]):
            current = kernel[channel] if isinstance(kernel, tuple) else kernel
            overlap = current.size - 1
            pad = self._pad[: overlap + frames, channel]
            pad[:overlap] = tail[:overlap, channel]
            pad[overlap:] = signal[:, channel]
            signal[:, channel] = np.convolve(pad, current, mode="valid")[:frames]
            tail[:overlap, channel] = pad[-overlap:]
        return signal
