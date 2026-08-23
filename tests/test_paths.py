"""跨平台的使用者資料路徑測試。"""

from __future__ import annotations

from pathlib import Path

import pytest

import aurora.core.paths as paths

ROOT = Path(__file__).resolve().parents[1]


def _set_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """隔離 Path.home，避免測試碰到開發者真正的使用者資料夾。"""
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda _cls: home))


def test_app_data_dir_uses_macos_application_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(paths.sys, "platform", "darwin")

    directory = paths.app_data_dir()

    assert directory == tmp_path / "Library" / "Application Support" / "Aurora"
    assert directory.is_dir()


def test_app_data_dir_preserves_windows_appdata_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    appdata = tmp_path / "Roaming"
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))

    directory = paths.app_data_dir()

    assert directory == appdata / "Aurora"
    assert directory.is_dir()


def test_app_data_dir_keeps_windows_fallback_without_appdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)

    assert paths.app_data_dir() == tmp_path / "AppData" / "Roaming" / "Aurora"


def test_frozen_resource_paths_use_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    meipass = tmp_path / "AURORA.app" / "Contents" / "Frameworks"
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(meipass), raising=False)

    assert paths.is_frozen()
    assert paths.resource_root() == meipass
    assert paths.data_file("bt_codecs.toml") == meipass / "data" / "bt_codecs.toml"
    assert paths.qml_root() == meipass / "aurora" / "qml"


def test_non_frozen_resource_paths_use_source_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    assert not paths.is_frozen()
    assert paths.resource_root() == ROOT
    assert paths.data_file("bt_codecs.toml") == ROOT / "data" / "bt_codecs.toml"
    assert paths.qml_root() == ROOT / "src" / "aurora" / "qml"
