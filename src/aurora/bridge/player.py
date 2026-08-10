"""主控制器：播放清單、傳輸控制、以及每幀的節拍。

執行緒紀律：音訊回呼**不會**碰到這個物件。所有狀態都由這裡的 60 Hz
計時器從引擎輪詢出來再轉成 Qt signal，這樣 QML 綁定永遠在主執行緒更新。

Signals
-------
``trackChanged()``      曲目換了，標題／演出者／封面都已更新
``positionChanged()``   每個 UI 幀（位置真的有變時）
``playingChanged()``    播放／暫停狀態
``volumeChanged()`` ``shuffleChanged()`` ``repeatChanged()``
``indexChanged()``      播放清單的目前索引
``toast(str)``          需要短暫提示使用者的訊息
"""

from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from aurora.audio.engine import AudioEngine
from aurora.bridge.lyrics import LyricsController
from aurora.bridge.models import PlaylistFilterProxy, PlaylistModel, SpectrumModel
from aurora.bridge.quality import QualityController
from aurora.bridge.theme import ThemeController
from aurora.core.config import Config, save_config
from aurora.core.constants import AUDIO_EXTENSIONS, SEEK_STEP_SEC, UI_TICK_HZ, VOLUME_STEP
from aurora.core.models import Track
from aurora.library.metadata import read_track
from aurora.library.scanner import group_audio_files

_REPEAT_ORDER = ("off", "all", "one")
_REPEAT_LABEL = {"off": "不循環", "all": "全部循環", "one": "單曲循環"}


def _clock(seconds: float) -> str:
    if seconds <= 0:
        return "0:00"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class PlayerController(QObject):
    """QML 的主要對話對象。"""

    trackChanged = Signal()
    positionChanged = Signal()
    frameAdvanced = Signal()
    panelChanged = Signal()
    playingChanged = Signal()
    volumeChanged = Signal()
    shuffleChanged = Signal()
    repeatChanged = Signal()
    indexChanged = Signal()
    libraryChanged = Signal()
    libraryFolderAdded = Signal()
    miniModeChanged = Signal()
    fontScaleChanged = Signal()
    toast = Signal(str)
    beat = Signal()

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._engine = AudioEngine()
        self._playlist = PlaylistModel(self)
        self._filtered_playlist = PlaylistFilterProxy(self._playlist, self)
        self._spectrum = SpectrumModel(self)
        self._theme = ThemeController(self)
        self._lyrics = LyricsController(self)
        self._quality = QualityController(self._engine, self)

        self._index = -1
        self._position = 0.0
        self._energy = 0.0
        self._bass = 0.0
        self._shuffle_order: list[int] = []
        self._library_playlists: dict[str, tuple[str, ...]] = {}
        self._engine.volume = config.volume
        self._engine.muted = config.muted

        self._lyrics.seekRequested.connect(self.seekTo)
        self._quality.outputRateChanged.connect(self._on_output_rate)

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, 1000 // UI_TICK_HZ))
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------ 子物件

    @Property(QObject, constant=True)
    def playlist(self) -> PlaylistModel:
        return self._playlist

    @Property(QObject, constant=True)
    def filteredPlaylist(self) -> PlaylistFilterProxy:
        return self._filtered_playlist

    @Property(QObject, constant=True)
    def spectrum(self) -> SpectrumModel:
        return self._spectrum

    @Property(QObject, constant=True)
    def theme(self) -> ThemeController:
        return self._theme

    @Property(QObject, constant=True)
    def lyrics(self) -> LyricsController:
        return self._lyrics

    @Property(QObject, constant=True)
    def quality(self) -> QualityController:
        return self._quality

    @Property(bool, notify=miniModeChanged)
    def miniMode(self) -> bool:
        return self._config.mini_mode

    @Property(float, notify=fontScaleChanged)
    def fontScale(self) -> float:
        return self._config.font_scale

    @Property(list, notify=libraryChanged)
    def libraryPlaylists(self) -> list[dict[str, object]]:
        return [
            {"path": folder, "label": Path(folder).name or folder, "count": len(paths)}
            for folder, paths in self._library_playlists.items()
        ]

    # ------------------------------------------------------------ 曲目資訊

    @property
    def _track(self) -> Track | None:
        return self._playlist.track_at(self._index)

    @Property(str, notify=trackChanged)
    def title(self) -> str:
        track = self._track
        return track.display_title if track else "沒有播放中的曲目"

    @Property(str, notify=trackChanged)
    def artist(self) -> str:
        track = self._track
        return track.display_artist if track else ""

    @Property(str, notify=trackChanged)
    def album(self) -> str:
        track = self._track
        return track.album if track else ""

    @Property(str, notify=trackChanged)
    def coverUrl(self) -> str:
        track = self._track
        if track is None or not track.cover_path:
            return ""
        return QUrl.fromLocalFile(track.cover_path).toString()

    @Property(bool, notify=trackChanged)
    def hasTrack(self) -> bool:
        return self._track is not None

    @Property(str, notify=trackChanged)
    def currentPath(self) -> str:
        track = self._track
        return track.path if track else ""

    @Property(str, notify=trackChanged)
    def sourceSummary(self) -> str:
        """給主畫面小徽章用的一行摘要，例如「FLAC · 44.1kHz · 無損」。"""
        track = self._track
        if track is None:
            return ""
        parts = [track.codec.upper()]
        if track.fmt:
            parts.append(f"{track.fmt.sample_rate / 1000:g}kHz")
        parts.append("無損" if track.lossless else f"{track.bitrate_kbps or '?'}kbps")
        return " · ".join(parts)

    # ------------------------------------------------------------ 播放狀態

    @Property(float, notify=positionChanged)
    def position(self) -> float:
        return self._position

    @Property(float, notify=trackChanged)
    def duration(self) -> float:
        return self._engine.duration

    @Property(float, notify=positionChanged)
    def progress(self) -> float:
        total = self._engine.duration
        return min(1.0, self._position / total) if total > 0 else 0.0

    @Property(str, notify=positionChanged)
    def positionText(self) -> str:
        return _clock(self._position)

    @Property(str, notify=trackChanged)
    def durationText(self) -> str:
        return _clock(self._engine.duration)

    @Property(str, notify=panelChanged)
    def openPanel(self) -> str:
        """目前展開的右側面板名稱，空字串代表全部收起。

        存在設定檔裡，所以下次開啟播放器會回到同一個面板 ——
        先前這個狀態雖然有欄位卻從來沒被讀寫過，面板永遠是收起的。
        """
        return str(self._config.open_panel)

    @Slot(str)
    def setOpenPanel(self, name: str) -> None:
        if name == self._config.open_panel:
            return
        self._config.open_panel = name  # type: ignore[assignment]
        self.panelChanged.emit()

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        return self._engine.is_playing

    @Property(float, notify=frameAdvanced)
    def energy(self) -> float:
        """整體響度 0..1。封面呼吸、播放鍵光暈、粒子發射率都綁這個值，
        所有視覺元件因此共用同一個節拍。"""
        return self._energy

    @Property(float, notify=frameAdvanced)
    def bass(self) -> float:
        """低頻能量 0..1。驅動暗角收縮這類「被聲音撞了一下」的效果。"""
        return self._bass

    @Property(float, notify=volumeChanged)
    def volume(self) -> float:
        return self._engine.volume

    @Property(bool, notify=volumeChanged)
    def muted(self) -> bool:
        return self._engine.muted

    @Property(bool, notify=shuffleChanged)
    def shuffle(self) -> bool:
        return self._config.shuffle

    @Property(str, notify=repeatChanged)
    def repeatMode(self) -> str:
        return self._config.repeat

    @Property(str, notify=repeatChanged)
    def repeatLabel(self) -> str:
        return _REPEAT_LABEL[self._config.repeat]

    @Property(int, notify=indexChanged)
    def index(self) -> int:
        return self._index

    @Property(int, notify=indexChanged)
    def count(self) -> int:
        return self._playlist.rowCount()

    # ------------------------------------------------------------ 傳輸控制

    @Slot()
    def togglePlay(self) -> None:
        if not self._engine.path and self._playlist.rowCount():
            self.playIndex(0)
            return
        self._engine.toggle()
        self.playingChanged.emit()

    @Slot()
    def playNext(self) -> None:
        self._advance(1, manual=True)

    @Slot()
    def playPrevious(self) -> None:
        """三秒內按上一首才真的跳上一首，否則回到本曲開頭 —— 這是通用慣例。"""
        if self._position > 3.0:
            self.seekTo(0.0)
            return
        self._advance(-1, manual=True)

    @Slot(int)
    def playIndex(self, row: int) -> None:
        if not 0 <= row < self._playlist.rowCount():
            return
        self._load(row)
        self._engine.play()
        self.playingChanged.emit()

    @Slot(float)
    def seekTo(self, seconds: float) -> None:
        if self._engine.seek(seconds):
            self._position = self._engine.position
            self.positionChanged.emit()

    @Slot(float)
    def seekFraction(self, fraction: float) -> None:
        total = self._engine.duration
        if total > 0:
            self.seekTo(min(max(fraction, 0.0), 1.0) * total)

    @Slot(float)
    def nudge(self, seconds: float = SEEK_STEP_SEC) -> None:
        self.seekTo(self._position + seconds)

    # ------------------------------------------------------------ 音量與模式

    @Slot(float)
    def setVolume(self, value: float) -> None:
        self._engine.volume = value
        self._engine.muted = False
        self._config.volume = self._engine.volume
        self.volumeChanged.emit()

    @Slot(float)
    def bumpVolume(self, delta: float = VOLUME_STEP) -> None:
        self.setVolume(self._engine.volume + delta)

    @Slot()
    def toggleMute(self) -> None:
        self._engine.muted = not self._engine.muted
        self._config.muted = self._engine.muted
        self.volumeChanged.emit()

    @Slot()
    def toggleShuffle(self) -> None:
        self._config.shuffle = not self._config.shuffle
        self._reshuffle()
        self.shuffleChanged.emit()
        self.toast.emit("隨機播放：開" if self._config.shuffle else "隨機播放：關")

    @Slot()
    def cycleRepeat(self) -> None:
        current = _REPEAT_ORDER.index(self._config.repeat)
        self._config.repeat = _REPEAT_ORDER[(current + 1) % len(_REPEAT_ORDER)]  # type: ignore[assignment]
        self.repeatChanged.emit()
        self.toast.emit(_REPEAT_LABEL[self._config.repeat])

    # ------------------------------------------------------------ 播放清單

    @Slot("QVariantList")
    def addUrls(self, urls: list[QUrl] | list[str]) -> None:
        """接收拖放進來的檔案或資料夾。

        資料夾代表一個固定音樂庫根目錄；其子資料夾會在音樂庫面板中各自成為歌單。
        個別音檔才直接加進目前的播放清單，避免把大型音樂庫攤平成一張未分類清單。
        """
        paths: list[str] = []
        for item in urls:
            local = item.toLocalFile() if isinstance(item, QUrl) else str(item)
            if not local:
                continue
            target = Path(local)
            if target.is_dir():
                self._add_library_path(target)
            elif target.suffix.lower() in AUDIO_EXTENSIONS:
                paths.append(local)
        self.addPaths(paths)

    @Slot("QStringList")
    def addPaths(self, paths: list[str]) -> None:
        self._add_paths(paths, autoplay_when_empty=True)

    def _add_paths(self, paths: list[str], *, autoplay_when_empty: bool) -> None:
        tracks = [track for path in paths if (track := read_track(path)) is not None]
        if not tracks:
            return
        was_empty = self._playlist.rowCount() == 0
        self._playlist.append(tracks)
        self._reshuffle()
        self.indexChanged.emit()
        self.toast.emit(f"已加入 {len(tracks)} 首")
        if was_empty and autoplay_when_empty:
            self.playIndex(0)

    @Slot(QUrl)
    def addLibraryFolder(self, folder: QUrl) -> None:
        self._add_library_path(Path(folder.toLocalFile()))

    @Slot(str)
    def setPlaylistSearch(self, query: str) -> None:
        self._filtered_playlist.set_query(query)

    @Slot(int)
    def playFilteredIndex(self, row: int) -> None:
        source_row = self._filtered_playlist.source_row(row)
        if source_row >= 0:
            self.playIndex(source_row)

    @Slot(int)
    def removeFilteredAt(self, row: int) -> None:
        source_row = self._filtered_playlist.source_row(row)
        if source_row >= 0:
            self.removeAt(source_row)

    @Slot(bool)
    def setMiniMode(self, enabled: bool) -> None:
        if self._config.mini_mode == enabled:
            return
        self._config.mini_mode = enabled
        save_config(self._config)
        self.miniModeChanged.emit()

    @Slot(float)
    def setFontScale(self, scale: float) -> None:
        normalized = min(max(float(scale), 0.8), 1.35)
        if abs(normalized - self._config.font_scale) < 1e-3:
            return
        self._config.font_scale = normalized
        save_config(self._config)
        self.fontScaleChanged.emit()

    def _add_library_path(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        resolved = str(path.resolve())
        if any(item.casefold() == resolved.casefold() for item in self._config.library_folders):
            self.toast.emit("這個音樂資料夾已加入。")
            return False
        self._config.library_folders.append(resolved)
        self._refresh_library()
        save_config(self._config)
        self.libraryFolderAdded.emit()
        self.toast.emit(f"已加入音樂庫：{path.name or resolved}")
        return True

    @Slot(str)
    def loadLibraryPlaylist(self, folder: str) -> None:
        paths = self._library_playlists.get(folder, ())
        if not paths:
            self.toast.emit("This folder has no playable music.")
            return
        self.clearPlaylist()
        self._add_paths(list(paths), autoplay_when_empty=False)

    @Slot()
    def clearPlaylist(self) -> None:
        self._engine.stop()
        self._playlist.clear()
        self._index = -1
        self._shuffle_order = []
        self.indexChanged.emit()
        self.trackChanged.emit()
        self.playingChanged.emit()

    @Slot(int)
    def removeAt(self, row: int) -> None:
        if row == self._index:
            self._engine.stop()
        self._playlist.remove_at(row)
        if row < self._index:
            self._index -= 1
        elif row == self._index:
            self._index = min(self._index, self._playlist.rowCount() - 1)
        self._reshuffle()
        self.indexChanged.emit()
        self.trackChanged.emit()

    # ------------------------------------------------------------ 生命週期

    def start(self) -> None:
        self._quality.start()
        self._timer.start()
        self._refresh_library()
        self._restore()

    def shutdown(self) -> None:
        self._timer.stop()
        self._quality.stop()
        self._persist()
        self._engine.close()

    # ------------------------------------------------------------ 內部

    def _load(self, row: int) -> None:
        track = self._playlist.track_at(row)
        if track is None:
            return
        self._index = row
        self._engine.load(track.path, track.duration_sec)
        self._position = 0.0
        self._theme.apply_cover(track.cover_path, track.path)
        self._lyrics.load_for(track.path)
        self._quality.set_track(track)
        self.indexChanged.emit()
        self.trackChanged.emit()
        self.positionChanged.emit()

    def _advance(self, step: int, manual: bool = False) -> None:
        count = self._playlist.rowCount()
        if count == 0:
            return

        if not manual and self._config.repeat == "one":
            self.seekTo(0.0)
            self._engine.play()
            return

        order = self._shuffle_order if self._config.shuffle else list(range(count))
        try:
            position = order.index(self._index)
        except ValueError:
            position = 0

        nxt = position + step
        if nxt >= len(order) or nxt < 0:
            if self._config.repeat == "off" and not manual:
                self._engine.pause()
                self.playingChanged.emit()
                return
            nxt %= len(order)

        self.playIndex(order[nxt])

    def _reshuffle(self) -> None:
        order = list(range(self._playlist.rowCount()))
        random.shuffle(order)
        self._shuffle_order = order

    def _refresh_library(self) -> None:
        groups = group_audio_files(self._config.library_folders)
        self._library_playlists = {
            str(folder): tuple(str(path) for path in paths) for folder, paths in groups.items()
        }
        self.libraryChanged.emit()

    def _on_output_rate(self, rate: int) -> None:
        """輸出端點換取樣率時讓引擎跟上，少一次重取樣。"""
        if self._engine.configure_output(rate):
            self.toast.emit(f"輸出已對齊 {rate / 1000:g} kHz")

    def _tick(self) -> None:
        dt = 1.0 / UI_TICK_HZ
        frame = self._engine.analyzer.tick(dt)
        self._spectrum.apply(frame)
        self._energy = frame.rms
        self._bass = frame.bass
        self.frameAdvanced.emit()
        if frame.onset:
            self.beat.emit()

        position = self._engine.position
        if abs(position - self._position) > 1e-3:
            self._position = position
            self.positionChanged.emit()
            self._lyrics.update_position(position)

        if self._engine.take_finished():
            self._advance(1)

    def _restore(self) -> None:
        if not self._config.playlist:
            return
        self.addPaths(self._config.playlist)
        target = self._config.current_index
        if 0 <= target < self._playlist.rowCount():
            self._load(target)
            if self._config.current_position > 0:
                self.seekTo(self._config.current_position)

    def _persist(self) -> None:
        self._config.playlist = [track.path for track in self._playlist.tracks]
        self._config.current_index = self._index
        self._config.current_position = self._position
        self._config.volume = self._engine.volume
        self._config.muted = self._engine.muted
        save_config(self._config)
