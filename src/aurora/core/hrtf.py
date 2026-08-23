"""P2 HRTF：合成球形頭模型，以及 renderer 需要的 M/S 濾波器對。

## 為什麼 HRTF 不必再開一組 STFT，也不必多做一次 FFT

§9.4 量出來的結論是「P2 的 HRTF renderer 必須與 Spatial 共用同一個 STFT」。
把場景留在 M/S 域之後，可以比那個要求更省：**連 FFT 次數都不用增加。**

推導。虛擬喇叭對稱擺放，右側 ``+θ`` 的喇叭到**近耳**的轉移函數記為
``H_i(θ)``、到**遠耳**記為 ``H_c(θ)``；左側 ``−θ`` 依頭部左右對稱互換。
一對喇叭餵 ``(a, b)``（左、右）時，兩耳收到的是::

    L_ear = a·H_i + b·H_c
    R_ear = a·H_c + b·H_i

轉回 M/S（``M = (L+R)/2``、``S = (L−R)/2``）之後交叉項整組消掉，只剩::

    M ← (a+b)/2 · H_sum(θ)      其中 H_sum(θ)  = H_i(θ) + H_c(θ)
    S ← (a−b)/2 · H_diff(θ)          H_diff(θ) = H_i(θ) − H_c(θ)

**兩對喇叭走的是同一條規則**：餵法的和進 mid、差進 side。代進場景
（見 ``spatial.py`` 的 ``_build_scene``）::

    C                → 置中喇叭，兩耳相同
    FL / FR = front_mid ± s          ⇒ 和 = front_mid、差 = s
    SL / SR = u·D₁ , u·D₂            ⇒ 和 = u·(D₁+D₂)/2、差 = u·(D₁−D₂)/2

於是::

    M_out = C·H_0 + front_mid·H_sum(30°) + u·(D₁+D₂)/2 · H_sum(110°)
    S_out =         s·H_diff(30°)        + u·(D₁−D₂)/2 · H_diff(110°)

也就是**每格五次複數乘法**，然後照舊兩次 irfft 得到左右耳 —— 與 Basic
Stereo Renderer 完全相同的 FFT 次數。頭部的相位差（ITD）與頻率相依的遮蔽
（ILD）全部藏在複數值裡，不需要額外的延遲線。

``D₁``、``D₂`` 是兩組固定的隨機相位。**環繞不能餵 ±u。** P1 折回立體聲時
SL/SR 就是 ±u（完全反相），那在立體聲下只是加寬；但反相的一對在上面的式子
裡和恆為 0，經過 HRTF 之後只剩純反相的 side，實測耳間相關性掉到 −0.45，
聽起來是「在頭裡面」—— 正好是頭外化的反面。真實的 5.1 環繞本來就是兩條
互不相關的訊號，所以這裡給兩組獨立的去相關。

這個化簡成立的前提是**場景左右對稱**。P1 的場景天生對稱（M/S 表示法本身
就是對稱的），所以現在成立；哪天做了 re-panning 讓個別物件不對稱，這條
捷徑就要重推。

## 為什麼先做合成模型而不是直接載 SADIE II

測試要能在無頭環境、沒有任何資料檔的情況下判定 renderer 的數學對不對。
合成模型有**解析解**：ITD 有閉式公式、ILD 隨頻率單調上升、正中央必須
左右相等。真人量測的 HRIR 沒有解析解，只能做回歸比對 —— 那抓不到
「方位角號誤植」「左右接反」這類錯誤，而那正是這一層最容易寫錯的地方。

資料集（SADIE II，Apache-2.0，**不進版控**）在下一步接上，介面就是
:class:`HrtfFilters`：從 SOFA 讀到的 HRIR 一樣可以轉成同一組 sum/diff 對。

## 模型出處與精確度

* **ITD** 用 Woodworth 的球面繞射近似 ``τ(θ) = (a/c)(θ + sin θ)``。
* **ILD／頭部遮蔽** 用 Brown–Duda 的單極點近似：低頻繞得過去（增益趨近 1），
  高頻被頭擋住（遠耳衰減）。

兩者都是**近似**，不是量測。它們給得出正確的方向、正確的頻率趨勢與正確
的量級，足以驗證 renderer；但耳廓造成的高頻凹陷（前後判別的主要線索）
不在模型裡，所以合成模型**做不出可靠的前後區分**，也做不出真正的頭外化。
那要等真人資料集。UI 上不能拿合成模型冒充 HRTF 完成品。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    HEAD_RADIUS_M,
    HRTF_FRONT_AZIMUTH_DEG,
    HRTF_SHADOW_MIN_GAIN,
    HRTF_SURROUND_AZIMUTH_DEG,
    SOUND_SPEED_MPS,
)

ComplexArray = npt.NDArray[np.complex128]


@dataclass(frozen=True, slots=True)
class HrtfFilters:
    """renderer 要用的五條頻域濾波器，全部是 rfft 長度的複數陣列。

    這是 renderer 與資料來源之間的唯一介面：合成模型與之後的 SADIE II
    SOFA 載入器都產生這個型別，``spatial.py`` 不需要知道差別。
    """

    #: 置中喇叭到兩耳（左右相同，所以只有一條）。
    centre: ComplexArray
    #: 前方喇叭對的和 —— 作用在 mid 成分上。
    front_sum: ComplexArray
    #: 前方喇叭對的差 —— 作用在 side 成分上，ITD／ILD 都在這裡。
    front_diff: ComplexArray
    #: 環繞喇叭對的和。環繞餵的是兩條去相關訊號而不是 ±u，所以它**也**有
    #: mid 成分 —— 那正是不讓音場變成純反相的關鍵（見模組 docstring）。
    surround_sum: ComplexArray
    #: 環繞喇叭對的差。
    surround_diff: ComplexArray

    @classmethod
    def from_ear_pairs(
        cls,
        centre: ComplexArray,
        front: tuple[ComplexArray, ComplexArray],
        surround: tuple[ComplexArray, ComplexArray],
    ) -> HrtfFilters:
        """由「近耳／遠耳」的原始響應組出 sum/diff 形式。

        資料集給的一律是左右耳（或近／遠耳）的 HRIR，轉換在這裡做一次，
        renderer 就永遠只看得到 M/S 需要的那五條。之後接 SADIE II 的
        SOFA 載入器，也是把讀到的 HRIR 做 rfft 之後餵進這裡。
        """
        front_ipsi, front_contra = front
        surround_ipsi, surround_contra = surround
        return cls(
            centre=centre,
            front_sum=front_ipsi + front_contra,
            front_diff=front_ipsi - front_contra,
            surround_sum=surround_ipsi + surround_contra,
            surround_diff=surround_ipsi - surround_contra,
        )

    def __post_init__(self) -> None:
        sizes = {
            self.centre.size,
            self.front_sum.size,
            self.front_diff.size,
            self.surround_sum.size,
            self.surround_diff.size,
        }
        if len(sizes) != 1:
            raise ValueError(f"五條濾波器長度必須相同，收到 {sizes}")


def ear_pair(
    sample_rate: int, fft_size: int, azimuth_deg: float
) -> tuple[ComplexArray, ComplexArray]:
    """某個方位角的（近耳, 遠耳）響應。

    公開出來有兩個用途：測試要能直接檢查 ITD 與 ILD（sum/diff 形式看不出
    這兩件事），以及之後拿真人資料集來比對時，比的就是這一層。
    """
    freqs = np.asarray(np.fft.rfftfreq(fft_size, d=1.0 / sample_rate), dtype=np.float64)
    return (
        _ear_response(freqs, azimuth_deg, ipsilateral=True),
        _ear_response(freqs, azimuth_deg, ipsilateral=False),
    )


def _ear_response(
    freqs: npt.NDArray[np.float64], azimuth_deg: float, ipsilateral: bool
) -> ComplexArray:
    """單一喇叭到單一耳朵的轉移函數。

    ``azimuth_deg`` 是喇叭偏離正前方的角度（取絕對值；哪一耳由
    ``ipsilateral`` 決定）。``ipsilateral`` 為真代表這是**近耳**。
    """
    theta = math.radians(min(abs(azimuth_deg), 180.0))

    # Woodworth 的繞射路程：τ = (a/c)(θ + sin θ) 是**兩耳之間**的總差值，
    # 所以這裡各分一半 —— 近耳提早、遠耳延後，相減剛好還原成 τ。
    # 寫成 ±half 而不是「近耳 0、遠耳 τ」，是為了讓正前方的兩耳完全對稱，
    # 否則整個場景會被一個共同延遲往一邊拖。
    # 公式只在 |θ| ≤ 90° 有效；環繞喇叭在 110°，繞射路徑不再變長，用邊界值延伸。
    clamped = min(theta, math.pi / 2)
    half = 0.5 * (HEAD_RADIUS_M / SOUND_SPEED_MPS) * (clamped + math.sin(clamped))
    delay = -half if ipsilateral else half

    # Brown–Duda 單極點頭部遮蔽。ω0 = c/a 是頭的特徵頻率（3.9 krad/s ≈ 620 Hz，
    # 轉移函數用的是 2ω0，所以實際轉折落在 1.2 kHz 附近）：低於它聲音繞得過去、
    # 兩耳幾乎一樣；高於它遠耳被頭擋住。
    #
    # alpha 是從**耳朵的方向**量的入射角決定的，不是從正前方量。耳朵在
    # ±90°，所以近耳的入射角是 90°−θ、遠耳是 90°+θ，
    # 代進 1 + cos(·) 就得到下面這兩行。用 cos(θ) 會因為 cos 是偶函數而
    # 讓兩耳拿到同一個值 —— 那樣就完全沒有 ILD，只剩 ITD。
    alpha = 1.0 + math.sin(theta) if ipsilateral else 1.0 - math.sin(theta)
    alpha = max(HRTF_SHADOW_MIN_GAIN, alpha)

    omega_zero = SOUND_SPEED_MPS / HEAD_RADIUS_M
    omega = 2.0 * np.pi * freqs
    shadow = (1.0 + 1j * alpha * omega / (2.0 * omega_zero)) / (
        1.0 + 1j * omega / (2.0 * omega_zero)
    )
    return np.asarray(shadow * np.exp(-1j * omega * delay), dtype=np.complex128)


def synthetic_filters(sample_rate: int, fft_size: int) -> HrtfFilters:
    """用球形頭模型合成一組 :class:`HrtfFilters`。

    ``fft_size`` 必須與 ``spatial.py`` 的 STFT 相同 —— 濾波器是直接乘在
    它的頻譜上的。
    """
    centre, _ = ear_pair(sample_rate, fft_size, 0.0)
    return HrtfFilters.from_ear_pairs(
        centre=centre,
        front=ear_pair(sample_rate, fft_size, HRTF_FRONT_AZIMUTH_DEG),
        surround=ear_pair(sample_rate, fft_size, HRTF_SURROUND_AZIMUTH_DEG),
    )


def interaural_delay_sec(azimuth_deg: float) -> float:
    """Woodworth ITD（秒）：遠耳比近耳晚多少。

    公開出來是給測試與診斷用的 —— renderer 內部不需要它，ITD 已經在
    :attr:`HrtfFilters.front_diff` 的相位裡。90° 時約 660 µs，
    這個量級是這個模型對不對的第一個檢查點。
    """
    theta = min(math.radians(abs(azimuth_deg)), math.pi / 2)
    return (HEAD_RADIUS_M / SOUND_SPEED_MPS) * (theta + math.sin(theta))
