"""Build the portable Windows AURORA executable.

PyInstaller cannot statically discover miniaudio's CFFI extension because the
library imports it dynamically.  Keep it as an explicit hidden import so a
clean build always contains ``_cffi_backend``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    separator = os.pathsep
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "AURORA",
        "--icon",
        str(ROOT / "data" / "aurora-icon.ico"),
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        f"{ROOT / 'data'}{separator}data",
        "--add-data",
        f"{ROOT / 'src' / 'aurora' / 'qml'}{separator}aurora/qml",
        "--collect-data",
        "PySide6",
        "--collect-all",
        "miniaudio",
        "--hidden-import",
        "_cffi_backend",
        str(ROOT / "src" / "aurora" / "__main__.py"),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
