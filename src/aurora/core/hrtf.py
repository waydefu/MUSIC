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

**一對喇叭的濾波器要各承擔一半。** ``H_sum(θ) = H_i + H_c`` 在低頻趨近
``2·H_0``（兩耳都聽得到、而且幾乎一樣），但場景那一邊給的權重是 1 ——
``centre + front_mid == mid`` 是恆等式，立體聲 renderer 的兩條路權重都是 1。
不補這個 ``0.5``，一對喇叭的路徑就整整多 6 dB，而中央還要再被距離機制壓
5 dB：實聽的結果是「人聲被拉很遠、左右樂器太近，像廉價耳機」。這是實機
回報出來的，量出來低頻確實差 +5.7 dB（實測 H13）與 +6.0 dB（合成模型）。

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
from pathlib import Path

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    HEAD_RADIUS_M,
    HRTF_CUE_SMOOTHING_OCTAVE,
    HRTF_EQ_LIMIT_DB,
    HRTF_EQ_SMOOTHING_OCTAVE,
    HRTF_FRONT_AZIMUTH_DEG,
    HRTF_MAX_TAP_RATIO,
    HRTF_SHADOW_MIN_GAIN,
    HRTF_SURROUND_AZIMUTH_DEG,
    SOUND_SPEED_MPS,
)
from aurora.core.paths import hrtf_dir, hrtf_file

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
        # 每支喇叭承擔它那一對的一半 —— 見模組 docstring 的「一對喇叭的
        # 濾波器要各承擔一半」。少了它，成對的路徑會比中央多 6 dB。
        half = _PAIR_SHARE
        return cls(
            centre=centre,
            front_sum=(front_ipsi + front_contra) * half,
            front_diff=(front_ipsi - front_contra) * half,
            surround_sum=(surround_ipsi + surround_contra) * half,
            surround_diff=(surround_ipsi - surround_contra) * half,
        )

    def layout_equalised(self) -> HrtfFilters:
        """除掉**這個虛擬喇叭佈局**帶進來的共同音色偏差。

        ## 這不是資料集的擴散場等化

        好的 HRTF 資料集**已經做過**擴散場等化了。SADIE II 的做法是每耳取
        全球面量測的能量平均、依**立體角加權**（避免密集取樣的方向被過度
        代表）、再用 Kirkeby–Nelson 正則化求反濾波器，並在加窗前後各做一次。
        AURORA **不重做**那件事，重做只會把已經平的東西再乘一次。

        ## 那要補的是什麼

        AURORA 只用到球面上的**五個方向**（中央、前方 ±30°、環繞 ±110°）。
        資料集的全球面平均是平的，不代表這五個方向的平均也是平的 ——
        實測 H13 這五條路徑的平均相對 500 Hz 是：63 Hz −6.6 dB、
        125 Hz −6.4 dB、8 kHz −4.0 dB。那是**佈局本身**的音色偏差，
        不帶任何方向資訊，卻整個乘在訊號上。實聽的結果就是
        「變悶、沒有通透感、低頻不見」。

        同一個群組（York）在 Ambisonic 雙耳渲染上也做過同樣的事：底層 HRTF
        已經處理過，但經過解碼與虛擬喇叭組合之後仍會產生新的頻響偏差，
        於是量**整個 renderer** 的響應再補回去。這裡是同一個道理。

        ## 為什麼不會損失方向資訊

        方向資訊全部藏在各方向之間的**差異**裡。這個修正是「每格一個共同的
        實數」：共同 ⇒ 任兩個方向的比值不變（ILD 與相對頻譜形狀都保住），
        實數 ⇒ 相位不動（ITD 不變）。兩者都有測試守著。
        """
        paths = np.stack(
            [
                self.centre,
                self.front_sum + self.front_diff,
                self.front_sum - self.front_diff,
                self.surround_sum + self.surround_diff,
                self.surround_sum - self.surround_diff,
            ]
        )
        common = _smooth_octaves(np.sqrt(np.mean(np.abs(paths) ** 2, axis=0)))
        reference = float(np.median(common))
        if reference <= _EPS:
            return self

        limit = 10.0 ** (HRTF_EQ_LIMIT_DB / 20.0)
        correction = np.clip(reference / np.maximum(common, _EPS), 1.0 / limit, limit)
        # 只動 magnitude。相位帶著 ITD，碰它等於改掉方向。
        return HrtfFilters(
            centre=self.centre * correction,
            front_sum=self.front_sum * correction,
            front_diff=self.front_diff * correction,
            surround_sum=self.surround_sum * correction,
            surround_diff=self.surround_diff * correction,
        )

    def ear_responses(self) -> tuple[ComplexArray, ...]:
        """拆回五條「喇叭到耳朵」的原始響應。

        ``from_ear_pairs`` 的反運算：``ipsi = sum + diff``、``contra = sum − diff``
        （每支各半的 0.5 在這裡剛好抵消）。頻譜線索住在**耳朵的響應**上，
        不在 sum/diff 上，所以要動線索就得先拆回來。
        """
        return (
            self.centre,
            self.front_sum + self.front_diff,
            self.front_sum - self.front_diff,
            self.surround_sum + self.surround_diff,
            self.surround_sum - self.surround_diff,
        )

    def with_cue_strength(self, strength: float) -> HrtfFilters:
        """調整頻譜線索的強度。1.0 ＝ 原樣，0.0 ＝ 只留粗略輪廓。

        ## 這在交換什麼

        HRTF 的窄峰谷（主要來自耳廓）是**前後與上下**的線索，但它們是**那個
        人**的耳朵形狀。非個人化 HRTF 的凹陷落在錯的頻率時，大腦不會把它讀
        成方向，只會聽成「人聲的高頻怎麼不見了」—— 實測 H13 在正前方 8 kHz
        比平均低 7.2 dB，回報的聽感就是「悶」。

        Merimaa（Sennheiser）的 AES 研究做過同一件事：降低 HRTF 的頻譜起伏、
        同時完整保留 ITD 與 ILD，在非個人化 HRTF 上音色染色顯著減少而定位
        沒有統計顯著惡化。所以這是一個**準確度 ↔ 自然音色**的交換，
        不是高頻等化。

        ## 怎麼做到「保留 ITD 與 ILD」

        對每條耳朵響應，把它的 magnitude 往**自己的**一八度平滑版本內插::

            |H_soft| = |H_smooth| · (|H| / |H_smooth|) ** strength

        粗略輪廓原封不動 ⇒ 寬頻的 ILD 保住；只有窄的峰谷被壓平。
        相位完全不碰 ⇒ ITD 完全不變。
        """
        alpha = float(np.clip(strength, 0.0, 1.0))
        if alpha >= 1.0:
            return self

        softened: list[ComplexArray] = []
        for response in self.ear_responses():
            magnitude = np.abs(response)
            outline = _smooth_octaves(magnitude, HRTF_CUE_SMOOTHING_OCTAVE)
            detail = np.divide(
                magnitude, outline, out=np.ones_like(magnitude), where=outline > _EPS
            )
            # α=0 時這個式子恰好等於輪廓本身，α=1 時恰好等於原訊號 ——
            # 兩端都是精確的，中間是對數域的線性內插。
            target = outline * detail**alpha
            scale = np.divide(
                target,
                np.maximum(magnitude, _EPS),
                out=np.ones_like(magnitude),
                where=magnitude > _EPS,
            )
            softened.append(response * scale)

        centre, front_ipsi, front_contra, surround_ipsi, surround_contra = softened
        return HrtfFilters.from_ear_pairs(
            centre=centre,
            front=(front_ipsi, front_contra),
            surround=(surround_ipsi, surround_contra),
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


def _smooth_octaves(
    magnitude: npt.NDArray[np.float64], octaves: float = HRTF_EQ_SMOOTHING_OCTAVE
) -> npt.NDArray[np.float64]:
    """對數頻率上的分數八度平滑（能量平均）。

    用累積和一次算完，避免 1025 格各跑一次迴圈。第 0 格（DC）沒有八度可言，
    照原值留著 —— 它只影響直流偏移。
    """
    power = np.square(magnitude, dtype=np.float64)
    cumulative = np.concatenate(([0.0], np.cumsum(power)))
    index = np.arange(magnitude.size, dtype=np.float64)
    ratio = 2.0 ** (octaves / 2.0)
    low = np.maximum(0, np.floor(index / ratio)).astype(np.int64)
    high = np.minimum(magnitude.size, np.ceil(index * ratio).astype(np.int64) + 1)
    width = np.maximum(high - low, 1)
    smoothed = np.sqrt((cumulative[high] - cumulative[low]) / width)
    smoothed[0] = magnitude[0]
    return np.asarray(smoothed, dtype=np.float64)


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
    ).layout_equalised()


def interaural_delay_sec(azimuth_deg: float) -> float:
    """Woodworth ITD（秒）：遠耳比近耳晚多少。

    公開出來是給測試與診斷用的 —— renderer 內部不需要它，ITD 已經在
    :attr:`HrtfFilters.front_diff` 的相位裡。90° 時約 660 µs，
    這個量級是這個模型對不對的第一個檢查點。
    """
    theta = min(math.radians(abs(azimuth_deg)), math.pi / 2)
    return (HEAD_RADIUS_M / SOUND_SPEED_MPS) * (theta + math.sin(theta))


# ---------------------------------------------------------------- 實測資料

#: 避免除以零。
_EPS = 1e-12
#: 一對喇叭裡每一支承擔的份額。場景給一對的權重是 1，而 H_sum 在低頻
#: 趨近 2·H_0，所以要各半才回到場景的能量分配。
_PAIR_SHARE = 0.5
#: 量測格點與目標方位角最多可以差幾度。資料集的格點通常是 5° 或更密，
#: 差超過這個值就代表拿到的不是那個方向的響應，寧可退回合成模型。
_AZIMUTH_TOLERANCE_DEG = 7.5
#: ``.npz`` 裡必須有的欄位。
_REQUIRED_KEYS = ("sample_rate", "azimuths", "ipsi", "contra")


def _resample(response: npt.NDArray[np.float64], source_rate: int, target_rate: int) -> (
    npt.NDArray[np.float64]
):
    """把脈衝響應換到另一個取樣率。

    用傅立葉重取樣（``irfft(rfft(x), n=M)``），也就是理想的 sinc 內插。
    線性內插在 10 kHz 附近就開始明顯滾降，而那正好是 HRTF 的方向線索所在。
    HRIR 兩端本來就衰減到接近 0，所以這個方法隱含的週期性假設不會造成問題。
    """
    if source_rate == target_rate:
        return response
    length = max(1, round(response.size * target_rate / source_rate))
    return np.asarray(np.fft.irfft(np.fft.rfft(response), n=length), dtype=np.float64)


#: 內建合成模型的 profile 名稱。使用者要能明確選它 —— A/B 比較「真人資料
#: 到底有沒有比較好」是這個功能存在的理由之一。
SYNTHETIC_PROFILE = "synthetic"


def available_profiles() -> tuple[str, ...]:
    """使用者已匯入的 profile 名稱，依字母排序。

    舊版的單檔 ``hrtf.npz`` 會以 ``imported`` 的名字出現，這樣已經匯入過的
    人升級之後不會突然找不到自己的資料。
    """
    names: set[str] = set()
    try:
        directory = hrtf_dir()
        if directory.is_dir():
            names.update(item.stem for item in directory.glob("*.npz") if item.is_file())
    except OSError:
        pass
    try:
        if hrtf_file().is_file():
            names.add("imported")
    except OSError:
        pass
    names.discard(SYNTHETIC_PROFILE)
    return tuple(sorted(names))


def profile_path(name: str) -> Path | None:
    """profile 名稱對應的檔案。找不到回傳 ``None``。"""
    if not name or name == SYNTHETIC_PROFILE:
        return None
    try:
        candidate = hrtf_dir() / f"{name}.npz"
        if candidate.is_file():
            return candidate
        legacy = hrtf_file()
        if name == "imported" and legacy.is_file():
            return legacy
    except OSError:
        return None
    return None


def resolve_profile(name: str) -> Path | None:
    """把設定裡的 profile 名稱解析成檔案路徑。

    空字串是**自動**：有匯入過就用第一組，沒有就用合成模型。這讓已經匯入
    過的使用者升級後行為不變，而不是突然掉回合成模型。
    """
    if name == SYNTHETIC_PROFILE:
        return None
    if name:
        return profile_path(name)
    profiles = available_profiles()
    return profile_path(profiles[0]) if profiles else None


def load_filters(sample_rate: int, fft_size: int, path: Path | None = None) -> HrtfFilters | None:
    """載入使用者自備的實測 HRTF。**任何問題都回傳 ``None``，不拋例外。**

    退回 ``None`` 的意思是「用合成模型」，那是一個完全可用的狀態，不是錯誤。
    這與設定檔／快取的處理原則相同（AGENTS.md 不變量 6）：壞掉的檔案只能
    讓功能降級，不能讓播放器開不起來。

    檔案由 ``tools/import_hrtf.py`` 產生，內容是**近耳／遠耳**的 HRIR
    而不是左右耳 —— 左右哪一邊是近耳取決於喇叭在哪一側，轉換在匯入時
    做掉一次，renderer 就不必知道資料集的座標慣例。
    """
    target = path or hrtf_file()
    try:
        if not target.is_file():
            return None
        with np.load(target) as data:
            if any(key not in data for key in _REQUIRED_KEYS):
                return None
            source_rate = int(data["sample_rate"])
            azimuths = np.asarray(data["azimuths"], dtype=np.float64)
            ipsi = np.atleast_2d(np.asarray(data["ipsi"], dtype=np.float64))
            contra = np.atleast_2d(np.asarray(data["contra"], dtype=np.float64))
    except Exception:
        # 檔案壞掉、不是 npz、numpy 版本不合 —— 一律當成沒有這個檔案。
        return None

    if source_rate <= 0 or ipsi.shape != contra.shape or ipsi.shape[0] != azimuths.size:
        return None
    if ipsi.shape[1] > fft_size * HRTF_MAX_TAP_RATIO:
        # 太長的濾波器會在頻域相乘時繞回框首（見 HRTF_MAX_TAP_RATIO）。
        return None

    def pair_at(azimuth: float) -> tuple[ComplexArray, ComplexArray] | None:
        # 資料集的量測格點不一定剛好落在 30°／110°，取最近的一個。
        # 差太多就不要硬用 —— 那已經不是這個方位角的響應了。
        index = int(np.argmin(np.abs(azimuths - azimuth)))
        if abs(float(azimuths[index]) - azimuth) > _AZIMUTH_TOLERANCE_DEG:
            return None
        near = _resample(ipsi[index], source_rate, sample_rate)
        far = _resample(contra[index], source_rate, sample_rate)
        if near.size > fft_size or far.size > fft_size:
            return None
        return (
            np.asarray(np.fft.rfft(near, n=fft_size), dtype=np.complex128),
            np.asarray(np.fft.rfft(far, n=fft_size), dtype=np.complex128),
        )

    centre = pair_at(0.0)
    front = pair_at(HRTF_FRONT_AZIMUTH_DEG)
    surround = pair_at(HRTF_SURROUND_AZIMUTH_DEG)
    if centre is None or front is None or surround is None:
        return None

    try:
        filters = HrtfFilters.from_ear_pairs(centre=centre[0], front=front, surround=surround)
    except ValueError:
        return None
    return filters.layout_equalised()
