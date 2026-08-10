"""歌詞面板的 ViewModel。

Signals
-------
``lyricsChanged()``
    換歌載入新歌詞（或確定沒有歌詞）時。
``activeChanged()``
    目前該高亮的行或字變了。每個 UI 幀最多發一次，而且只在真的改變時發。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from aurora.bridge.models import LyricsModel
from aurora.core.lrc import active_line_index, active_word_index, parse_lrc
from aurora.core.models import Lyrics
from aurora.library.metadata import read_lyrics_text


class LyricsController(QObject):
    """把 LRC 變成 QML 綁得動的「目前第幾行、第幾個字」。"""

    lyricsChanged = Signal()
    activeChanged = Signal()
    seekRequested = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = LyricsModel(self)
        self._lyrics = Lyrics()
        self._active = -1
        self._word = -1

    # ------------------------------------------------------------ 屬性

    @Property(QObject, constant=True)
    def model(self) -> LyricsModel:
        return self._model

    @Property(int, notify=activeChanged)
    def activeIndex(self) -> int:
        return self._active

    @Property(int, notify=activeChanged)
    def activeWord(self) -> int:
        return self._word

    @Property(bool, notify=lyricsChanged)
    def hasLyrics(self) -> bool:
        return not self._lyrics.is_empty

    @Property(bool, notify=lyricsChanged)
    def hasWordTiming(self) -> bool:
        return self._lyrics.has_word_timing

    @Property(int, notify=lyricsChanged)
    def lineCount(self) -> int:
        return len(self._lyrics.lines)

    # ------------------------------------------------------------ 操作

    def load_for(self, audio_path: str | None) -> None:
        """換歌時呼叫。先找同名 .lrc，再退回內嵌標籤。"""
        text = read_lyrics_text(audio_path) if audio_path else ""
        self._lyrics = parse_lrc(text) if text else Lyrics()
        self._model.replace(self._lyrics.lines)
        self._active = -1
        self._word = -1
        self.lyricsChanged.emit()
        self.activeChanged.emit()

    def update_position(self, seconds: float) -> None:
        """每個 UI 幀呼叫。只在高亮位置真的改變時才發訊號。"""
        if self._lyrics.is_empty:
            return

        line = active_line_index(self._lyrics, seconds)
        word = -1
        if 0 <= line < len(self._lyrics.lines):
            word = active_word_index(self._lyrics.lines[line], seconds, self._lyrics.offset_ms)

        if line != self._active or word != self._word:
            self._active = line
            self._word = word
            self.activeChanged.emit()

    @Slot(int)
    def seekToLine(self, row: int) -> None:
        """點擊某一行 → 跳到那一句的時間。"""
        if 0 <= row < len(self._lyrics.lines):
            target = self._lyrics.lines[row].time_sec - self._lyrics.offset_ms / 1000.0
            self.seekRequested.emit(max(0.0, target))
