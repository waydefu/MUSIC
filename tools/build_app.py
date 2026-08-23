"""Build and verify the personal-use Apple Silicon ``AURORA.app`` bundle.

The macOS build is intentionally separate from the Windows PyInstaller spec.
It creates an onedir app without a Developer ID identity or notarization for
local use; it does not create a DMG, install anything, or register file types.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import runpy
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "aurora-macos.spec"
BUNDLE = ROOT / "dist" / "AURORA.app"
COLLECT = ROOT / "dist" / "AURORA-macos"
EXECUTABLE = BUNDLE / "Contents" / "MacOS" / "AURORA"
RESOURCES = BUNDLE / "Contents" / "Resources"

BUNDLE_IDENTIFIER = "io.github.waydefu.aurora"

# 這些路徑同時覆蓋 Qt Quick 的 native framework、Cocoa platform plugin、
# Qt 自帶 QML 與專案自己的 QML/data。Frameworks 是 frozen runtime 的
# sys._MEIPASS 所在位置；資料在 Resources，PyInstaller 會建立內部 cross-link。
REQUIRED = (
    "Contents/Info.plist",
    "Contents/MacOS/AURORA",
    "Contents/Frameworks/PySide6/Qt/lib/QtQuick.framework/Versions/A/QtQuick",
    "Contents/Frameworks/PySide6/Qt/plugins/platforms/libqcocoa.dylib",
    "Contents/Frameworks/PySide6/Qt/qml/QtQuick/qmldir",
    "Contents/Frameworks/PySide6/Qt/qml/QtQuick/Effects/qmldir",
    "Contents/Frameworks/PySide6/Qt/qml/QtQuick/Particles/qmldir",
    "Contents/Frameworks/aurora/qml/Main.qml",
    "Contents/Frameworks/aurora/qml/Aurora/qmldir",
    "Contents/Frameworks/aurora/qml/Aurora/shaders/poststack.frag.qsb",
    "Contents/Frameworks/data/aurora-icon.png",
    "Contents/Frameworks/data/bt_codecs.toml",
)

REQUIRED_GLOBS = (
    "Contents/Frameworks/_cffi_backend*.so",
    "Contents/Frameworks/_miniaudio*.so",
)

FORBIDDEN = (
    "QtWebEngine*.framework",
    "QtWebEngineProcess.app",
    "QtMultimedia*.framework",
    "QtQuick3D*.framework",
    "QtPdf*.framework",
)

EXPECTED_ADAPTER = "macOS"
_MACHO_64_MAGIC = 0xFEEDFACF
_CPU_TYPE_ARM64 = 0x0100000C


def _version() -> str:
    source = ROOT / "src" / "aurora" / "__init__.py"
    return str(runpy.run_path(source)["__version__"])


def _platform_supported() -> bool:
    if sys.platform != "darwin":
        print("[error] macOS .app 只能在 macOS 上建置與驗證")
        return False
    if platform.machine() != "arm64":
        print(f"[error] 需要 Apple Silicon arm64，目前是 {platform.machine()}")
        return False
    return True


def build() -> int:
    existing = [path for path in (BUNDLE, COLLECT) if path.exists()]
    if existing:
        print("[error] 建置會覆寫既有輸出；依專案安全規則不自動刪除：")
        for path in existing:
            print(f"        {path}")
        print("        請自行移走上述目錄後重試，或用 --skip-build 驗證現有產物。")
        return 1

    # 倉庫常放在 iCloud 同步的桌面。若直接在 dist/ 組 app，File Provider
    # 會在 codesign 尚未完成時替 framework 目錄加回 com.apple.FinderInfo，
    # 造成「resource fork, Finder information ... not allowed」。先在本機
    # /private/tmp 完成 PyInstaller 的 ad-hoc signing，再移回 dist 可避開競態。
    stage = Path(tempfile.mkdtemp(prefix="aurora-macos-dist-", dir="/private/tmp"))
    stage_dist = stage / "dist"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--distpath",
        str(stage_dist),
        "--workpath",
        str(ROOT / "build" / "aurora-macos"),
        str(SPEC),
    ]
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    code = subprocess.run(command, cwd=ROOT, check=False, env=environment).returncode
    if code != 0:
        print(f"[error] PyInstaller staging retained for inspection: {stage}")
        return code

    staged_bundle = stage_dist / BUNDLE.name
    staged_collect = stage_dist / COLLECT.name
    if not staged_bundle.is_dir() or not staged_collect.is_dir():
        print(f"[error] PyInstaller staging output incomplete: {stage_dist}")
        return 1

    code = _verify_adhoc_signature(staged_bundle, strict=True)
    if code != 0:
        print(f"[error] PyInstaller staging retained for inspection: {stage}")
        return code

    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    staged_collect.replace(COLLECT)
    staged_bundle.replace(BUNDLE)
    return _verify_adhoc_signature(BUNDLE, strict=False)


def _verify_adhoc_signature(bundle: Path, *, strict: bool) -> int:
    command = ["codesign", "--verify", "--deep"]
    if strict:
        command.append("--strict")
    command.append(str(bundle))
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        mode = "strict" if strict else "destination"
        print(f"[error] PyInstaller ad-hoc signature verification failed ({mode})")
        if process.stdout.strip():
            print(process.stdout.strip())
        return 1
    mode = "strict staging" if strict else "destination"
    print(f"PyInstaller ad-hoc signature verified ({mode})")
    return 0


def _check_arm64_macho(path: Path) -> bool:
    try:
        magic, cpu_type = struct.unpack("<II", path.read_bytes()[:8])
    except (OSError, struct.error):
        return False
    return magic == _MACHO_64_MAGIC and cpu_type == _CPU_TYPE_ARM64


def _check_internal_symlinks() -> list[str]:
    """回傳 broken 或指向 bundle 外部的 symlink；正常時為空。"""
    failures: list[str] = []
    bundle_root = BUNDLE.resolve()
    for item in BUNDLE.rglob("*"):
        if not item.is_symlink():
            continue
        try:
            target = item.resolve(strict=True)
        except FileNotFoundError:
            failures.append(f"broken symlink: {item.relative_to(BUNDLE)}")
            continue
        if not target.is_relative_to(bundle_root):
            failures.append(
                f"external symlink: {item.relative_to(BUNDLE)} -> {target}"
            )
    return failures


def _folder_size_mb(folder: Path) -> float:
    return sum(
        item.stat().st_size
        for item in folder.rglob("*")
        if item.is_file() and not item.is_symlink()
    ) / 1024**2


def inspect() -> int:
    """檢查 app 具備啟動所需內容，且沒有被排除的 Qt 贅重。"""
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
            print(f"[error] excluded content came back: {pattern}")
            failures += 1

    if not os.access(EXECUTABLE, os.X_OK):
        print("[error] Contents/MacOS/AURORA is not executable")
        failures += 1
    elif not _check_arm64_macho(EXECUTABLE):
        print("[error] Contents/MacOS/AURORA is not an arm64 Mach-O executable")
        failures += 1

    plist_path = BUNDLE / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        print(f"[error] cannot read Info.plist: {error}")
        failures += 1
        info = {}

    expected_version = _version()
    expected_plist = {
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleExecutable": "AURORA",
        "CFBundleShortVersionString": expected_version,
        "CFBundleVersion": expected_version,
    }
    for key, expected in expected_plist.items():
        if info.get(key) != expected:
            print(f"[error] Info.plist {key}={info.get(key)!r}, expected {expected!r}")
            failures += 1

    icon_name = info.get("CFBundleIconFile")
    icon_path = RESOURCES / str(icon_name) if icon_name else None
    if icon_path is None or not icon_path.is_file():
        print(f"[error] bundle icon missing: {icon_name!r}")
        failures += 1
    elif icon_path.read_bytes()[:4] != b"icns":
        print(f"[error] bundle icon is not an ICNS file: {icon_path.name}")
        failures += 1

    for failure in _check_internal_symlinks():
        print(f"[error] {failure}")
        failures += 1

    size = _folder_size_mb(BUNDLE)
    count = sum(
        1
        for item in BUNDLE.rglob("*")
        if item.is_file() and not item.is_symlink()
    )
    print(f"\nbundle: {size:.0f} MB across {count} physical files")

    if failures:
        print(f"{failures} bundle check(s) failed")
        return 1
    print("bundle checks passed (arm64, resources, icon, internal symlinks)")
    return 0


def _verify_platform_adapter(output: str) -> int:
    marker = "platform adapter:"
    line = next((line for line in output.splitlines() if line.startswith(marker)), None)
    if line is None:
        print(f"[error] frozen app did not report '{marker}'")
        return 1
    name = line[len(marker) :].strip()
    if name != EXPECTED_ADAPTER:
        print(f"[error] platform adapter is {name!r}, expected {EXPECTED_ADAPTER!r}")
        return 1
    print(f"platform adapter resolved to {name}")
    return 0


def verify_runs(seconds: float = 30.0) -> int:
    """在 frozen arm64 executable 中離屏載入完整 QML tree。"""
    print(f"\nvalidating QML inside {BUNDLE.name} ...")
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        process = subprocess.run(
            [str(EXECUTABLE), "--validate-qml"],
            cwd=BUNDLE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=seconds,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        print("[error] validation did not finish - the app hung")
        return 1

    output = process.stdout.strip()
    if process.returncode != 0:
        print(f"[error] frozen app exited with code {process.returncode}")
        if output:
            print(output)
        return 1

    print("QML loaded successfully inside the frozen app")
    return _verify_platform_adapter(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="建置後在 bundle 內驗證 QML")
    parser.add_argument("--skip-build", action="store_true", help="只檢查現有 bundle")
    arguments = parser.parse_args()

    if not _platform_supported():
        return 1

    if not arguments.skip_build:
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
