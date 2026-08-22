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
    HRTF_FRONT_AZIMUTH_DEG,
    HRTF_SURROUND_AZIMUTH_DEG,
    SPATIAL_FFT_SIZE,
)
from aurora.core.hrtf import HrtfFilters, ear_pair, interaural_delay_sec, synthetic_filters

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
    assert filters.surround_diff.size == BINS


def test_mismatched_filter_lengths_are_rejected() -> None:
    """長度不一致會安靜地廣播成錯的結果，寧可當場炸掉。"""
    ones = np.ones(BINS, dtype=np.complex128)
    with pytest.raises(ValueError):
        HrtfFilters(
            centre=ones,
            front_sum=ones,
            front_diff=ones,
            surround_diff=np.ones(BINS - 1, dtype=np.complex128),
        )


# ------------------------------------------------------------------ 化簡等價


def _reference_ms(
    centre: np.ndarray, front_mid: np.ndarray, side: np.ndarray, surround: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """最笨的參考實作：五個喇叭各自送到兩耳，最後才轉回 M/S。

    刻意不共用 ``hrtf.py`` 的任何化簡，這樣它才有資格當答案。
    """
    centre_ear, _ = ear_pair(SAMPLE_RATE, FFT, 0.0)
    front_ipsi, front_contra = ear_pair(SAMPLE_RATE, FFT, HRTF_FRONT_AZIMUTH_DEG)
    surr_ipsi, surr_contra = ear_pair(SAMPLE_RATE, FFT, HRTF_SURROUND_AZIMUTH_DEG)

    feed_fl, feed_fr = front_mid + side, front_mid - side
    feed_sl, feed_sr = surround, -surround

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

    centre, front_mid, side, surround = spectrum(), spectrum(), spectrum(), spectrum()

    filters = synthetic_filters(SAMPLE_RATE, FFT)
    fast_mid = centre * filters.centre + front_mid * filters.front_sum
    fast_side = side * filters.front_diff + surround * filters.surround_diff

    ref_mid, ref_side = _reference_ms(centre, front_mid, side, surround)

    assert np.allclose(fast_mid, ref_mid)
    assert np.allclose(fast_side, ref_side)


def test_shortcut_costs_four_multiplies_per_bin() -> None:
    """化簡的重點是「只有四條濾波器」。多一條就代表推導被改壞了。

    這條看起來像在數欄位，但它守的是 §9.4 的預算結論：HRTF 之所以塞得下，
    正是因為它只是每格四次複數乘法，沒有第二組 STFT。
    """
    assert len(dataclasses.fields(HrtfFilters)) == 4
