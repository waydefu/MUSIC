"""Shared PyInstaller build-log policy for AURORA packaging gates.

The goal is not to hide warnings.  A successful frozen build may only contain
warnings that we have deliberately reviewed and bounded.  Any new PyInstaller
WARNING turns the build into a failure so packaging regressions cannot be lost
inside an otherwise-green job.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

_KNOWN_PYSIDE_VERSION = "6.11.1"
_ASSETDOWNLOADER_WARNING = re.compile(
    r"QtLibraryInfo\(PySide6\): QML plugin binary .*[\\/]Qt[\\/]labs[\\/]"
    r"assetdownloader[\\/](?:lib)?qmlassetdownloaderprivateplugin\.(?:dll|dylib) "
    r"does not exist!"
)


def _project_uses_assetdownloader(qml_root: Path) -> bool:
    marker = "Qt.labs.assetdownloader"
    for path in qml_root.rglob("*.qml"):
        try:
            if marker in path.read_text(encoding="utf-8"):
                return True
        except OSError:
            # A disappearing source tree is a build failure elsewhere; do not make
            # the warning allowlist more permissive because inspection failed.
            return True
    return False


def warning_is_allowlisted(
    line: str,
    *,
    pyside_version: str,
    qml_root: Path,
) -> bool:
    """Return True only for the reviewed PySide6 6.11.1 assetdownloader quirk.

    The 6.11.1 wheel has a Qt.labs.assetdownloader qmldir entry whose dynamic
    plugin is absent. AURORA does not import that QML module. The exception is
    deliberately version-locked: after PySide6 changes, the warning must be
    reviewed again instead of being silently grandfathered forever.
    """
    return (
        pyside_version == _KNOWN_PYSIDE_VERSION
        and _ASSETDOWNLOADER_WARNING.search(line) is not None
        and not _project_uses_assetdownloader(qml_root)
    )


def run_pyinstaller(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    qml_root: Path,
    pyside_version: str,
) -> int:
    """Run PyInstaller live and fail a successful build on unexpected warnings."""
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    unexpected: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip("\r\n")
        if "WARNING:" not in line:
            print(line)
            continue
        if warning_is_allowlisted(
            line,
            pyside_version=pyside_version,
            qml_root=qml_root,
        ):
            # Keep the evidence visible without presenting a reviewed upstream
            # quirk as an untriaged warning in the CI log.
            print(line.replace("WARNING:", "KNOWN-UPSTREAM:", 1))
            continue
        unexpected.append(line)
        print(line)

    code = process.wait()
    if code != 0:
        return code
    if unexpected:
        print("\n[error] PyInstaller emitted unexpected warning(s):")
        for line in unexpected:
            print(f"        {line}")
        print("        Review/fix them or add a narrowly-scoped, evidenced exception.")
        return 1
    return 0
