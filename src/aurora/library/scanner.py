"""資料夾掃描。

刻意寫成純 Python 產生器而非 QThread 子類別 —— 掃描邏輯因此可以無頭測試，
要不要丟到背景執行緒由 bridge 層決定。這是分層規約的一部分。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from aurora.core.constants import AUDIO_EXTENSIONS, SCAN_BATCH_SIZE
from aurora.core.models import ScanProgress, Track
from aurora.library.metadata import read_track
from aurora.library.store import LibraryCache

#: 這些目錄不可能有使用者的音樂，掃了只是浪費時間。
_SKIP_DIRS = frozenset({"$recycle.bin", "system volume information", "node_modules", ".git"})


def iter_audio_files(roots: list[str] | tuple[str, ...]) -> Iterator[Path]:
    """遞迴列出所有支援的音訊檔。

    用 ``os.scandir`` 而不是 ``Path.rglob``：前者一次系統呼叫就能同時拿到
    名稱與型別，掃大型音樂庫時差距很明顯。權限不足的目錄直接跳過。
    """
    stack = [Path(root) for root in roots]
    seen: set[str] = set()

    while stack:
        current = stack.pop()
        try:
            resolved = str(current.resolve()).lower()
        except OSError:
            continue
        if resolved in seen:  # 對付符號連結造成的環
            continue
        seen.add(resolved)

        try:
            entries = list(os.scandir(current))
        except (OSError, PermissionError):
            continue

        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in _SKIP_DIRS and not entry.name.startswith("."):
                        stack.append(Path(entry.path))
                elif Path(entry.name).suffix.lower() in AUDIO_EXTENSIONS:
                    yield Path(entry.path)
            except OSError:
                continue


def scan(
    roots: list[str] | tuple[str, ...],
    cache: LibraryCache | None = None,
    batch_size: int = SCAN_BATCH_SIZE,
) -> Iterator[ScanProgress]:
    """掃描並逐批產出結果。

    每 ``batch_size` 首才產出一次，避免呼叫端被訊號淹沒。
    有快取時，檔案的 mtime 與大小都沒變就直接沿用，不重讀標籤。
    """
    batch: list[Track] = []
    scanned = 0
    added = 0

    for path in iter_audio_files(roots):
        scanned += 1
        track = cache.get(path) if cache else None
        if track is None:
            track = read_track(path)
            if track is not None and cache is not None:
                cache.put(track)
        if track is None:
            continue

        added += 1
        batch.append(track)
        if len(batch) >= batch_size:
            yield ScanProgress(scanned, added, str(path.parent), False, tuple(batch))
            batch = []

    yield ScanProgress(scanned, added, "", True, tuple(batch))
