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


def octave_band_filter(
    samples: npt.ArrayLike,
    sample_rate: int,
    centre_hz: float,
    *,
    taps: int = 1025,
) -> RealArray:
    """離線用的一倍頻程 FIR；保留時間對齊，不宣稱 ISO 濾波器相容。

    通帶邊界為 centre/sqrt(2) 到 centre*sqrt(2)。核心是奇數抽頭、
    Kaiser-windowed sinc，前後補零後用 valid convolution，所以輸出長度與
    原訊號相同，且不額外移動直達聲位置。這個函式只用於診斷 IACC 分頻帶，
    不進 realtime renderer。
    """
    signal = np.asarray(samples, dtype=np.float64)
    if signal.ndim != 1 or signal.size == 0 or not np.all(np.isfinite(signal)):
        raise ValueError("濾波需要非空且有限的一維訊號")
    if sample_rate <= 0 or not np.isfinite(centre_hz) or centre_hz <= 0.0:
        raise ValueError("取樣率與中心頻率必須為正值")
    if not isinstance(taps, int) or taps < 3 or taps % 2 == 0:
        raise ValueError("FIR 抽頭數必須是至少 3 的奇數")

    low = centre_hz / np.sqrt(2.0)
    high = centre_hz * np.sqrt(2.0)
    if high >= sample_rate / 2.0:
        raise ValueError("倍頻程上緣必須低於 Nyquist")

    half = taps // 2
    offsets = np.arange(taps, dtype=np.float64) - half
    high_kernel = 2.0 * high / sample_rate * np.sinc(2.0 * high / sample_rate * offsets)
    low_kernel = 2.0 * low / sample_rate * np.sinc(2.0 * low / sample_rate * offsets)
    kernel = (high_kernel - low_kernel) * np.kaiser(taps, 8.6)

    response = abs(
        np.sum(kernel * np.exp(-2j * np.pi * centre_hz / sample_rate * np.arange(taps)))
    )
    if response <= 0.0:
        raise RuntimeError("倍頻程 FIR 中心頻率響應為零")
    kernel /= response

    padded = np.pad(signal, (half, half))
    return np.asarray(np.convolve(padded, kernel, mode="valid"), dtype=np.float64)


def windowed_iacc(
    left: npt.ArrayLike,
    right: npt.ArrayLike,
    sample_rate: int,
    *,
    start_ms: float,
    end_ms: float,
    direct_index: int = 0,
    centre_hz: float | None = None,
) -> float:
    """量 BRIR 相對直達聲抵達點的一段 IACC。

    start_ms / end_ms 都相對 direct_index。若指定 centre_hz，會先對完整左右
    IR 做同一個一倍頻程 FIR，再切時間窗。late window 的終點刻意由呼叫端
    指定：不同研究與工具對晚期截止時間並不一致。
    """
    if sample_rate <= 0:
        raise ValueError("取樣率必須為正值")
    x, y = _pair(left, right)
    if not isinstance(direct_index, int) or not 0 <= direct_index < x.size:
        raise ValueError("direct_index 必須落在訊號範圍內")
    if (
        not np.isfinite(start_ms)
        or not np.isfinite(end_ms)
        or start_ms < 0.0
        or end_ms <= start_ms
    ):
        raise ValueError("時間窗必須有限，且滿足 0 <= start < end")

    if centre_hz is not None:
        x = octave_band_filter(x, sample_rate, centre_hz)
        y = octave_band_filter(y, sample_rate, centre_hz)

    start = direct_index + round(start_ms * sample_rate / 1000.0)
    end = direct_index + round(end_ms * sample_rate / 1000.0)
    if start >= x.size:
        raise ValueError("時間窗起點超出訊號")
    end = min(end, x.size)
    if end - start < 2:
        raise ValueError("時間窗太短")
    return interaural_cross_correlation(x[start:end], y[start:end], sample_rate)


def iacc_e3(
    left: npt.ArrayLike,
    right: npt.ArrayLike,
    sample_rate: int,
    *,
    direct_index: int = 0,
) -> dict[str, float]:
    """常見 room-acoustics IACC_E3：0–80 ms 的 500/1k/2k Hz octave IACC 平均。

    這是 BRIR/房間診斷參數，不是 AURORA 自然度分數，也不應拿來設定單一
    pass/fail 門檻。呼叫端必須提供已知的直達聲抵達位置。
    """
    values = {
        "500_hz": windowed_iacc(
            left, right, sample_rate, start_ms=0.0, end_ms=80.0,
            direct_index=direct_index, centre_hz=500.0,
        ),
        "1000_hz": windowed_iacc(
            left, right, sample_rate, start_ms=0.0, end_ms=80.0,
            direct_index=direct_index, centre_hz=1000.0,
        ),
        "2000_hz": windowed_iacc(
            left, right, sample_rate, start_ms=0.0, end_ms=80.0,
            direct_index=direct_index, centre_hz=2000.0,
        ),
    }
    values["mean"] = float(np.mean(tuple(values.values())))
    return values

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
