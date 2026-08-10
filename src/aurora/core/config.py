"""使用者設定的 schema 與讀寫。

兩個原則：

1. **壞掉的設定檔絕不能讓播放器開不起來。** 任何解析錯誤都退回預設值。
2. **寫入必須是原子的。** 先寫暫存檔再 ``os.replace``，避免當機時留下半個 JSON。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

from aurora.core.paths import config_file

RepeatMode = Literal["off", "all", "one"]
QualityPreset = Literal["cinematic", "balanced", "performance"]

_REPEAT_MODES: frozenset[str] = frozenset({"off", "all", "one"})
_QUALITY_PRESETS: frozenset[str] = frozenset({"cinematic", "balanced", "performance"})


@dataclass(slots=True)
class WindowGeometry:
    x: int = -1
    y: int = -1
    width: int = 1180
    height: int = 760

    @property
    def is_placed(self) -> bool:
        return self.x >= 0 and self.y >= 0


@dataclass(slots=True)
class Config:
    """整個 app 的持久化狀態。"""

    volume: float = 0.8
    muted: bool = False
    shuffle: bool = False
    repeat: RepeatMode = "off"

    playlist: list[str] = field(default_factory=list)
    current_index: int = -1
    current_position: float = 0.0

    library_folders: list[str] = field(default_factory=list)

    window: WindowGeometry = field(default_factory=WindowGeometry)
    mini_mode: bool = False
    playlist_visible: bool = True
    lyrics_visible: bool = False
    quality_visible: bool = False

    quality_preset: QualityPreset = "cinematic"
    #: ``None`` 表示跟隨 Windows 的「顯示動畫」系統設定。
    reduce_motion: bool | None = None
    cinema_mode: bool = False

    # ---------------------------------------------------------- 序列化

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        """逐欄位挑值並做型別修正。多餘的鍵忽略，缺少的鍵用預設值。"""
        config = cls()
        known = {item.name for item in fields(cls)}

        for key, value in raw.items():
            if key not in known or key == "window":
                continue
            setattr(config, key, value)

        window = raw.get("window")
        if isinstance(window, dict):
            config.window = WindowGeometry(
                x=int(window.get("x", -1)),
                y=int(window.get("y", -1)),
                width=int(window.get("width", 1180)),
                height=int(window.get("height", 760)),
            )

        config._sanitize()
        return config

    def _sanitize(self) -> None:
        """把任何不合理的值拉回合法範圍。設定檔是使用者可編輯的，不能信任。"""
        self.volume = min(max(float(self.volume), 0.0), 1.0)
        self.current_position = max(0.0, float(self.current_position))

        if self.repeat not in _REPEAT_MODES:
            self.repeat = "off"
        if self.quality_preset not in _QUALITY_PRESETS:
            self.quality_preset = "cinematic"

        self.playlist = [str(item) for item in self.playlist if isinstance(item, str)]
        self.library_folders = [str(item) for item in self.library_folders if isinstance(item, str)]

        if not self.playlist:
            self.current_index = -1
        else:
            self.current_index = min(max(int(self.current_index), -1), len(self.playlist) - 1)

        if self.reduce_motion is not None:
            self.reduce_motion = bool(self.reduce_motion)

        self.window.width = max(720, int(self.window.width))
        self.window.height = max(480, int(self.window.height))


def load_config(path: Path | None = None) -> Config:
    """讀設定；檔案不存在、格式壞掉、或內容不是物件時一律回預設值。"""
    target = path or config_file()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return Config()

    if not isinstance(raw, dict):
        return Config()

    try:
        return Config.from_dict(raw)
    except (TypeError, ValueError):
        return Config()


def save_config(config: Config, path: Path | None = None) -> bool:
    """原子寫入。回傳是否成功 —— 存不了設定不該中斷播放。"""
    target = path or config_file()
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError:
        temporary.unlink(missing_ok=True)
        return False
    return True
