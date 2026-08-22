"""音樂庫層測試。素材由 tools/make_test_audio.py 產生，含三種容器的封面。"""

from __future__ import annotations

import json
import shutil
import time
import unicodedata
from pathlib import Path

import pytest

from aurora.bridge.metadata_loader import MetadataLoader
from aurora.core.lrc import parse_lrc
from aurora.core.models import Track
from aurora.library.metadata import read_lyrics_text, read_track, read_track_stub
from aurora.library.scanner import group_audio_files, iter_audio_files, scan
from aurora.library.store import LibraryCache, _cache_key

# ------------------------------------------------------------------ 標籤


def test_track_stub_does_not_parse_tags_or_cover(generated_dir: Path) -> None:
    source = generated_dir / "test_320k.mp3"
    stub = read_track_stub(source)

    assert stub is not None
    assert stub.title == "test_320k"
    assert stub.artist == ""
    assert stub.duration_sec == 0.0
    assert stub.cover_path is None
    assert stub.size == source.stat().st_size


def test_metadata_loader_returns_full_tracks_in_background(generated_dir: Path) -> None:
    paths = [str(generated_dir / name) for name in ("test_320k.mp3", "test.flac", "test.ogg")]
    loader = MetadataLoader(batch_size=2)
    ready = []
    try:
        loader.request(paths)
        deadline = time.monotonic() + 5.0
        while len(ready) < len(paths) and time.monotonic() < deadline:
            ready.extend(loader.take_ready())
            time.sleep(0.01)
    finally:
        loader.close()

    assert {track.path for track in ready} == set(paths)
    assert all(track.title == "測試曲目" for track in ready)
    assert all(track.duration_sec > 0 for track in ready)


@pytest.mark.parametrize(
    "name", ["test_320k.mp3", "test_128k.mp3", "test.flac", "test.ogg", "fake_lossless.flac"]
)
def test_reads_tags_from_every_container(generated_dir: Path, name: str) -> None:
    track = read_track(generated_dir / name)
    assert track is not None
    assert track.title == "測試曲目"
    assert track.artist == "AURORA 測試"
    assert track.album == "語料庫"


def test_reads_cover_from_every_container(generated_dir: Path) -> None:
    """MP3 的 APIC、FLAC 的 Picture block、OGG 的 base64 欄位是三條路徑。"""
    for name in ("test_320k.mp3", "test.flac", "test.ogg"):
        track = read_track(generated_dir / name)
        assert track is not None, name
        assert track.cover_path is not None, f"{name} 沒讀到封面"
        data = Path(track.cover_path).read_bytes()
        assert data.startswith(b"\x89PNG"), f"{name} 的封面不是有效 PNG"


def test_identical_covers_are_stored_once(generated_dir: Path) -> None:
    mp3 = read_track(generated_dir / "test_320k.mp3")
    flac = read_track(generated_dir / "test.flac")
    assert mp3 is not None and flac is not None
    assert mp3.cover_path == flac.cover_path


def test_duration_and_format(generated_dir: Path) -> None:
    track = read_track(generated_dir / "test.flac")
    assert track is not None
    assert track.duration_sec == pytest.approx(12.0, abs=0.1)
    assert track.fmt is not None
    assert track.fmt.sample_rate == 44100
    assert track.fmt.channels == 2


def test_lossless_flag_follows_container(generated_dir: Path) -> None:
    assert read_track(generated_dir / "test.flac").lossless  # type: ignore[union-attr]
    assert read_track(generated_dir / "test.wav").lossless  # type: ignore[union-attr]
    assert not read_track(generated_dir / "test_320k.mp3").lossless  # type: ignore[union-attr]
    # 假無損：容器確實是無損，判定要靠頻譜分析而不是副檔名
    assert read_track(generated_dir / "fake_lossless.flac").lossless  # type: ignore[union-attr]


def test_bitrate_is_reported(generated_dir: Path) -> None:
    mp3 = read_track(generated_dir / "test_128k.mp3")
    assert mp3 is not None
    assert mp3.bitrate_kbps == pytest.approx(128, abs=8)


def test_lossless_bitrate_is_computed_from_size(generated_dir: Path) -> None:
    flac = read_track(generated_dir / "test.flac")
    assert flac is not None
    assert flac.bitrate_kbps is not None and flac.bitrate_kbps > 400


def test_untagged_file_still_yields_a_track(tmp_path: Path, generated_dir: Path) -> None:
    """讀不到標籤不該讓檔案從音樂庫消失，用檔名當標題就好。"""
    target = tmp_path / "沒有標籤的歌.wav"
    shutil.copy2(generated_dir / "test.wav", target)
    track = read_track(target)
    assert track is not None
    assert track.title == "沒有標籤的歌"


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_track(tmp_path / "nope.mp3") is None


def test_corrupt_file_returns_none_or_minimal(tmp_path: Path) -> None:
    target = tmp_path / "壞掉.mp3"
    target.write_bytes(b"this is definitely not an mp3")
    track = read_track(target)
    assert track is None or track.title == "壞掉"


# ------------------------------------------------------------------ 歌詞


def test_reads_sidecar_lrc(generated_dir: Path) -> None:
    text = read_lyrics_text(generated_dir / "test_320k.mp3")
    assert "第一句歌詞" in text
    lyrics = parse_lrc(text)
    assert len(lyrics.lines) == 5
    assert lyrics.has_word_timing


def test_missing_lyrics_returns_empty(generated_dir: Path) -> None:
    assert read_lyrics_text(generated_dir / "test_128k.mp3") == ""


# ------------------------------------------------------------------ 掃描


def test_scanner_finds_every_supported_file(generated_dir: Path) -> None:
    found = {path.name for path in iter_audio_files([str(generated_dir)])}
    assert {"test.wav", "test.flac", "test.ogg", "test_128k.mp3", "test_320k.mp3"} <= found
    assert not any(name.endswith((".png", ".lrc")) for name in found)


def test_scanner_recurses_into_subdirectories(tmp_path: Path, generated_dir: Path) -> None:
    deep = tmp_path / "專輯" / "2026" / "disc 1"
    deep.mkdir(parents=True)
    shutil.copy2(generated_dir / "test.flac", deep / "歌.flac")
    assert [path.name for path in iter_audio_files([str(tmp_path)])] == ["歌.flac"]


def test_subfolders_become_independent_playlists(tmp_path: Path, generated_dir: Path) -> None:
    first = tmp_path / "專輯 A"
    second = tmp_path / "專輯 B"
    first.mkdir()
    second.mkdir()
    shutil.copy2(generated_dir / "test.flac", first / "第一首.flac")
    shutil.copy2(generated_dir / "test_320k.mp3", second / "第二首.mp3")

    groups = group_audio_files([str(tmp_path)])

    assert {folder.name for folder in groups} == {"專輯 A", "專輯 B"}
    assert [path.name for path in groups[first]] == ["第一首.flac"]
    assert [path.name for path in groups[second]] == ["第二首.mp3"]


def test_scanner_skips_unreadable_roots(tmp_path: Path) -> None:
    assert list(iter_audio_files([str(tmp_path / "不存在")])) == []


def test_scan_yields_batches_then_a_final_done(generated_dir: Path) -> None:
    progress = list(scan([str(generated_dir)], batch_size=2))
    assert progress[-1].done
    assert not any(item.done for item in progress[:-1])

    collected = [track for item in progress for track in item.batch]
    assert len(collected) >= 5
    assert progress[-1].added == len(collected)


def test_scan_reports_running_totals(generated_dir: Path) -> None:
    final = list(scan([str(generated_dir)]))[-1]
    assert final.scanned >= final.added > 0


# ------------------------------------------------------------------ 快取


def test_cache_round_trip(tmp_path: Path, generated_dir: Path) -> None:
    target = tmp_path / "library.json"
    cache = LibraryCache()
    track = read_track(generated_dir / "test.flac")
    assert track is not None
    cache.put(track)
    assert cache.save(target)
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 2

    reloaded = LibraryCache()
    assert reloaded.load(target)
    assert len(reloaded) == 1
    assert reloaded.tracks[0] == track


def test_cache_schema_v2_round_trip(tmp_path: Path) -> None:
    """新版快取可獨立於音訊測試素材完成寫入與還原。"""
    source = tmp_path / "Beyonc\N{LATIN SMALL LETTER E WITH ACUTE}.flac"
    source.write_bytes(b"cached metadata")
    stat = source.stat()
    track = Track(
        path=str(source),
        title="Beyonc\N{LATIN SMALL LETTER E WITH ACUTE}",
        mtime=stat.st_mtime,
        size=stat.st_size,
    )
    target = tmp_path / "library.json"

    cache = LibraryCache()
    cache.put(track)
    assert cache.save(target)
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 2

    reloaded = LibraryCache()
    assert reloaded.load(target)
    assert reloaded.get(source) == track


def test_cache_hit_avoids_rereading(tmp_path: Path, generated_dir: Path) -> None:
    source = generated_dir / "test.flac"
    cache = LibraryCache()
    first = read_track(source)
    assert first is not None
    cache.put(first)
    assert cache.get(source) == first


def test_cache_misses_when_file_changes(tmp_path: Path, generated_dir: Path) -> None:
    """mtime 或大小變了就該重讀，否則改過標籤的檔案會顯示舊資料。"""
    target = tmp_path / "歌.flac"
    shutil.copy2(generated_dir / "test.flac", target)

    cache = LibraryCache()
    track = read_track(target)
    assert track is not None
    cache.put(track)
    assert cache.get(target) is not None

    target.write_bytes(target.read_bytes() + b"\x00" * 64)
    assert cache.get(target) is None


def test_corrupt_cache_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "library.json"
    target.write_text("{ 壞掉的 JSON", encoding="utf-8")
    cache = LibraryCache()
    assert not cache.load(target)
    assert len(cache) == 0


def test_cache_from_a_different_schema_version_is_discarded(tmp_path: Path) -> None:
    target = tmp_path / "library.json"
    target.write_text('{"version": 999, "tracks": {}}', encoding="utf-8")
    assert not LibraryCache().load(target)


def test_cache_from_schema_v1_is_discarded_after_path_key_normalization(tmp_path: Path) -> None:
    """v1 的 NFD 路徑鍵可能和 Windows 的 NFC 鍵不同，必須整份安全淘汰。"""
    target = tmp_path / "library.json"
    target.write_text('{"version": 1, "tracks": {}}', encoding="utf-8")
    assert not LibraryCache().load(target)


def test_cache_key_treats_nfc_and_nfd_paths_as_the_same_path() -> None:
    """APFS 的 NFD 路徑不能讓跨平台共用快取無故失效。"""
    nfc_path = Path("/Music/Beyonc\N{LATIN SMALL LETTER E WITH ACUTE}.flac")
    nfd_path = Path(unicodedata.normalize("NFD", str(nfc_path)))

    assert _cache_key(nfc_path, 1234.5, 678) == _cache_key(nfd_path, 1234.5, 678)


def test_prune_removes_vanished_files(tmp_path: Path, generated_dir: Path) -> None:
    target = tmp_path / "暫時.flac"
    shutil.copy2(generated_dir / "test.flac", target)
    cache = LibraryCache()
    track = read_track(target)
    assert track is not None
    cache.put(track)

    target.unlink()
    assert cache.prune_missing() == 1
    assert len(cache) == 0


def test_scan_populates_the_cache(tmp_path: Path, generated_dir: Path) -> None:
    cache = LibraryCache()
    list(scan([str(generated_dir)], cache))
    assert len(cache) >= 5
