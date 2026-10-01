"""離線聲學量測；不在音訊回呼上呼叫。

零延遲 Pearson 相關可辨識反相，IACC 則搜尋 ±1 ms 的時間差並取絕對最大。
兩者回答不同問題。量分頻帶、early／late 時，呼叫端先濾波、再選時間窗，
不能把整段全頻的數值直接當作頭外化或主觀自然度。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aurora.core.constants import IACC_MAX_LAG_MS, LIMITER_TRUE_PEAK_FACTOR

RealArray = npt.NDArray[np.float64]


def _pair(left: npt.ArrayLike, right: npt.ArrayLike) -> tuple[RealArray, RealArray]:
    x, y = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if x.ndim != 1 or y.shape != x.shape or x.size == 0:
        raise ValueError("量測需要非空、等長的一維左右聲道")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("量測訊號必須有限")
    # 先縮放，讓極小／極大振幅都不會在內積時下溢／溢位。
    scale = max(float(np.abs(x).max()), float(np.abs(y).max()))
    if scale:
        x, y = x / scale, y / scale
    return x, y


def zero_lag_correlation(left: npt.ArrayLike, right: npt.ArrayLike) -> float:
    """有正負號、扣掉均值的 Pearson 相關；靜音或常數訊號回傳 0。"""
    x, y = _pair(left, right)
    x, y = x - x.mean(), y - y.mean()
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denominator == 0.0:
        return 0.0
    return float(np.clip(np.dot(x, y) / denominator, -1.0, 1.0))


def interaural_cross_correlation(
    left: npt.ArrayLike,
    right: npt.ArrayLike,
    sample_rate: int,
    max_lag_ms: float = IACC_MAX_LAG_MS,
) -> float:
    """選定時間窗內的 IACC：正規化互相關在 ±max_lag_ms 的絕對最大值。

    使用固定的整窗能量作分母，超出時間窗的樣本視為零；不對短的重疊片段
    各自正規化，避免邊緣幾個樣本就被誤報成完美相關。時間差解析度是一框。
    """
    if sample_rate <= 0 or not np.isfinite(max_lag_ms) or max_lag_ms < 0.0:
        raise ValueError("取樣率必須為正值、搜尋時間必須有限且非負")
    x, y = _pair(left, right)
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denominator == 0.0:
        return 0.0
    lag = min(int(np.floor(sample_rate * max_lag_ms / 1000.0)), x.size - 1)
    best = abs(float(np.dot(x, y)))
    for offset in range(1, lag + 1):
        best = max(best, abs(float(np.dot(x[:-offset], y[offset:]))))
        best = max(best, abs(float(np.dot(x[offset:], y[:-offset]))))
    return float(np.clip(best / denominator, 0.0, 1.0))


def fft_true_peak(samples: npt.ArrayLike, factor: int = LIMITER_TRUE_PEAK_FACTOR) -> float:
    """FFT 零補點插值的峰值 oracle，輸入為 frames × channels。

    不使用限幅器的 FIR 係數。FFT 假設首尾週期接續；非週期素材應先補靜音，
    確認峰值不是首尾接縫。偶數長度的 Nyquist 格須平分到正負頻率。
    """
    signal = np.asarray(samples, dtype=np.float64)
    if signal.ndim != 2 or not signal.size or not np.all(np.isfinite(signal)):
        raise ValueError("量測需要非空且有限的 frames × channels 訊號")
    if not isinstance(factor, int) or factor < 2:
        raise ValueError("插值倍率必須是至少 2 的整數")
    frames = signal.shape[0]
    spectrum = np.fft.rfft(signal, axis=0)
    if frames % 2 == 0:
        spectrum[-1] *= 0.5
    interpolated = np.fft.irfft(spectrum, n=frames * factor, axis=0) * factor
    return float(np.abs(interpolated).max())
