import json
from pathlib import Path

from aurora.core.config import Config, WindowGeometry, load_config, save_config


def test_round_trip_preserves_everything(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    original = Config(
        volume=0.42,
        muted=True,
        shuffle=True,
        repeat="one",
        playlist=[r"D:\a.mp3", r"D:\b.flac"],
        current_index=1,
        current_position=87.5,
        library_folders=[r"D:\music"],
        window=WindowGeometry(100, 200, 1400, 900),
        mini_mode=True,
        quality_preset="balanced",
        reduce_motion=True,
        cinema_mode=True,
    )
    assert save_config(original, target)

    loaded = load_config(target)
    assert loaded == original


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.json")
    assert config == Config()
    assert config.volume == 0.8


def test_corrupt_json_returns_defaults_instead_of_raising(tmp_path: Path) -> None:
    """設定檔壞掉絕不能讓播放器開不起來。"""
    target = tmp_path / "config.json"
    target.write_text("{ 這不是合法的 JSON", encoding="utf-8")
    assert load_config(target) == Config()


def test_non_object_json_returns_defaults(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_config(target) == Config()


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"volume": 0.3, "從未存在的欄位": 123}), encoding="utf-8")
    config = load_config(target)
    assert config.volume == 0.3
    assert not hasattr(config, "從未存在的欄位")


def test_out_of_range_values_are_clamped(tmp_path: Path) -> None:
    """設定檔是使用者可編輯的純文字，不能信任裡面的數字。"""
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "volume": 9.9,
                "current_position": -50.0,
                "repeat": "亂填的模式",
                "quality_preset": "ultra",
                "window": {"x": 10, "y": 10, "width": 1, "height": 1},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(target)
    assert config.volume == 1.0
    assert config.current_position == 0.0
    assert config.repeat == "off"
    assert config.quality_preset == "cinematic"
    assert config.window.width >= 720
    assert config.window.height >= 480


def test_current_index_is_clamped_to_playlist(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps({"playlist": [r"D:\one.mp3"], "current_index": 99}), encoding="utf-8"
    )
    assert load_config(target).current_index == 0


def test_index_resets_when_playlist_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"playlist": [], "current_index": 5}), encoding="utf-8")
    assert load_config(target).current_index == -1


def test_non_string_playlist_entries_are_dropped(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps({"playlist": [r"D:\ok.mp3", 42, None, {"a": 1}]}), encoding="utf-8"
    )
    assert load_config(target).playlist == [r"D:\ok.mp3"]


def test_reduce_motion_none_means_follow_system(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    assert save_config(Config(reduce_motion=None), target)
    assert load_config(target).reduce_motion is None


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    assert save_config(Config(), target)
    assert target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "config.json"
    assert save_config(Config(volume=0.5), target)
    assert load_config(target).volume == 0.5


def test_existing_config_is_overwritten_not_appended(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    save_config(Config(volume=0.9), target)
    save_config(Config(volume=0.1), target)
    assert load_config(target).volume == 0.1
    assert json.loads(target.read_text(encoding="utf-8"))["volume"] == 0.1
