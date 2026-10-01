"""量測指標須有解析或獨立參考，不能只因 DSP 輸出符合門檻就說指標正確。"""

import numpy as np
import pytest

from aurora.core.acoustics import (
    fft_true_peak,
    interaural_cross_correlation,
    zero_lag_correlation,
)


def test_iacc_finds_itd_that_zero_lag_misses() -> None:
    rng = np.random.default_rng(992)
    left = np.pad(rng.standard_normal(8192), (64, 64))
    right = np.roll(left, 32)  # 667 µs @48k，在搜尋範圍內。
    assert abs(zero_lag_correlation(left, right)) < 0.05
    assert interaural_cross_correlation(left, right, 48000) == pytest.approx(1.0)


def test_iacc_does_not_search_beyond_one_ms() -> None:
    rng = np.random.default_rng(992)
    left = rng.standard_normal(16384)
    right = np.roll(left, 60)
    assert interaural_cross_correlation(left, right, 48000) < 0.05


def test_iacc_does_not_replace_signed_anti_phase_check() -> None:
    left = np.arange(1024) % 7 - 3
    assert zero_lag_correlation(left, -left) == pytest.approx(-1.0)
    assert interaural_cross_correlation(left, -left, 48000) == pytest.approx(1.0)


@pytest.mark.parametrize("amplitude", [1e-200, 1.0, 1e200])
def test_correlation_metrics_are_scale_independent(amplitude: float) -> None:
    left = np.sin(np.arange(1024)) * amplitude
    assert zero_lag_correlation(left, left) == pytest.approx(1.0)
    assert interaural_cross_correlation(left, left, 48000) == pytest.approx(1.0)


def test_silent_metrics_are_zero() -> None:
    silence = np.zeros(1024)
    assert zero_lag_correlation(silence, silence) == 0.0
    assert interaural_cross_correlation(silence, silence, 48000) == 0.0


@pytest.mark.parametrize("frames", [1023, 1024])
def test_fft_interpolation_preserves_original_samples_and_dc(frames: int) -> None:
    dc = np.full((frames, 2), 0.3)
    assert fft_true_peak(dc) == pytest.approx(0.3)


def test_fft_interpolation_splits_nyquist_bin() -> None:
    nyquist = ((-1.0) ** np.arange(1024))[:, None]
    assert fft_true_peak(nyquist) == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_metrics_reject_nonfinite_input(bad: float) -> None:
    with pytest.raises(ValueError):
        interaural_cross_correlation([0.0, bad], [0.0, 1.0], 48000)
    with pytest.raises(ValueError):
        fft_true_peak([[bad]])
