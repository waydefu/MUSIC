"""封面 → 主題色。

Python 這邊只負責「算出目標色」，**過場動畫完全交給 QML** ——
``Behavior on color { ColorAnimation }`` 由場景圖在 render thread 上跑，
比在 Python 裡逐幀插值好得多，也符合「動效歸 QML」的分層。

Signals
-------
``paletteChanged()``
    換歌抽出新色票時發一次。QML 綁定的 accent/bgTop 等會自動過場。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import Property, QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage

from aurora.core.colorx import palette_from_cover, palette_from_seed
from aurora.core.constants import COVER_SAMPLE_SIZE
from aurora.core.models import Palette


def _image_to_array(image: QImage) -> npt.NDArray[np.uint8] | None:
    """QImage → ``(H, W, 3)`` uint8。注意每列有對齊填充，不能直接 reshape。"""
    if image.isNull():
        return None
    scaled = image.scaled(
        COVER_SAMPLE_SIZE,
        COVER_SAMPLE_SIZE,
        aspectMode=Qt.AspectRatioMode.IgnoreAspectRatio,
    ).convertToFormat(QImage.Format.Format_RGB888)

    width, height, stride = scaled.width(), scaled.height(), scaled.bytesPerLine()
    if width <= 0 or height <= 0:
        return None

    raw = np.frombuffer(bytes(scaled.constBits()), dtype=np.uint8)
    if raw.size < stride * height:
        return None
    return raw[: stride * height].reshape(height, stride)[:, : width * 3].reshape(height, width, 3)


class ThemeController(QObject):
    """整個 UI 的色彩來源。"""

    paletteChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._palette = palette_from_seed("aurora")

    # ------------------------------------------------------------ 屬性

    def _color(self, value: str) -> QColor:
        return QColor(value)

    @Property(QColor, notify=paletteChanged)
    def accent(self) -> QColor:
        return self._color(self._palette.accent)

    @Property(QColor, notify=paletteChanged)
    def accent2(self) -> QColor:
        return self._color(self._palette.accent2)

    @Property(QColor, notify=paletteChanged)
    def bgTop(self) -> QColor:
        return self._color(self._palette.bg_top)

    @Property(QColor, notify=paletteChanged)
    def bgBottom(self) -> QColor:
        return self._color(self._palette.bg_bottom)

    @Property(QColor, notify=paletteChanged)
    def textPrimary(self) -> QColor:
        return self._color(self._palette.text_primary)

    @Property(QColor, notify=paletteChanged)
    def textSecondary(self) -> QColor:
        return self._color(self._palette.text_secondary)

    # ------------------------------------------------------------ 更新

    def apply_cover(self, cover_path: str | None, fallback_seed: str = "") -> None:
        """依封面重算色票。沒有封面時用檔名雜湊產生穩定且分散的色相。"""
        palette: Palette | None = None
        if cover_path:
            array = _image_to_array(QImage(cover_path))
            if array is not None:
                palette = palette_from_cover(array)
        if palette is None:
            palette = palette_from_seed(fallback_seed or "aurora")

        if palette != self._palette:
            self._palette = palette
            self.paletteChanged.emit()

    @property
    def palette(self) -> Palette:
        return self._palette
