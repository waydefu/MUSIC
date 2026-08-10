"""Build the portable Windows AURORA executable.

The build is driven by ``aurora.spec`` rather than command-line flags.  A spec
file is the only reliable way to keep the bundle small: PySide6's PyInstaller
hook pulls in the entire Qt distribution, and ``--exclude-module`` alone does
not stop the collected DLLs and resource files.  ``aurora.spec`` filters
``a.binaries`` and ``a.datas`` directly after analysis.

Run with ``--verify`` to launch the freshly built executable and confirm it
reaches a running state before shipping it anywhere.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "aurora.spec"
BUNDLE = ROOT / "dist" / "AURORA"

#: Files that must exist in the bundle or the executable will not start.
REQUIRED = (
    "AURORA.exe",
    "_internal/PySide6/Qt6Quick.dll",
    "_internal/PySide6/plugins/platforms/qwindows.dll",
    "_internal/PySide6/qml/QtQuick/qmldir",
    "_internal/PySide6/qml/QtQuick/Effects/qmldir",
    "_internal/PySide6/qml/QtQuick/Particles/qmldir",
    "_internal/aurora/qml/Main.qml",
    "_internal/aurora/qml/Aurora/qmldir",
    "_internal/aurora/qml/Aurora/shaders/poststack.frag.qsb",
    "_internal/data/bt_codecs.toml",
)

#: Globs for files whose exact name varies with the Python ABI tag.
#: miniaudio imports its CFFI extension dynamically, so PyInstaller cannot see
#: it statically - if this one goes missing, playback dies at the first track.
REQUIRED_GLOBS = (
    "_internal/_cffi_backend*.pyd",
    "_internal/_miniaudio*.pyd",
)

#: Anything matching these must NOT be in the bundle - they are the bloat we
#: deliberately strip.  Guarding against their return keeps the build honest.
FORBIDDEN = (
    "Qt6WebEngineCore.dll",
    "QtWebEngineProcess.exe",
    "icudtl.dat",
    "opengl32sw.dll",
    "avcodec-61.dll",
)


def _folder_size_mb(folder: Path) -> float:
    return sum(item.stat().st_size for item in folder.rglob("*") if item.is_file()) / 1024**2


def build() -> int:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def inspect() -> int:
    """Confirm the bundle has what it needs and none of what it should not."""
    if not BUNDLE.is_dir():
        print(f"[error] bundle missing: {BUNDLE}")
        return 1

    failures = 0
    for relative in REQUIRED:
        if not (BUNDLE / relative).exists():
            print(f"[error] required file missing: {relative}")
            failures += 1

    for pattern in REQUIRED_GLOBS:
        if not list(BUNDLE.glob(pattern)):
            print(f"[error] required file missing: {pattern}")
            failures += 1

    for pattern in FORBIDDEN:
        found = list(BUNDLE.rglob(pattern))
        if found:
            size = found[0].stat().st_size / 1024**2
            print(f"[error] excluded file came back: {pattern} ({size:.1f} MB)")
            failures += 1

    size = _folder_size_mb(BUNDLE)
    count = sum(1 for item in BUNDLE.rglob("*") if item.is_file())
    print(f"\nbundle: {size:.0f} MB across {count} files")

    if failures:
        print(f"{failures} bundle check(s) failed")
        return 1
    print("bundle checks passed")
    return 0


def verify_runs(seconds: float = 30.0) -> int:
    """Load the whole QML tree inside the frozen executable.

    ``--validate-qml`` instantiates every controller and loads ``Main.qml``
    with all its imports, then exits.  That exercises exactly what breaks when
    a Qt plugin or QML module was stripped too aggressively, and it reports the
    failure through the exit code instead of a silent crash.
    """
    executable = BUNDLE / "AURORA.exe"
    print(f"\nvalidating QML inside {executable.name} ...")
    process = subprocess.Popen(
        [str(executable), "--validate-qml"],
        cwd=BUNDLE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.25)

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        print("[error] validation did not finish - the executable hung")
        return 1

    output = (process.stdout.read() if process.stdout else "").strip()
    if process.returncode == 0:
        print("QML loaded successfully inside the frozen build")
        return 0

    print(f"[error] executable exited with code {process.returncode}")
    if output:
        print(output)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="launch the build afterwards")
    parser.add_argument("--skip-build", action="store_true", help="only run the checks")
    arguments = parser.parse_args()

    if not arguments.skip_build:
        if BUNDLE.exists():
            shutil.rmtree(BUNDLE, ignore_errors=True)
        code = build()
        if code != 0:
            return code

    code = inspect()
    if code != 0:
        return code

    if arguments.verify:
        return verify_runs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
