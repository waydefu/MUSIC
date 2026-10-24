"""Calibrate SpatialUpmix primary/ambient estimator without changing product DSP.

This isolates _analyse() from the STFT renderer by feeding the same per-bin complex
signal model the estimator assumes:

    stereo = one rank-1 directional source + equal-power independent ambience.

Two quantities are intentionally reported separately:

* covariance_direct_fraction: eigenvalue anisotropy. In the infinite-sample model
  this estimates the direct fraction of total M/S power.
* extracted_primary_fraction: actual energy returned by the current Wiener/MMSE
  projection. Even with perfect covariance this is lower than the source fraction
  whenever ambience is present, because Wiener shrinkage is deliberate.

Therefore extracted_primary_fraction must NOT be tested against the source fraction.
The tool is research/diagnostic only; it does not tune runtime parameters.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from aurora.core.constants import DSP_REFERENCE_RATE, SPATIAL_FFT_SIZE, SPATIAL_HOP
from aurora.core.spatial import SpatialUpmix

ComplexArray = npt.NDArray[np.complex128]

DEFAULT_DIRECT_RATIOS = (0.0, 0.25, 0.5, 0.75, 1.0)
DEFAULT_PAN_GAINS = (1.0, 10.0 ** (-6.0 / 20.0))
DEFAULT_ALPHAS = (0.85, 0.75, 0.60, 0.50)


@dataclass(frozen=True)
class ModelTarget:
    direct_power: float
    ambient_power_per_axis: float
    total_power: float
    direct_fraction: float
    wiener_extracted_fraction: float


@dataclass(frozen=True)
class CalibrationResult:
    source_mix: float
    pan_gain: float
    alpha: float
    target_direct_fraction: float
    target_wiener_extracted_fraction: float
    measured_covariance_direct_fraction: float
    measured_extracted_primary_fraction: float
    covariance_error: float
    extracted_error_vs_wiener_target: float


def model_target(source_mix: float, pan_gain: float) -> ModelTarget:
    """Analytical infinite-sample target for the calibration signal model."""
    f = float(source_mix)
    g = float(pan_gain)
    if not 0.0 <= f <= 1.0:
        raise ValueError("source_mix must be in [0, 1]")
    if g < 0.0 or not math.isfinite(g):
        raise ValueError("pan_gain must be finite and non-negative")

    # L=sqrt(f)s+sqrt(1-f)n1, R=sqrt(f)g*s+sqrt(1-f)n2.
    # In M/S, independent equal-power ambience is isotropic with A per axis.
    direct = f * (1.0 + g * g) * 0.5
    ambient_axis = (1.0 - f) * 0.5
    total = direct + 2.0 * ambient_axis
    if total == 0.0:
        return ModelTarget(direct, ambient_axis, total, 0.0, 0.0)

    direct_fraction = direct / total
    # Along the dominant axis, Cx has power P+A. The Wiener gain is
    # P/(P+A), so output primary power is P^2/(P+A).
    wiener = (
        0.0
        if direct == 0.0
        else direct * direct / (direct + ambient_axis) / total
    )
    return ModelTarget(direct, ambient_axis, total, direct_fraction, wiener)


def ewma_effective_samples(alpha: float) -> float:
    """Equivalent sample count from squared normalized EWMA weights."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    return (1.0 + alpha) / (1.0 - alpha)


def independent_complex_wishart_null_bias(alpha: float) -> float:
    """Reference E[(lambda1-lambda2)/(lambda1+lambda2)] for isotropic noise.

    For a 2x2 complex Wishart covariance with n independent equal-weight samples,
    q=(lambda1-lambda2)/(lambda1+lambda2) has density proportional to
    q^2(1-q^2)^(n-2). We substitute the EWMA equivalent sample count. This is an
    analytical *reference*, not a runtime correction: overlapping STFT frames are
    not independent and therefore must be measured separately.
    """
    n = ewma_effective_samples(alpha)
    log_beta_2 = math.lgamma(2.0) + math.lgamma(n - 1.0) - math.lgamma(n + 1.0)
    log_beta_15 = (
        math.lgamma(1.5) + math.lgamma(n - 1.0) - math.lgamma(n + 0.5)
    )
    return math.exp(log_beta_2 - log_beta_15)


def _complex_gaussian(rng: np.random.Generator, bins: int) -> ComplexArray:
    real = rng.standard_normal(bins)
    imag = rng.standard_normal(bins)
    return np.asarray((real + 1j * imag) / math.sqrt(2.0), dtype=np.complex128)


def _covariance_direct_fraction(processor: SpatialUpmix) -> float:
    a = processor._smoothed_m
    b = processor._smoothed_s
    x = processor._smoothed_cross
    spread = np.sqrt((0.5 * (a - b)) ** 2 + np.abs(x) ** 2)
    trace = a + b
    total = float(np.sum(trace))
    return 0.0 if total <= 0.0 else float(np.sum(2.0 * spread) / total)


def calibrate_stationary(
    source_mix: float,
    pan_gain: float,
    alpha: float,
    *,
    seeds: Iterable[int] = (1, 2, 3, 4),
    frames: int = 320,
    warmup: int = 80,
) -> CalibrationResult:
    """Measure steady-state estimator bias for one synthetic configuration."""
    if frames <= warmup:
        raise ValueError("frames must be greater than warmup")

    target = model_target(source_mix, pan_gain)
    covariance_samples: list[float] = []
    extracted_samples: list[float] = []

    for seed in seeds:
        processor = SpatialUpmix()
        processor.prepare(DSP_REFERENCE_RATE, 2, 2880)
        processor.amount = 1.0
        processor._smoothing = float(alpha)
        bins = SPATIAL_FFT_SIZE // 2 + 1
        rng = np.random.default_rng(seed)

        for frame in range(frames):
            source = _complex_gaussian(rng, bins)
            noise_l = _complex_gaussian(rng, bins)
            noise_r = _complex_gaussian(rng, bins)
            root_direct = math.sqrt(source_mix)
            root_ambient = math.sqrt(1.0 - source_mix)
            left = root_direct * source + root_ambient * noise_l
            right = root_direct * pan_gain * source + root_ambient * noise_r
            mid = (left + right) * 0.5
            side = (left - right) * 0.5

            primary_mid, primary_side = processor._analyse(mid, side)
            if frame < warmup:
                continue

            input_power = float(np.sum(np.abs(mid) ** 2 + np.abs(side) ** 2))
            primary_power = float(
                np.sum(np.abs(primary_mid) ** 2 + np.abs(primary_side) ** 2)
            )
            extracted_samples.append(primary_power / max(input_power, 1e-30))
            covariance_samples.append(_covariance_direct_fraction(processor))

    measured_covariance = float(np.mean(covariance_samples))
    measured_extracted = float(np.mean(extracted_samples))
    return CalibrationResult(
        source_mix=source_mix,
        pan_gain=pan_gain,
        alpha=alpha,
        target_direct_fraction=target.direct_fraction,
        target_wiener_extracted_fraction=target.wiener_extracted_fraction,
        measured_covariance_direct_fraction=measured_covariance,
        measured_extracted_primary_fraction=measured_extracted,
        covariance_error=measured_covariance - target.direct_fraction,
        extracted_error_vs_wiener_target=(
            measured_extracted - target.wiener_extracted_fraction
        ),
    )


def tracking_time_ms(alpha: float, *, threshold: float = 0.9) -> float:
    """Ideal EWMA step-response time in the estimator's hop clock."""
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be in (0, 1)")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    hops = math.ceil(math.log(1.0 - threshold) / math.log(alpha))
    return hops * SPATIAL_HOP / DSP_REFERENCE_RATE * 1000.0


def build_report(
    alphas: Iterable[float] = DEFAULT_ALPHAS,
    ratios: Iterable[float] = DEFAULT_DIRECT_RATIOS,
    pan_gains: Iterable[float] = DEFAULT_PAN_GAINS,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    alpha_rows: list[dict[str, float]] = []
    for alpha in alphas:
        alpha_rows.append(
            {
                "alpha": float(alpha),
                "ideal_t90_ms": tracking_time_ms(float(alpha)),
                "ewma_effective_samples": ewma_effective_samples(float(alpha)),
                "independent_complex_wishart_null_bias": (
                    independent_complex_wishart_null_bias(float(alpha))
                ),
            }
        )
        for pan_gain in pan_gains:
            for ratio in ratios:
                rows.append(
                    asdict(
                        calibrate_stationary(
                            float(ratio), float(pan_gain), float(alpha)
                        )
                    )
                )

    return {
        "purpose": "offline estimator calibration; no product tuning",
        "model": (
            "rank-1 complex Gaussian directional source plus equal-power independent "
            "complex Gaussian ambience in L/R"
        ),
        "interpretation": {
            "covariance_direct_fraction": (
                "compare with target_direct_fraction; finite-window eigenvalue spread "
                "creates a positive null bias"
            ),
            "extracted_primary_fraction": (
                "compare with target_wiener_extracted_fraction, NOT the source direct "
                "fraction; Wiener shrinkage is part of the current estimator"
            ),
            "wishart_null_bias": (
                "independent-sample analytical reference only; do not use directly as "
                "a runtime correction for overlapping STFT frames"
            ),
        },
        "alpha_reference": alpha_rows,
        "stationary": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))


if __name__ == "__main__":
    main()
