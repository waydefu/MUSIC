"""可重現的離線 DSP 數值報告，不開 Qt、音訊裝置，也不需要測試音檔。

執行：uv run python tools/analyze_dsp.py
輸出 JSON 的峰值是獨立 FFT 插值 oracle，不是限幅器內部的估計。
效能另外用 bench_callback.py 量；聽感不由這份報告推論。
"""

from __future__ import annotations

import json

import numpy as np
import numpy.typing as npt

from aurora.core.acoustics import (
    fft_true_peak,
    interaural_cross_correlation,
    zero_lag_correlation,
)
from aurora.core.constants import LIMITER_CEILING, SPATIAL_FFT_SIZE
from aurora.core.dynamics import Limiter
from aurora.core.spatial import SpatialUpmix

RealArray = npt.NDArray[np.float64]
FloatArray = npt.NDArray[np.float32]
RATE = 48000
BLOCK = 2880


def db(value: float) -> float:
    return float(20.0 * np.log10(max(value, np.finfo(np.float64).tiny)))


def render(signal: RealArray, sample_rate: int) -> tuple[FloatArray, int]:
    limiter = Limiter()
    limiter.prepare(sample_rate, signal.shape[1], BLOCK * 2)
    padding = limiter.latency_frames * 4
    output = np.pad(signal.astype(np.float32), ((padding, padding), (0, 0)))
    for start in range(0, len(output), BLOCK):
        limiter.process(output[start : start + BLOCK].reshape(-1))
    return output, limiter.latency_frames


def limiter_report() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    n = np.arange(16384)
    for sample_rate in (44100, 48000, 96000, 192000):
        quarter = 1.2 * np.sin(2 * np.pi * n / 4 + np.pi / 4)
        clipped = 0.9 * np.tanh(
            3
            * (
                np.sin(2 * np.pi * 2100 * n / sample_rate)
                + 0.7 * np.sin(2 * np.pi * 5300 * n / sample_rate + 1)
                + 0.5 * np.sin(2 * np.pi * 11900 * n / sample_rate + 2)
            )
        )
        for kind, mono in (("quarter_rate", quarter), ("clipped_multitone", clipped)):
            signal = np.column_stack((mono, -0.8 * mono))
            output, latency = render(signal, sample_rate)
            rows.append(
                {
                    "signal": kind,
                    "sample_rate": sample_rate,
                    "input_sample_peak_dbfs": db(float(np.abs(signal).max())),
                    "input_fft4_peak_dbtp": db(
                        fft_true_peak(np.pad(signal, ((2304, 2304), (0, 0))))
                    ),
                    "output_fft4_peak_dbtp": db(fft_true_peak(output)),
                    "output_fft8_peak_db": db(fft_true_peak(output, factor=8)),
                    "latency_frames": latency,
                    "latency_ms": latency / sample_rate * 1000,
                }
            )

    rng = np.random.default_rng(12345)
    stress: list[dict[str, object]] = []
    for kind in ("noise", "clipped_noise", "multitone", "burst", "nyquist_band"):
        worst = -np.inf
        worst8 = -np.inf
        for case in range(10):
            if kind == "noise":
                signal = rng.normal(0, 1, (16384, 2))
            elif kind == "clipped_noise":
                signal = np.clip(rng.normal(0, 2, (16384, 2)), -0.95, 0.95)
            elif kind == "multitone":
                frequencies = rng.uniform(0.001, 0.45, 9)
                phases = rng.uniform(0, 2 * np.pi, 9)
                mono = np.sin(2 * np.pi * n[:, None] * frequencies + phases).sum(axis=1) * 0.4
                signal = np.column_stack((mono, np.roll(mono, 3)))
            elif kind == "burst":
                signal = rng.normal(0, 0.01, (16384, 2))
                signal[500:520] = rng.normal(0, 3, (20, 2))
                signal[-20:] = rng.normal(0, 3, (20, 2))
            else:
                mono = 1.2 * np.sin(2 * np.pi * n * (0.45 + case * 0.0049) + 0.78)
                signal = np.column_stack((mono, mono))
            output, _ = render(signal, RATE)
            worst = max(worst, db(fft_true_peak(output)))
            worst8 = max(worst8, db(fft_true_peak(output, factor=8)))
        stress.append(
            {"signal": kind, "cases": 10, "worst_fft4_dbtp": worst, "worst_fft8_db": worst8}
        )
    return {"target_dbtp": db(LIMITER_CEILING), "regressions": rows, "stress": stress}


def projection_report() -> dict[str, object]:
    rows: list[dict[str, float]] = []
    bins = SPATIAL_FFT_SIZE // 2 + 1
    for amplitude in (1.0, 1e-3, 1e-6, 1e-12):
        spatial = SpatialUpmix()
        spatial.prepare(RATE, 2, BLOCK)
        mid = np.full(bins, amplitude, dtype=np.complex128)
        side = mid * (0.3 + 0.2j)
        primary_mid, primary_side = spatial._analyse(mid, side)
        error = (
            max(float(np.abs(primary_mid - mid).max()), float(np.abs(primary_side - side).max()))
            / amplitude
        )
        rows.append({"amplitude": amplitude, "relative_error": error})

    # C 尚未處理的有限樣本偏差也照實量，避免把尺度修正誤寫成估計完全無偏。
    rng = np.random.default_rng(601)
    source = rng.normal(size=(160, bins)) + 1j * rng.normal(size=(160, bins))
    noise = rng.normal(size=(160, bins, 2)) + 1j * rng.normal(size=(160, bins, 2))
    estimates: list[dict[str, float]] = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        spatial = SpatialUpmix()
        spatial.prepare(RATE, 2, BLOCK)
        primary_power, total_power = 0.0, 0.0
        for hop in range(source.shape[0]):
            left = np.sqrt(fraction) * source[hop] + np.sqrt(1 - fraction) * noise[hop, :, 0]
            right = np.sqrt(fraction) * source[hop] + np.sqrt(1 - fraction) * noise[hop, :, 1]
            mid, side = (left + right) / 2, (left - right) / 2
            primary_mid, primary_side = spatial._analyse(mid, side)
            if hop >= 50:
                primary_power += float(np.sum(np.abs(primary_mid) ** 2 + np.abs(primary_side) ** 2))
                total_power += float(np.sum(np.abs(mid) ** 2 + np.abs(side) ** 2))
        estimates.append(
            {
                "input_direct_fraction": fraction,
                "extracted_power_fraction": primary_power / total_power,
            }
        )
    return {"scale_invariance": rows, "finite_sample_bias_still_present": estimates}


def main() -> None:
    rng = np.random.default_rng(992)
    left = np.pad(rng.normal(size=8192), (64, 64))
    right = np.roll(left, 32)
    report = {
        "evidence": "offline numerical verification; listening and device performance unverified",
        "limiter": limiter_report(),
        "primary_projection": projection_report(),
        "correlation_example": {
            "itd_us": 32 / RATE * 1e6,
            "zero_lag_signed": zero_lag_correlation(left, right),
            "iacc_one_ms": interaural_cross_correlation(left, right, RATE),
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
