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

from aurora.core.constants import EQ_BAND_HZ, EQ_GAIN_LIMIT_DB
from aurora.core.paths import config_file

RepeatMode = Literal["off", "all", "one"]
QualityPreset = Literal["cinematic", "balanced", "performance"]
PanelName = Literal["", "playlist", "library", "lyrics", "quality", "settings", "effects"]

_PANEL_NAMES: frozenset[str] = frozenset(
    {"", "playlist", "library", "lyrics", "quality", "settings", "effects"}
)

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
    #: 右側面板一次只會開一個，所以用單一字串而不是好幾個布林值 ——
    #: 布林值可以組合出「兩個都開」這種不存在的狀態，字串則不會。
    #: 空字串代表全部收起。預設開播放清單，開啟後馬上看得到自己的音樂。
    open_panel: PanelName = "playlist"

    quality_preset: QualityPreset = "cinematic"
    font_scale: float = 1.0
    #: ``None`` 表示跟隨 Windows 的「顯示動畫」系統設定。
    reduce_motion: bool | None = None
    cinema_mode: bool = False

    # 音效。預設全關 —— 使用者沒開過就不該付延遲與運算成本。
    eq_enabled: bool = False
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * len(EQ_BAND_HZ))
    spatial_amount: float = 0.0

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
        self.font_scale = min(max(float(self.font_scale), 0.8), 1.35)

        if self.repeat not in _REPEAT_MODES:
            self.repeat = "off"
        if self.quality_preset not in _QUALITY_PRESETS:
            self.quality_preset = "cinematic"
        if self.open_panel not in _PANEL_NAMES:
            self.open_panel = "playlist"

        self.playlist = [str(item) for item in self.playlist if isinstance(item, str)]
        self.library_folders = [str(item) for item in self.library_folders if isinstance(item, str)]

        if not self.playlist:
            self.current_index = -1
        else:
            self.current_index = min(max(int(self.current_index), -1), len(self.playlist) - 1)

        if self.reduce_motion is not None:
            self.reduce_motion = bool(self.reduce_motion)

        # 音效的值全部來自使用者可編輯的 JSON，一律夾回合法範圍。
        # 段數不對就整組丟掉退回全平 —— 補零會讓使用者拿到一條他沒設定過的
        # 曲線，那比重置更難理解。
        self.eq_enabled = bool(self.eq_enabled)
        gains = [
            min(max(float(value), -EQ_GAIN_LIMIT_DB), EQ_GAIN_LIMIT_DB)
            for value in self.eq_gains
            if isinstance(value, int | float)
        ]
        self.eq_gains = gains if len(gains) == len(EQ_BAND_HZ) else [0.0] * len(EQ_BAND_HZ)
        self.spatial_amount = min(max(float(self.spatial_amount), 0.0), 1.0)

        self.window.width = max(720, int(self.window.width))
        self.window.height = max(480, int(self.window.height))


def load_config(path: Path | None = None) -> Config:
    """讀設定；檔案不存在、格式壞掉、或內容不是物件時一律回預設值。

    編碼用 ``utf-8-sig`` 而不是 ``utf-8``：Windows 上的記事本、PowerShell 的
    ``Out-File -Encoding utf8`` 等工具寫出來的 UTF-8 都帶 BOM，而 ``json.loads``
    看到 BOM 會直接拋 JSONDecodeError —— 結果就是使用者手動編輯過設定檔之後，
    所有設定無聲無息地全部回到預設值。``utf-8-sig`` 兩種都吃得下。
    """
    target = path or config_file()
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
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
