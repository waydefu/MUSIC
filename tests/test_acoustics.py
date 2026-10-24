"""量測指標須有解析或獨立參考，不能只因 DSP 輸出符合門檻就說指標正確。"""

import numpy as np
import pytest

from aurora.core.acoustics import (
    fft_true_peak,
    iacc_e3,
    interaural_cross_correlation,
    octave_band_filter,
    windowed_iacc,
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


def test_windowed_iacc_separates_early_and_late_energy() -> None:
    rate = 48000
    direct = 1024
    frames = direct + int(rate * 0.4)
    left = np.zeros(frames)
    right = np.zeros(frames)
    rng = np.random.default_rng(2026)

    early = slice(direct, direct + int(rate * 0.08))
    shared = rng.standard_normal(early.stop - early.start)
    left[early] = shared
    right[early] = shared

    late = slice(early.stop, direct + int(rate * 0.30))
    left[late] = rng.standard_normal(late.stop - late.start)
    right[late] = rng.standard_normal(late.stop - late.start)

    assert windowed_iacc(
        left,
        right,
        rate,
        start_ms=0.0,
        end_ms=80.0,
        direct_index=direct,
    ) == pytest.approx(1.0)
    assert windowed_iacc(
        left,
        right,
        rate,
        start_ms=80.0,
        end_ms=300.0,
        direct_index=direct,
    ) < 0.08


def test_iacc_e3_is_one_for_identical_binaural_ir() -> None:
    rate = 48000
    rng = np.random.default_rng(3382)
    direct = 2048
    signal = np.zeros(rate // 2)
    signal[direct : direct + int(rate * 0.08)] = rng.standard_normal(int(rate * 0.08))

    result = iacc_e3(signal, signal, rate, direct_index=direct)

    assert set(result) == {"500_hz", "1000_hz", "2000_hz", "mean"}
    assert result["500_hz"] == pytest.approx(1.0)
    assert result["1000_hz"] == pytest.approx(1.0)
    assert result["2000_hz"] == pytest.approx(1.0)
    assert result["mean"] == pytest.approx(1.0)


def test_octave_filter_selects_its_declared_band() -> None:
    rate = 48000
    time = np.arange(rate, dtype=np.float64) / rate
    in_band = np.sin(2 * np.pi * 1000.0 * time)
    out_band = np.sin(2 * np.pi * 8000.0 * time)

    passed = octave_band_filter(in_band, rate, 1000.0)
    rejected = octave_band_filter(out_band, rate, 1000.0)
    margin = 2048
    passed_rms = float(np.sqrt(np.mean(passed[margin:-margin] ** 2)))
    rejected_rms = float(np.sqrt(np.mean(rejected[margin:-margin] ** 2)))

    assert passed_rms > 0.6
    assert rejected_rms < passed_rms * 0.01


def test_windowed_iacc_requires_explicit_valid_late_end() -> None:
    signal = np.ones(4800)
    with pytest.raises(ValueError):
        windowed_iacc(signal, signal, 48000, start_ms=80.0, end_ms=80.0)


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
