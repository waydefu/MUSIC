from pathlib import Path

from pyinstaller_gate import warning_is_allowlisted


def _qml_root(tmp_path: Path, content: str = "import QtQuick\nItem {}\n") -> Path:
    root = tmp_path / "qml"
    root.mkdir()
    (root / "Main.qml").write_text(content, encoding="utf-8")
    return root


def test_known_pyside_assetdownloader_warning_is_narrowly_allowlisted(tmp_path: Path) -> None:
    qml_root = _qml_root(tmp_path)
    windows = (
        "123 WARNING: QtLibraryInfo(PySide6): QML plugin binary "
        "'C:\\venv\\PySide6\\qml\\Qt\\labs\\assetdownloader\\"
        "qmlassetdownloaderprivateplugin.dll' does not exist!"
    )
    macos = (
        "123 WARNING: QtLibraryInfo(PySide6): QML plugin binary "
        "'/venv/PySide6/Qt/qml/Qt/labs/assetdownloader/"
        "libqmlassetdownloaderprivateplugin.dylib' does not exist!"
    )

    assert warning_is_allowlisted(windows, pyside_version="6.11.1", qml_root=qml_root)
    assert warning_is_allowlisted(macos, pyside_version="6.11.1", qml_root=qml_root)


def test_assetdownloader_exception_expires_when_pyside_changes(tmp_path: Path) -> None:
    qml_root = _qml_root(tmp_path)
    warning = (
        "123 WARNING: QtLibraryInfo(PySide6): QML plugin binary "
        "'/venv/PySide6/Qt/qml/Qt/labs/assetdownloader/"
        "libqmlassetdownloaderprivateplugin.dylib' does not exist!"
    )

    assert not warning_is_allowlisted(warning, pyside_version="6.11.2", qml_root=qml_root)


def test_assetdownloader_warning_is_fatal_if_aurora_starts_using_it(tmp_path: Path) -> None:
    qml_root = _qml_root(tmp_path, "import Qt.labs.assetdownloader\nItem {}\n")
    warning = (
        "123 WARNING: QtLibraryInfo(PySide6): QML plugin binary "
        "'/venv/PySide6/Qt/qml/Qt/labs/assetdownloader/"
        "libqmlassetdownloaderprivateplugin.dylib' does not exist!"
    )

    assert not warning_is_allowlisted(warning, pyside_version="6.11.1", qml_root=qml_root)


def test_unrelated_pyinstaller_warning_is_never_allowlisted(tmp_path: Path) -> None:
    qml_root = _qml_root(tmp_path)

    assert not warning_is_allowlisted(
        "123 WARNING: Library important.dll required via ctypes not found",
        pyside_version="6.11.1",
        qml_root=qml_root,
    )
