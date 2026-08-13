"""給 QML 用的清單模型。

頻譜為什麼用 ``QAbstractListModel`` 而不是一個 list property：
QML 裡寫 ``spectrum.bars[index]`` 是 JavaScript 陣列取值，60fps × 64 條
等於每秒近四千次 JS 求值，而 Qt 官方明確警告「動畫期間不要跑 JavaScript」。
改用模型後 delegate 綁的是 ``model.value``，走 C++ 的屬性讀取，零 JS。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from aurora.core.constants import SPECTRUM_BARS
from aurora.core.models import LyricLine, SpectrumFrame, Track

_VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
_PEAK_ROLE = Qt.ItemDataRole.UserRole + 2
_ROOT_INDEX = QModelIndex()


class SpectrumModel(QAbstractListModel):
    """64 條頻譜的數值與峰值。長度固定，只更新內容不做插入刪除。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bars = [0.0] * SPECTRUM_BARS
        self._peaks = [0.0] * SPECTRUM_BARS

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        if parent.isValid():
            return 0
        return SPECTRUM_BARS

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = _VALUE_ROLE) -> Any:
        row = index.row()
        if not 0 <= row < SPECTRUM_BARS:
            return None
        if role == _VALUE_ROLE:
            return self._bars[row]
        if role == _PEAK_ROLE:
            return self._peaks[row]
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            _VALUE_ROLE: QByteArray(b"value"),
            _PEAK_ROLE: QByteArray(b"peak"),
        }

    def apply(self, frame: SpectrumFrame) -> None:
        """每幀呼叫一次。整段一次 ``dataChanged``，不是 64 次。"""
        self._bars = list(frame.bars)
        self._peaks = list(frame.peaks)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(SPECTRUM_BARS - 1, 0),
            [_VALUE_ROLE, _PEAK_ROLE],
        )


_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_TITLE_ROLE = Qt.ItemDataRole.UserRole + 2
_ARTIST_ROLE = Qt.ItemDataRole.UserRole + 3
_ALBUM_ROLE = Qt.ItemDataRole.UserRole + 4
_DURATION_ROLE = Qt.ItemDataRole.UserRole + 5
_COVER_ROLE = Qt.ItemDataRole.UserRole + 6
_LOSSLESS_ROLE = Qt.ItemDataRole.UserRole + 7
_TRACK_ROLES = [
    _PATH_ROLE,
    _TITLE_ROLE,
    _ARTIST_ROLE,
    _ALBUM_ROLE,
    _DURATION_ROLE,
    _COVER_ROLE,
    _LOSSLESS_ROLE,
]


def _duration_text(seconds: float) -> str:
    if seconds <= 0:
        return "--:--"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlaylistModel(QAbstractListModel):
    """播放清單。同一份資料也拿來當音樂庫檢視，差別只在餵進來的曲目集合。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        if parent.isValid():
            return 0
        return len(self._tracks)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = _TITLE_ROLE) -> Any:
        row = index.row()
        if not 0 <= row < len(self._tracks):
            return None
        track = self._tracks[row]
        return {
            _PATH_ROLE: track.path,
            _TITLE_ROLE: track.display_title,
            _ARTIST_ROLE: track.display_artist,
            _ALBUM_ROLE: track.album,
            _DURATION_ROLE: _duration_text(track.duration_sec),
            _COVER_ROLE: _file_url(track.cover_path),
            _LOSSLESS_ROLE: track.lossless,
        }.get(role)

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            _PATH_ROLE: QByteArray(b"path"),
            _TITLE_ROLE: QByteArray(b"title"),
            _ARTIST_ROLE: QByteArray(b"artist"),
            _ALBUM_ROLE: QByteArray(b"album"),
            _DURATION_ROLE: QByteArray(b"duration"),
            _COVER_ROLE: QByteArray(b"cover"),
            _LOSSLESS_ROLE: QByteArray(b"lossless"),
        }

    # ------------------------------------------------------------ 編輯

    @property
    def tracks(self) -> list[Track]:
        return self._tracks

    def replace(self, tracks: list[Track]) -> None:
        self.beginResetModel()
        self._tracks = list(tracks)
        self.endResetModel()

    def append(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        start = len(self._tracks)
        self.beginInsertRows(QModelIndex(), start, start + len(tracks) - 1)
        self._tracks.extend(tracks)
        self.endInsertRows()

    def remove_at(self, row: int) -> None:
        if not 0 <= row < len(self._tracks):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._tracks[row]
        self.endRemoveRows()

    def clear(self) -> None:
        self.replace([])

    def track_at(self, row: int) -> Track | None:
        return self._tracks[row] if 0 <= row < len(self._tracks) else None

    def replace_at(self, row: int, track: Track) -> bool:
        """原地補齊一列的 metadata，不重設模型或改變目前選取位置。"""
        if not 0 <= row < len(self._tracks):
            return False
        self._tracks[row] = track
        changed = self.index(row, 0)
        self.dataChanged.emit(changed, changed, _TRACK_ROLES)
        return True

    def update_track(self, track: Track) -> tuple[int, ...]:
        """以路徑更新所有相符列，供背景 metadata 載入完成時使用。"""
        target = track.path.casefold()
        updated: list[int] = []
        for row, current in enumerate(self._tracks):
            if current.path.casefold() != target:
                continue
            self._tracks[row] = track
            changed = self.index(row, 0)
            self.dataChanged.emit(changed, changed, _TRACK_ROLES)
            updated.append(row)
        return tuple(updated)

    def index_of(self, path: str) -> int:
        lowered = path.lower()
        for row, track in enumerate(self._tracks):
            if track.path.lower() == lowered:
                return row
        return -1


class PlaylistFilterProxy(QSortFilterProxyModel):
    """播放清單的即時搜尋代理，保留來源列索引供播放與刪除使用。"""

    def __init__(self, source: PlaylistModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._query = ""
        self.setSourceModel(source)

    def set_query(self, query: str) -> None:
        normalized = query.strip().casefold()
        if normalized == self._query:
            return
        self.beginFilterChange()
        self._query = normalized
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def source_row(self, proxy_row: int) -> int:
        index = self.index(proxy_row, 0)
        if not index.isValid():
            return -1
        return self.mapToSource(index).row()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not self._query:
            return True
        source = self.sourceModel()
        if not isinstance(source, PlaylistModel):
            return False
        track = source.track_at(source_row)
        if track is None:
            return False
        haystack = " ".join((track.display_title, track.display_artist, track.album, track.path))
        return self._query in haystack.casefold()


_LINE_TEXT_ROLE = Qt.ItemDataRole.UserRole + 1
_LINE_TIME_ROLE = Qt.ItemDataRole.UserRole + 2


class LyricsModel(QAbstractListModel):
    """歌詞行。哪一行要高亮由 ``LyricsController.activeIndex`` 決定，
    delegate 只需比對自己的 index，不必自己算時間。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lines: list[LyricLine] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        if parent.isValid():
            return 0
        return len(self._lines)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = _LINE_TEXT_ROLE) -> Any:
        row = index.row()
        if not 0 <= row < len(self._lines):
            return None
        if role == _LINE_TEXT_ROLE:
            return self._lines[row].text
        if role == _LINE_TIME_ROLE:
            return self._lines[row].time_sec
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            _LINE_TEXT_ROLE: QByteArray(b"text"),
            _LINE_TIME_ROLE: QByteArray(b"time"),
        }

    def replace(self, lines: tuple[LyricLine, ...]) -> None:
        self.beginResetModel()
        self._lines = list(lines)
        self.endResetModel()

    def time_at(self, row: int) -> float:
        return self._lines[row].time_sec if 0 <= row < len(self._lines) else 0.0


def _file_url(path: str | None) -> str:
    """本機路徑轉成 QML ``Image.source`` 吃得下的 URL。

    直接把 Windows 路徑丟給 QML 會被當成相對 URL，中文路徑更會整個壞掉，
    所以一律走 ``QUrl.fromLocalFile``。
    """
    if not path:
        return ""
    from PySide6.QtCore import QUrl

    return QUrl.fromLocalFile(path).toString()
