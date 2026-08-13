"""播放清單延遲載入的回歸測試。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

import aurora.bridge.player as player_module
from aurora.bridge.player import PlayerController
from aurora.core.config import Config
from aurora.library.store import LibraryCache


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _controller(monkeypatch: object) -> PlayerController:
    _app()
    monkeypatch.setattr(LibraryCache, "load", lambda self: False)  # type: ignore[attr-defined]
    return PlayerController(Config())


def _close(controller: PlayerController) -> None:
    controller._timer.stop()
    controller._cache_save_timer.stop()
    controller._metadata_start_timer.stop()
    controller._metadata_loader.close()
    controller._engine.close()


def test_restore_uses_stubs_without_sync_metadata(
    monkeypatch: object, generated_dir: Path
) -> None:
    controller = _controller(monkeypatch)
    paths = [str(generated_dir / name) for name in ("test_320k.mp3", "test.flac", "test.ogg")]
    controller._config.playlist = paths
    reads: list[str] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        player_module,
        "read_track",
        lambda path: reads.append(str(path)) or None,
    )
    try:
        controller._restore(resume=False)
        assert controller.playlist.rowCount() == len(paths)
        assert reads == []
    finally:
        _close(controller)


def test_external_open_loads_empty_playlist_only_once(
    monkeypatch: object, generated_dir: Path
) -> None:
    controller = _controller(monkeypatch)
    loads: list[str] = []
    source = str(generated_dir / "test.flac")
    monkeypatch.setattr(  # type: ignore[attr-defined]
        controller._engine,
        "load",
        lambda path, duration=0.0: loads.append(path) or True,
    )
    monkeypatch.setattr(controller._engine, "play", lambda: True)  # type: ignore[attr-defined]
    try:
        controller.openPaths([source])
        assert controller.playlist.rowCount() == 1
        assert loads == [source]
    finally:
        _close(controller)
