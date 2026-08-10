"""從封面圖抽出整套 UI 色票。

做法是「飽和度加權的粗量化直方圖」：把像素量化進 16³ 個色箱，
每箱評分 = 平均飽和度 × √像素數。比 k-means 快一個數量級，
而且對同一張圖永遠給出同樣結果 —— 這對截圖回歸測試很重要。

輸入是 ``(H, W, 3)`` 的 uint8 RGB 陣列，本模組不碰 Qt。
"""

from __future__ import annotations

import colorsys
import hashlib

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    ACCENT2_HUE_SHIFT,
    ACCENT_MAX_VALUE,
    ACCENT_MIN_SATURATION,
    ACCENT_MIN_VALUE,
    BG_BOTTOM_VALUE,
    BG_SATURATION,
    BG_TOP_VALUE,
    COLOR_HIST_BITS,
    COLOR_MIN_SATURATION,
    COLOR_MIN_VALUE,
    COVER_SAMPLE_SIZE,
    FALLBACK_HUE_COUNT,
)
from aurora.core.models import Palette

FloatArray = npt.NDArray[np.float32]

#: 封面完全沒有可用色彩時的預設色相（冷藍紫，襯深色底好看）。
_NEUTRAL_HUE = 232.0


def _subsample(rgb: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """用整數步進把圖降到約 ``COVER_SAMPLE_SIZE`` 見方。不做插值，夠用且快。"""
    height, width = rgb.shape[:2]
    step_y = max(1, height // COVER_SAMPLE_SIZE)
    step_x = max(1, width // COVER_SAMPLE_SIZE)
    return rgb[::step_y, ::step_x]


def _rgb_to_hsv(rgb: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
    """向量化 RGB→HSV。輸入 0..1，回傳 (色相 0..360, 飽和度 0..1, 明度 0..1)。"""
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    value = rgb.max(axis=-1)
    minimum = rgb.min(axis=-1)
    chroma = value - minimum

    saturation = np.where(value > 0, chroma / np.maximum(value, 1e-12), 0.0)

    # 依最大分量決定色相所在的 60° 區段
    hue = np.zeros_like(value)
    safe_chroma = np.maximum(chroma, 1e-12)
    is_red = (value == red) & (chroma > 0)
    is_green = (value == green) & (chroma > 0)
    is_blue = (value == blue) & (chroma > 0)
    hue = np.where(is_red, ((green - blue) / safe_chroma) % 6.0, hue)
    hue = np.where(is_green, (blue - red) / safe_chroma + 2.0, hue)
    hue = np.where(is_blue, (red - green) / safe_chroma + 4.0, hue)
    hue *= 60.0

    return (
        hue.astype(np.float32),
        saturation.astype(np.float32),
        value.astype(np.float32),
    )


def _hex(hue: float, saturation: float, value: float) -> str:
    red, green, blue = colorsys.hsv_to_rgb((hue % 360.0) / 360.0, saturation, value)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def dominant_hue(rgb: npt.NDArray[np.uint8]) -> tuple[float, float] | None:
    """回傳封面主色的 (色相, 飽和度)。整張圖都是灰階或空的話回傳 ``None``。"""
    if rgb.size == 0 or rgb.ndim != 3 or rgb.shape[2] < 3:
        return None

    sample = _subsample(rgb[:, :, :3]).astype(np.float32) / 255.0
    _hue, saturation, value = _rgb_to_hsv(sample)

    keep = (saturation >= COLOR_MIN_SATURATION) & (value >= COLOR_MIN_VALUE)
    if not bool(keep.any()):
        return None

    # 量化進 (2^bits)³ 個色箱
    levels = 1 << COLOR_HIST_BITS
    quantized = (sample[keep] * (levels - 1)).round().astype(np.int32)
    bins = (quantized[:, 0] * levels + quantized[:, 1]) * levels + quantized[:, 2]
    kept_saturation = saturation[keep]

    counts = np.bincount(bins, minlength=levels**3).astype(np.float32)
    saturation_sum = np.bincount(bins, weights=kept_saturation, minlength=levels**3)
    nonempty = counts > 0
    scores = np.zeros_like(counts)
    scores[nonempty] = (saturation_sum[nonempty] / counts[nonempty]) * np.sqrt(counts[nonempty])

    winner = int(scores.argmax())
    member = bins == winner
    # 用該箱內像素的平均值當代表色，比用箱中心準
    mean_rgb = sample[keep][member].mean(axis=0).reshape(1, 1, 3).astype(np.float32)
    win_hue, win_saturation, _value = _rgb_to_hsv(mean_rgb)
    return float(win_hue[0, 0]), float(win_saturation[0, 0])


def palette_from_hue(hue: float, saturation: float) -> Palette:
    """由一組色相/飽和度長出整套色票，並把 accent 亮度夾進可讀區間。"""
    accent_saturation = float(np.clip(max(saturation, ACCENT_MIN_SATURATION), 0.0, 1.0))
    accent_value = float(np.clip((ACCENT_MIN_VALUE + ACCENT_MAX_VALUE) / 2, 0.0, 1.0))
    return Palette(
        accent=_hex(hue, accent_saturation, accent_value),
        accent2=_hex(hue + ACCENT2_HUE_SHIFT, accent_saturation * 0.92, accent_value),
        bg_top=_hex(hue, BG_SATURATION, BG_TOP_VALUE),
        bg_bottom=_hex(hue + ACCENT2_HUE_SHIFT * 0.5, BG_SATURATION * 0.8, BG_BOTTOM_VALUE),
    )


def palette_from_cover(rgb: npt.NDArray[np.uint8]) -> Palette:
    """封面 → 色票。抽不出主色時退回中性色相。"""
    found = dominant_hue(rgb)
    if found is None:
        return palette_from_hue(_NEUTRAL_HUE, ACCENT_MIN_SATURATION)
    return palette_from_hue(*found)


def palette_from_seed(seed: str) -> Palette:
    """沒有封面時，用檔名雜湊產生穩定且分散的色相。"""
    digest = hashlib.sha256(seed.encode("utf-8", "replace")).digest()
    hue = (int.from_bytes(digest[:4], "big") % FALLBACK_HUE_COUNT) * 1.0
    return palette_from_hue(hue, 0.55)
