from __future__ import annotations

import pytest
from tools import calibrate_spatial_estimator as calibration


def test_model_target_separates_source_fraction_from_wiener_output() -> None:
    target = calibration.model_target(0.5, 1.0)

    assert target.direct_fraction == pytest.approx(0.5)
    assert target.wiener_extracted_fraction == pytest.approx(1.0 / 3.0)
    assert target.wiener_extracted_fraction < target.direct_fraction


def test_model_target_accounts_for_pan_gain_in_total_direct_power() -> None:
    target = calibration.model_target(0.5, 0.5)

    # P = f(1+g²)/2 = 0.3125, 2A = 0.5.
    assert target.direct_power == pytest.approx(0.3125)
    assert target.total_power == pytest.approx(0.8125)
    assert target.direct_fraction == pytest.approx(0.3125 / 0.8125)


def test_ewma_null_bias_reference_matches_complex_wishart_model() -> None:
    # alpha=.85 -> n_eff=(1+.85)/(1-.85)=12.333...
    # For a 2x2 complex Wishart null covariance the expected normalized
    # eigenvalue spread is about 0.318, even though the true directionality is 0.
    assert calibration.ewma_effective_samples(0.85) == pytest.approx(12.3333333333)
    assert calibration.independent_complex_wishart_null_bias(0.85) == pytest.approx(
        0.318064, abs=1e-5
    )


def test_pure_direct_calibration_is_exact() -> None:
    result = calibration.calibrate_stationary(
        1.0,
        1.0,
        0.85,
        seeds=(17,),
        frames=24,
        warmup=4,
    )

    assert result.target_direct_fraction == pytest.approx(1.0)
    assert result.target_wiener_extracted_fraction == pytest.approx(1.0)
    assert result.measured_covariance_direct_fraction == pytest.approx(1.0, abs=1e-12)
    assert result.measured_extracted_primary_fraction == pytest.approx(1.0, abs=1e-12)


def test_pure_ambient_exposes_finite_window_directionality_bias() -> None:
    result = calibration.calibrate_stationary(
        0.0,
        1.0,
        0.85,
        seeds=(19,),
        frames=96,
        warmup=32,
    )

    assert result.target_direct_fraction == 0.0
    assert result.target_wiener_extracted_fraction == 0.0
    # The exact value depends on the random realization. The important invariant
    # is that a short EWMA covariance has a clearly positive null eigenvalue gap.
    assert 0.20 < result.measured_covariance_direct_fraction < 0.45
    assert 0.10 < result.measured_extracted_primary_fraction < 0.35


def test_tracking_time_is_expressed_on_the_actual_hop_clock() -> None:
    assert calibration.tracking_time_ms(0.85) == pytest.approx(320.0)
    assert calibration.tracking_time_ms(0.5) == pytest.approx(85.3333333333)
