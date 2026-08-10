from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from aurora.bridge.models import PlaylistFilterProxy, PlaylistModel
from aurora.core.models import Track


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def test_playlist_filter_matches_title_artist_album_and_path() -> None:
    _app()
    playlist = PlaylistModel()
    playlist.append(
        [
            Track(path="D:/Music/Night Drive.flac", title="Night Drive", artist="AURORA", album="Skies"),
            Track(path="D:/Music/Quiet.wav", title="Quiet", artist="Elsewhere", album="Ambient"),
        ]
    )
    filtered = PlaylistFilterProxy(playlist)

    filtered.set_query("aurora")
    assert filtered.rowCount() == 1
    assert filtered.source_row(0) == 0

    filtered.set_query("ambient")
    assert filtered.rowCount() == 1
    assert filtered.source_row(0) == 1

    filtered.set_query("music/night")
    assert filtered.rowCount() == 1
    assert filtered.source_row(0) == 0
