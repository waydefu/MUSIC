"""動效與畫質的總開關。

三段畫質預設對應到 QML 裡各特效的啟用與否。降級順序是刻意的：
先關粒子與色散（最貴、也最不影響可讀性），再降 bloom，最後才動模糊 ——
模糊背景是這個介面的識別，寧可犧牲其他也要留著。

「減少動態」預設跟隨 Windows 的協助工具設定。Apple HIG 與 Material Design
都把尊重這個設定列為硬性要求，不是選配。

Signals
-------
``presetChanged()`` / ``reduceMotionChanged()``
    QML 綁定會自動重算所有特效開關。
``fpsChanged()``
    每秒更新一次量測到的畫面更新率。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from aurora.core.config import Config, QualityPreset
from aurora.platform_win.osinfo import system_animations_enabled

#: 三段預設各自開啟哪些特效。QML 只讀這裡算出來的布林值，不自己判斷。
_PRESETS: dict[str, dict[str, bool | float]] = {
    "cinematic": {
        "particles": True,
        "chromatic": True,
        "grain": True,
        "bloom": True,
        "depthOfField": True,
        "bloomStrength": 1.0,
        "blurQuality": 1.0,
    },
    "balanced": {
        "particles": False,
        "chromatic": False,
        "grain": True,
        "bloom": True,
        "depthOfField": True,
        "bloomStrength": 0.6,
        "blurQuality": 0.8,
    },
    "performance": {
        "particles": False,
        "chromatic": False,
        "grain": False,
        "bloom": False,
        "depthOfField": False,
        "bloomStrength": 0.0,
        "blurQuality": 0.5,
    },
}

_ORDER: tuple[QualityPreset, ...] = ("cinematic", "balanced", "performance")

#: 量測期間平均更新率低於這個值就自動降一級。
_DEGRADE_FPS = 45.0
#: 開始量測前先讓場景暖機這麼多幀（著色器編譯、貼圖上傳都在這期間）。
_WARMUP_FRAMES = 90
#: 每次量測取樣這麼多幀。
_SAMPLE_FRAMES = 120


class MotionController(QObject):
    """畫質預設、減少動態、以及自動降級。"""

    presetChanged = Signal()
    reduceMotionChanged = Signal()
    fpsChanged = Signal()
    degraded = Signal(str)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._preset = config.quality_preset
        self._system_animations = system_animations_enabled()
        self._auto_degrade = True

        self._frames = 0
        self._fps = 0.0
        self._show_fps = False
        self._last_stamp = time.perf_counter()
        self._sample_start = self._last_stamp

    # ------------------------------------------------------------ 畫質

    @Property(str, notify=presetChanged)
    def preset(self) -> str:
        return self._preset

    @preset.setter  # type: ignore[no-redef]
    def preset(self, value: QualityPreset) -> None:
        self._set_preset(value)

    def _set_preset(self, value: QualityPreset) -> None:
        if value not in _PRESETS or value == self._preset:
            return
        self._preset = value
        self._config.quality_preset = value
        self.presetChanged.emit()

    @Slot()
    def cyclePreset(self) -> None:
        current = _ORDER.index(self._preset) if self._preset in _ORDER else 0
        self._set_preset(_ORDER[(current + 1) % len(_ORDER)])
        self._auto_degrade = False  # 使用者手動選過就不再自動降級

    @Property(str, notify=presetChanged)
    def presetLabel(self) -> str:
        return {"cinematic": "電影", "balanced": "均衡", "performance": "效能"}[self._preset]

    # 個別特效開關 ——— QML 直接綁，不在 QML 裡寫判斷

    def _flag(self, name: str) -> bool:
        if self.reduceMotion and name in ("particles", "chromatic"):
            return False
        return bool(_PRESETS[self._preset][name])

    @Property(bool, notify=presetChanged)
    def particlesEnabled(self) -> bool:
        return self._flag("particles")

    @Property(bool, notify=presetChanged)
    def chromaticEnabled(self) -> bool:
        return self._flag("chromatic")

    @Property(bool, notify=presetChanged)
    def grainEnabled(self) -> bool:
        return self._flag("grain")

    @Property(bool, notify=presetChanged)
    def bloomEnabled(self) -> bool:
        return self._flag("bloom")

    @Property(bool, notify=presetChanged)
    def depthOfFieldEnabled(self) -> bool:
        return self._flag("depthOfField")

    @Property(float, notify=presetChanged)
    def bloomStrength(self) -> float:
        return float(_PRESETS[self._preset]["bloomStrength"])

    @Property(float, notify=presetChanged)
    def blurQuality(self) -> float:
        return float(_PRESETS[self._preset]["blurQuality"])

    # ------------------------------------------------------------ 減少動態

    @Property(bool, notify=reduceMotionChanged)
    def reduceMotion(self) -> bool:
        """使用者明確設定優先；沒設過就跟隨 Windows 的「動畫效果」偏好。"""
        if self._config.reduce_motion is not None:
            return self._config.reduce_motion
        return not self._system_animations

    @Slot(bool)
    def setReduceMotion(self, value: bool) -> None:
        self._config.reduce_motion = bool(value)
        self.reduceMotionChanged.emit()
        self.presetChanged.emit()  # 粒子與色散的開關跟著變

    @Slot()
    def followSystemMotion(self) -> None:
        self._config.reduce_motion = None
        self._system_animations = system_animations_enabled()
        self.reduceMotionChanged.emit()
        self.presetChanged.emit()

    # ------------------------------------------------------------ FPS

    @Property(float, notify=fpsChanged)
    def fps(self) -> float:
        return self._fps

    @Property(bool, constant=True)
    def showFps(self) -> bool:
        return self._show_fps

    def set_show_fps(self, value: bool) -> None:
        self._show_fps = value

    def note_frame(self) -> None:
        """每個算繪幀呼叫一次。量到持續掉幀就自動降一級畫質。"""
        self._frames += 1
        now = time.perf_counter()

        if now - self._last_stamp >= 1.0:
            self._fps = self._frames / (now - self._last_stamp)
            self._frames = 0
            self._last_stamp = now
            self.fpsChanged.emit()
            self._maybe_degrade(now)

    def _maybe_degrade(self, now: float) -> None:
        if not self._auto_degrade or self._preset == "performance":
            return
        # 暖機期間（著色器編譯、貼圖上傳）的更新率不具代表性
        elapsed = now - self._sample_start
        if elapsed < (_WARMUP_FRAMES + _SAMPLE_FRAMES) / 60.0:
            return
        if self._fps >= _DEGRADE_FPS:
            self._sample_start = now
            return

        lower = _ORDER[min(_ORDER.index(self._preset) + 1, len(_ORDER) - 1)]
        if lower != self._preset:
            self._preset = lower
            self._config.quality_preset = lower
            self.presetChanged.emit()
            self.degraded.emit(self.presetLabel)
        self._sample_start = now
