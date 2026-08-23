"""P2 HRTF：合成頭模型與 M/S 化簡的守門測試。

這個檔案守兩件不同的東西：

1. **模型有沒有給出物理上對的量。** ITD 有閉式解、ILD 有已知的頻率趨勢，
   所以「方位角接反」「兩耳拿到同一個增益」這類錯誤是可以被機器抓到的。
   （這兩個錯誤在寫這一版時真的都發生過：ITD 一開始大了兩倍，
   而遮蔽用了 cos 這個偶函數，導致兩耳的 alpha 相同、ILD 恆為零。）

2. **M/S 的化簡與逐喇叭渲染是否等價。** ``hrtf.py`` 整個設計都建立在
   「HRTF 可以留在 M/S 域、不必多做 FFT」這條推導上。推導錯了的話效能
   結論與音場都會一起錯，所以這裡用最笨的逐喇叭參考實作去對答案。
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from aurora.core.constants import (
    HRTF_CUE_SMOOTHING_OCTAVE,
    HRTF_EQ_LIMIT_DB,
    HRTF_FRONT_AZIMUTH_DEG,
    HRTF_SURROUND_AZIMUTH_DEG,
    SPATIAL_FFT_SIZE,
)
from aurora.core.hrtf import (
    HrtfFilters,
    _smooth_octaves,
    ear_pair,
    interaural_delay_sec,
    synthetic_filters,
)

SAMPLE_RATE = 48000
FFT = SPATIAL_FFT_SIZE
BINS = FFT // 2 + 1
FREQS = np.fft.rfftfreq(FFT, 1.0 / SAMPLE_RATE)


def _bin_at(hz: float) -> int:
    return int(np.argmin(np.abs(FREQS - hz)))


# ------------------------------------------------------------------ ITD


def test_centre_source_has_no_interaural_delay() -> None:
    assert interaural_delay_sec(0.0) == 0.0


def test_itd_matches_woodworth() -> None:
    """90° 的 ITD 約 660 µs。這是這個模型對不對的第一個檢查點。"""
    assert interaural_delay_sec(90.0) == pytest.approx(656e-6, abs=10e-6)
    assert interaural_delay_sec(30.0) == pytest.approx(261e-6, abs=10e-6)


def test_itd_grows_with_azimuth_then_saturates() -> None:
    """Woodworth 只在 |θ| ≤ 90° 有效，之後用邊界值延伸。"""
    values = [interaural_delay_sec(deg) for deg in (0, 15, 30, 60, 90)]
    assert values == sorted(values)
    assert interaural_delay_sec(110.0) == pytest.approx(interaural_delay_sec(90.0))


def test_left_and_right_are_mirror_images() -> None:
    """左右對稱是 M/S 化簡的前提，不能只靠慣例守著。"""
    assert interaural_delay_sec(-30.0) == interaural_delay_sec(30.0)


# ------------------------------------------------------------------ ILD


def test_centre_source_reaches_both_ears_identically() -> None:
    """正前方沒有近耳遠耳之分。差值不是 0 的話整個場景會偏向一邊。"""
    ipsi, contra = ear_pair(SAMPLE_RATE, FFT, 0.0)
    assert np.allclose(ipsi, contra)


def test_head_shadows_the_far_ear_at_high_frequency() -> None:
    """高頻繞不過頭：遠耳必須明顯比近耳小。"""
    ipsi, contra = ear_pair(SAMPLE_RATE, FFT, 90.0)
    high = _bin_at(8000.0)
    ild_db = 20 * np.log10(abs(ipsi[high]) / abs(contra[high]))
    assert ild_db > 6.0, f"8 kHz 的 ILD 只有 {ild_db:.1f} dB，頭等於不存在"


def test_low_frequency_bends_around_the_head() -> None:
    """低頻的 ILD 應該很小 —— 那個頻段的方向線索靠 ITD，不是靠音量。"""
    ipsi, contra = ear_pair(SAMPLE_RATE, FFT, 90.0)
    low = _bin_at(150.0)
    ild_db = abs(20 * np.log10(abs(ipsi[low]) / abs(contra[low])))
    assert ild_db < 3.0, f"150 Hz 的 ILD 有 {ild_db:.1f} dB，模型把低頻也擋住了"


def test_ild_increases_with_frequency() -> None:
    ipsi, contra = ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG)
    ilds = [
        20 * np.log10(abs(ipsi[_bin_at(hz)]) / abs(contra[_bin_at(hz)]))
        for hz in (200.0, 1000.0, 4000.0, 12000.0)
    ]
    assert ilds == sorted(ilds), f"ILD 沒有隨頻率單調上升：{ilds}"


def test_far_ear_never_goes_completely_silent() -> None:
    """真實的頭會繞射。遠耳高頻掉到 0 是模型的破綻，不是物理。"""
    _, contra = ear_pair(SAMPLE_RATE, FFT, 90.0)
    assert float(np.min(np.abs(contra))) > 0.05


# ------------------------------------------------------------------ 濾波器組


def test_filters_match_the_spatial_fft() -> None:
    """濾波器是直接乘在 Spatial 的頻譜上的，長度必須一致。"""
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    assert filters.centre.size == BINS
    assert filters.front_sum.size == BINS
    assert filters.front_diff.size == BINS
    assert filters.surround_sum.size == BINS
    assert filters.surround_diff.size == BINS


def test_mismatched_filter_lengths_are_rejected() -> None:
    """長度不一致會安靜地廣播成錯的結果，寧可當場炸掉。"""
    ones = np.ones(BINS, dtype=np.complex128)
    with pytest.raises(ValueError):
        HrtfFilters(
            centre=ones,
            front_sum=ones,
            front_diff=ones,
            surround_sum=ones,
            surround_diff=np.ones(BINS - 1, dtype=np.complex128),
        )


# ------------------------------------------------------------------ 化簡等價


def _reference_ms(
    centre: np.ndarray,
    front_mid: np.ndarray,
    side: np.ndarray,
    feed_sl: np.ndarray,
    feed_sr: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """最笨的參考實作：五個喇叭各自送到兩耳，最後才轉回 M/S。

    刻意不共用 ``hrtf.py`` 的任何化簡，這樣它才有資格當答案。環繞的兩個
    餵法直接傳進來，所以這個檔案完全不需要知道 ``spatial.py`` 怎麼產生
    去相關訊號 —— 驗的是推導，不是某一組特定的隨機相位。

    **成對的喇叭每支只承擔一半。** 場景給「前方」與「環繞」各一份權重，
    而那一份要由兩支喇叭分攤；不分攤的話成對的路徑會比中央多 6 dB
    （實機聽起來就是人聲被推遠、左右樂器逼近）。這裡照著同一個慣例餵，
    參考實作才問得出正確的答案。
    """
    centre_ear, _ = ear_pair(SAMPLE_RATE, FFT, 0.0)
    front_ipsi, front_contra = ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG)
    surr_ipsi, surr_contra = ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG)

    share = 0.5
    feed_fl, feed_fr = (front_mid + side) * share, (front_mid - side) * share
    feed_sl, feed_sr = feed_sl * share, feed_sr * share

    left = (
        centre * centre_ear
        + feed_fl * front_ipsi
        + feed_fr * front_contra
        + feed_sl * surr_ipsi
        + feed_sr * surr_contra
    )
    right = (
        centre * centre_ear
        + feed_fr * front_ipsi
        + feed_fl * front_contra
        + feed_sr * surr_ipsi
        + feed_sl * surr_contra
    )
    return (left + right) * 0.5, (left - right) * 0.5


def test_ms_shortcut_equals_per_speaker_rendering() -> None:
    """M/S 化簡必須與逐喇叭渲染逐位元等價（浮點誤差內）。

    ``hrtf.py`` 的模組 docstring 用這條推導論證「HRTF 不必多做一次 FFT」。
    推導一旦錯了，效能結論與音場會一起錯，而且兩者都不會自己叫。
    """
    rng = np.random.default_rng(20260823)

    def spectrum() -> np.ndarray:
        return (rng.standard_normal(BINS) + 1j * rng.standard_normal(BINS)).astype(
            np.complex128
        )

    centre, front_mid, side = spectrum(), spectrum(), spectrum()
    # 環繞餵的是兩條互不相關的訊號，不是 ±u —— 推導必須對任意的一對成立。
    feed_sl, feed_sr = spectrum(), spectrum()

    # 刻意用**未補償**的濾波器組。佈局補償是每格一個共同的實數
    #（由 test_layout_correction_is_a_common_real_scalar 守著），所以它與這裡要驗的
    # M/S 代數可交換 —— 把它算進來只會讓失敗訊息更難讀，證不了更多東西。
    filters = HrtfFilters.from_ear_pairs(
        centre=ear_pair(SAMPLE_RATE, FFT, 0.0)[0],
        front=ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG),
        surround=ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG),
    )
    surround_sum = (feed_sl + feed_sr) * 0.5
    surround_diff = (feed_sl - feed_sr) * 0.5
    fast_mid = (
        centre * filters.centre
        + front_mid * filters.front_sum
        + surround_sum * filters.surround_sum
    )
    fast_side = side * filters.front_diff + surround_diff * filters.surround_diff

    ref_mid, ref_side = _reference_ms(centre, front_mid, side, feed_sl, feed_sr)

    assert np.allclose(fast_mid, ref_mid)
    assert np.allclose(fast_side, ref_side)


def test_shortcut_stays_a_handful_of_multiplies_per_bin() -> None:
    """化簡的重點是濾波器只有少少幾條。多一條就要回頭重測預算。

    這條看起來像在數欄位，但它守的是 §9.4 的預算結論：HRTF 之所以塞得下，
    正是因為它只是每格幾次複數乘法，沒有第二組 STFT。它已經實際生效過一次
    —— 環繞從 ±u 改成兩條去相關訊號時多了一條 surround_sum，這條測試因此
    紅燈，預算也就跟著重測了（§9.10）。
    """
    assert len(dataclasses.fields(HrtfFilters)) == 5


# ------------------------------------------------------------------ 佈局音色補償


def _paths(filters: HrtfFilters) -> list[np.ndarray]:
    """五條喇叭到耳朵的路徑。等化看的是它們的共同成分。"""
    return [
        filters.centre,
        filters.front_sum + filters.front_diff,
        filters.front_sum - filters.front_diff,
        filters.surround_sum + filters.surround_diff,
        filters.surround_sum - filters.surround_diff,
    ]


def test_layout_correction_is_a_common_real_scalar() -> None:
    """等化必須是「每格一個共同的實數」。

    這條看似瑣碎，但它是另外兩件事的地基：**共同** ⇒ 與 M/S 代數可交換
    （所以化簡等價性可以在未等化的組上驗）；**實數** ⇒ 不動相位 ⇒ 不動 ITD。
    哪天有人把等化寫成每條路徑各自處理、或不小心動到相位，方向就會歪掉，
    而那用聽的只會覺得「怪」，很難定位到是這一步。
    """
    raw = HrtfFilters.from_ear_pairs(
        centre=ear_pair(SAMPLE_RATE, FFT, 0.0)[0],
        front=ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG),
        surround=ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG),
    )
    equalised = raw.layout_equalised()

    before, after = _paths(raw), _paths(equalised)
    # 只看兩邊都夠大的格，否則會拿 0/0 去比。
    solid = np.all([np.abs(item) > 1e-6 for item in before], axis=0)
    assert solid.sum() > FFT // 8, "可比較的格太少，這個測試會失去意義"

    ratios = [(new[solid] / old[solid]) for old, new in zip(before, after, strict=True)]
    for other in ratios[1:]:
        assert np.allclose(other, ratios[0]), "不同路徑拿到不同的等化 ⇒ 會擾動 M/S 代數"
    assert np.allclose(np.imag(ratios[0]), 0.0, atol=1e-9), "等化動到相位 ⇒ 會改掉 ITD"


def test_layout_response_is_flattened() -> None:
    """這個佈局的平均響應要被壓平 —— 那一段不帶任何方向資訊。

    **補的是佈局不是資料集。** SADIE II 已經做過全球面的擴散場等化；
    但 AURORA 只用到其中五個方向，那個子集的平均仍可能偏斜。未補償時實測
    H13 相對 500 Hz 是 63 Hz −6.6 dB、8 kHz −4.0 dB，聽起來就是
    「悶、沒有通透感、低頻不見」。
    """
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    common = np.sqrt(np.mean([np.abs(item) ** 2 for item in _paths(filters)], axis=0))

    band = (FREQS >= 100.0) & (FREQS <= 12000.0)
    spread_db = 20 * np.log10(common[band].max() / common[band].min())
    assert spread_db < 6.0, f"共同響應仍有 {spread_db:.1f} dB 的起伏"


def test_layout_correction_preserves_interaural_level_differences() -> None:
    """ILD 是方向線索，等化不得動到它。

    等化是共同純量，所以近耳／遠耳的**比值**必須逐位元不變。
    """
    raw = HrtfFilters.from_ear_pairs(
        centre=ear_pair(SAMPLE_RATE, FFT, 0.0)[0],
        front=ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG),
        surround=ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG),
    )
    equalised = raw.layout_equalised()

    def ild(filters: HrtfFilters) -> np.ndarray:
        near = filters.front_sum + filters.front_diff
        far = filters.front_sum - filters.front_diff
        keep = np.abs(far) > 1e-6
        return np.abs(near[keep]) / np.abs(far[keep])

    assert np.allclose(ild(raw), ild(equalised))


def test_layout_correction_never_boosts_beyond_the_limit() -> None:
    """量測在極低頻與極高頻不可靠，沒有上限的話會把噪訊放大成隆隆聲或嘶聲。"""
    raw = HrtfFilters.from_ear_pairs(
        centre=ear_pair(SAMPLE_RATE, FFT, 0.0)[0],
        front=ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG),
        surround=ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG),
    )
    equalised = raw.layout_equalised()
    keep = np.abs(raw.centre) > 1e-6
    gain_db = 20 * np.log10(np.abs(equalised.centre[keep]) / np.abs(raw.centre[keep]))
    assert gain_db.max() <= HRTF_EQ_LIMIT_DB + 1e-6


# ------------------------------------------------------------------ 頻譜線索強度


def _ripple_db(response: np.ndarray) -> float:
    """響應相對自身輪廓的起伏（標準差，dB）—— 這就是「頻譜線索」的量。"""
    magnitude = np.abs(response)
    outline = _smooth_octaves(magnitude, HRTF_CUE_SMOOTHING_OCTAVE)
    band = (FREQS > 200.0) & (FREQS < 12000.0)
    deviation = 20 * np.log10(np.maximum(magnitude, 1e-12) / np.maximum(outline, 1e-12))
    return float(np.std(deviation[band]))


def test_full_strength_changes_nothing() -> None:
    """預設不柔化 —— 要不要拿定位換音色是使用者的選擇。"""
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    assert filters.with_cue_strength(1.0) is filters


def test_zero_strength_leaves_exactly_the_outline() -> None:
    """α=0 時每條耳朵響應的 magnitude 必須**恰好**等於自己的輪廓。

    兩端精確是這個內插的地基：α=1 是原訊號、α=0 是輪廓，中間是對數域的
    線性內插。端點不精確的話，滑桿的兩端就不是它宣稱的東西。
    """
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    softened = filters.with_cue_strength(0.0)
    band = (FREQS > 200.0) & (FREQS < 12000.0)
    for original, result in zip(filters.ear_responses(), softened.ear_responses(), strict=True):
        outline = _smooth_octaves(np.abs(original), HRTF_CUE_SMOOTHING_OCTAVE)
        assert np.allclose(np.abs(result)[band], outline[band])


def test_softening_never_touches_phase() -> None:
    """相位不動 ⇒ ITD 不動。這是「保留 ITD」這個宣稱的唯一嚴格證明。

    不要用起音位置去量 ITD 來驗這件事：脈衝形狀本來就會隨 magnitude 改變，
    量出來的起音會飄，那是量測假象不是 ITD 變了（開發時真的被騙過一次）。
    """
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    for strength in (0.75, 0.5, 0.0):
        softened = filters.with_cue_strength(strength)
        for original, result in zip(
            filters.ear_responses(), softened.ear_responses(), strict=True
        ):
            assert np.allclose(np.angle(original), np.angle(result))


def test_critical_band_ild_is_preserved_exactly() -> None:
    """臨界頻帶（輪廓）的 ILD 必須完全不變 —— 那是感知上有意義的 ILD 定義。

    被柔化的只有細結構。輪廓帶著寬頻的左右音量差，動它就等於動方向。
    """
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    softened = filters.with_cue_strength(0.0)
    band = (FREQS > 200.0) & (FREQS < 12000.0)

    def outline_ild(near: np.ndarray, far: np.ndarray) -> np.ndarray:
        smooth_near = _smooth_octaves(np.abs(near), HRTF_CUE_SMOOTHING_OCTAVE)
        smooth_far = _smooth_octaves(np.abs(far), HRTF_CUE_SMOOTHING_OCTAVE)
        return 20 * np.log10(smooth_near[band] / np.maximum(smooth_far[band], 1e-12))

    original = outline_ild(filters.front_sum + filters.front_diff,
                           filters.front_sum - filters.front_diff)
    # α=0 之後 magnitude 就是輪廓本身，所以直接比它與原始輪廓的比值。
    result = 20 * np.log10(
        np.abs(softened.front_sum + softened.front_diff)[band]
        / np.maximum(np.abs(softened.front_sum - softened.front_diff)[band], 1e-12)
    )
    assert np.allclose(original, result, atol=1e-9)


def _with_notch(response: np.ndarray, hz: float, depth_db: float) -> np.ndarray:
    """在響應上挖一個窄凹陷，模擬耳廓造成的頻譜線索。相位不動。"""
    width = hz * 0.12
    shape = np.exp(-(((FREQS - hz) / width) ** 2))
    return response * (1.0 - (1.0 - 10 ** (depth_db / 20.0)) * shape)


def test_synthetic_model_has_almost_nothing_to_soften() -> None:
    """球形頭沒有耳廓，正前方的響應本來就是平滑的。

    所以柔化它幾乎不會改變什麼 —— 這不是滑桿沒接上，是合成模型的先天限制
    （也正是為什麼它做不出可靠的前後區分）。開發時曾經拿它當測試素材，
    結果測到的是這件事而不是柔化本身。
    """
    filters = synthetic_filters(SAMPLE_RATE, FFT)
    assert _ripple_db(filters.centre) < 0.05


def test_cues_soften_monotonically() -> None:
    """滑桿要有作用，而且方向要單調 —— 否則使用者調不出想要的位置。

    素材是注入了已知凹陷的響應（真人 HRTF 的耳廓線索就長這樣）。不能用
    合成模型驗，它根本沒有可柔化的細結構。
    """
    ipsi, contra = ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG)
    filters = HrtfFilters.from_ear_pairs(
        centre=_with_notch(ear_pair(SAMPLE_RATE, FFT, 0.0)[0], 8000.0, -12.0),
        front=(_with_notch(ipsi, 7000.0, -9.0), contra),
        surround=ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG),
    )

    ripples = [
        _ripple_db(filters.with_cue_strength(a).centre) for a in (1.0, 0.75, 0.5, 0.25, 0.0)
    ]
    assert ripples == sorted(ripples, reverse=True), f"起伏沒有單調下降：{ripples}"
    assert ripples[-1] < ripples[0] * 0.5, "柔化到底卻幾乎沒變，滑桿等於沒接上"
