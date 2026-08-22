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

## 交叉餵送

左聲道的反射主要送到**右**聲道，反之亦然。這模擬側牆反射的路徑
（聲音打到右牆再回到左耳），也是「空間變寬」的來源。同相直接疊回原聲道
只會變成梳狀濾波，聽起來像相位問題而不是空間。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    REFLECTION_CROSSFEED,
    REFLECTION_DECAY,
    REFLECTION_HP_HZ,
    REFLECTION_KERNEL_TAPS,
    REFLECTION_LEVEL,
    REFLECTION_LP_HZ,
    REFLECTION_TAP_MS,
)

FloatArray = npt.NDArray[np.float32]


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
    def active(self) -> bool:
        return self._amount > 1e-6 and self._channels == 2 and self._line is not None

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        if channels != 2:
            # 交叉餵送需要左右兩聲道。單聲道沒有「側牆」可言。
            self._line = None
            return

        self._delays = tuple(int(ms * sample_rate / 1000.0) for ms in REFLECTION_TAP_MS)
        # 延遲線要容得下最長的抽頭加一次完整回呼，否則寫入會追上讀取。
        capacity = max(self._delays) + max_frames + 1
        self._line = np.zeros((capacity, channels), dtype=np.float64)
        self._write = 0
        self._kernel = _bandpass_kernel(
            REFLECTION_KERNEL_TAPS, sample_rate, REFLECTION_HP_HZ, REFLECTION_LP_HZ
        )
        self._tail = np.zeros((REFLECTION_KERNEL_TAPS - 1, channels), dtype=np.float64)

    def reset(self) -> None:
        """換歌或 seek 時清掉延遲線，否則會聽到上一段的殘留反射。"""
        if self._line is not None:
            self._line.fill(0.0)
        if self._tail is not None:
            self._tail.fill(0.0)
        self._write = 0

    @property
    def latency_frames(self) -> int:
        """0。直達聲原樣通過，反射是加在它後面的。"""
        return 0

    def process(self, buf: FloatArray) -> None:
        if not self.active or self._line is None or self._tail is None:
            return
        frames = buf.size // self._channels
        if frames == 0:
            return

        view = buf.reshape(frames, self._channels)
        capacity = self._line.shape[0]

        # 1. 把這一塊寫進環形延遲線。
        indices = (self._write + np.arange(frames)) % capacity
        self._line[indices] = view

        # 2. 讀出兩個抽頭並疊加。時間差就是空間尺度。
        summed = np.zeros((frames, self._channels))
        for order, delay in enumerate(self._delays):
            taps = (self._write - delay + np.arange(frames)) % capacity
            echo = self._line[taps]
            # 交叉餵送：左聲道的反射主要落在右聲道，模擬側牆路徑。
            mixed = (
                echo * (1.0 - REFLECTION_CROSSFEED) + echo[:, ::-1] * REFLECTION_CROSSFEED
            )
            # 奇數號抽頭再對調一次左右，兩次反射才不會堆在同一側 ——
            # 都在同一側聽起來會像單邊回音，而不是一個空間。
            if order % 2 == 1:
                mixed = mixed[:, ::-1]
            # 越晚的反射越弱，這是自然的能量衰減。
            summed += mixed * (REFLECTION_DECAY**order)

        self._write = (self._write + frames) % capacity

        # 3. 帶通。低頻反射只會糊，高頻損失則是距離線索。
        filtered = np.empty_like(summed)
        for channel in range(self._channels):
            padded = np.concatenate([self._tail[:, channel], summed[:, channel]])
            convolved = np.convolve(padded, self._kernel, mode="valid")
            filtered[:, channel] = convolved[:frames]
            self._tail[:, channel] = padded[-(self._kernel.size - 1) :]

        # 4. 疊回去。直達聲完全沒被動過 —— 這是延遲為 0 的原因。
        view += (filtered * (self._level * self._amount)).astype(np.float32)
