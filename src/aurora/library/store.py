"""音樂庫快取。

以 ``路徑 + mtime + 大小`` 當鍵：只要檔案沒被動過就不重讀標籤，
重掃一個上萬首的音樂庫因此從幾分鐘變成幾秒。

跟設定檔一樣採原子寫入，而且**壞掉的快取一律當成沒有快取** ——
快取失效只是慢一點，絕不能讓音樂庫開不起來。
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aurora.core.models import AudioFormat, Track
from aurora.core.paths import library_file

#: 快取格式版本。改動 Track 欄位或快取鍵格式時要 +1，舊快取會被自動丟棄。
#:
#: v2 將路徑統一成 NFC，避免 APFS 的 NFD 檔名與 Windows 的 NFC 檔名對同一首歌
#: 產生不同快取鍵。
_SCHEMA_VERSION = 2


def _cache_key(path: Path, mtime: float, size: int) -> str:
    normalized_path = unicodedata.normalize("NFC", str(path)).lower()
    return f"{normalized_path}|{int(mtime)}|{size}"


def _track_to_dict(track: Track) -> dict[str, Any]:
    raw = asdict(track)
    raw["fmt"] = asdict(track.fmt) if track.fmt else None
    return raw


def _track_from_dict(raw: dict[str, Any]) -> Track | None:
    try:
        fmt_raw = raw.get("fmt")
        fmt = AudioFormat(**fmt_raw) if isinstance(fmt_raw, dict) else None
        return Track(**{**raw, "fmt": fmt})
    except (TypeError, ValueError):
        return None


class LibraryCache:
    """曲目中繼資料的持久化快取。"""

    def __init__(self) -> None:
        self._entries: dict[str, Track] = {}
        self._dirty = False

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def tracks(self) -> tuple[Track, ...]:
        return tuple(self._entries.values())

    # ------------------------------------------------------------ 查詢

    def get(self, path: Path) -> Track | None:
        """檔案未變動時回傳快取的曲目，否則回 ``None`` 讓呼叫端重讀。"""
        try:
            stat = path.stat()
        except OSError:
            return None
        return self._entries.get(_cache_key(path, stat.st_mtime, stat.st_size))

    def put(self, track: Track) -> None:
        self._entries[_cache_key(Path(track.path), track.mtime, track.size)] = track
        self._dirty = True

    def prune_missing(self) -> int:
        """移除已經不存在的檔案。回傳清掉的筆數。"""
        gone = [key for key, track in self._entries.items() if not Path(track.path).exists()]
        for key in gone:
            del self._entries[key]
        self._dirty = self._dirty or bool(gone)
        return len(gone)

    # ------------------------------------------------------------ 持久化

    def load(self, path: Path | None = None) -> bool:
        target = path or library_file()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False

        if not isinstance(raw, dict) or raw.get("version") != _SCHEMA_VERSION:
            return False

        entries = raw.get("tracks")
        if not isinstance(entries, dict):
            return False

        loaded: dict[str, Track] = {}
        for key, value in entries.items():
            if not isinstance(value, dict):
                continue
            track = _track_from_dict(value)
            if track is not None:
                loaded[key] = track

        self._entries = loaded
        self._dirty = False
        return True

    def save(self, path: Path | None = None, force: bool = False) -> bool:
        """原子寫入。沒有變更時直接跳過，除非 ``force``。"""
        if not self._dirty and not force:
            return True

        target = path or library_file()
        temporary = target.with_suffix(target.suffix + ".tmp")
        payload = {
            "version": _SCHEMA_VERSION,
            "tracks": {key: _track_to_dict(track) for key, track in self._entries.items()},
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, target)
        except OSError:
            temporary.unlink(missing_ok=True)
            return False

        self._dirty = False
        return True
