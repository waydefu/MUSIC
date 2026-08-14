"""Build the distributable release archive.

The archive contains the frozen application plus the install/uninstall
scripts, so a fresh machine only needs to extract it and double-click
``安裝.bat``.  Nothing else has to be present - no Python, no Qt, no VC++
redistributable.

Run with ``--skip-build`` to repackage an existing ``dist/AURORA`` folder.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurora import __version__


def _configure_output() -> None:
    """讓 redirect／CI 下的中文發行日誌不受 Windows ANSI code page 限制。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


_configure_output()

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "AURORA"
PACKAGING = ROOT / "packaging"
STAGE = ROOT / "dist" / "release-stage"

#: Files copied next to the application folder inside the archive.
INSTALLER_FILES = ("install.ps1", "uninstall.ps1", "安裝.bat", "README.txt")


def build() -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_exe.py"), "--verify"],
        cwd=ROOT,
        check=False,
    ).returncode


def check_powershell_encoding() -> int:
    """PowerShell 5.1 沒有 BOM 就用系統 ANSI 代碼頁讀 .ps1。

    在繁體中文 Windows 上那是 cp950，腳本裡的中文會變成亂碼並讓解析器
    直接失敗 —— 使用者看到的是一整頁 "Unexpected token" 而不是安裝畫面。
    這個檢查擋住的就是這件事：實測過，少了 BOM 安裝腳本 100% 跑不起來。
    """
    failures = 0
    for name in INSTALLER_FILES:
        source = PACKAGING / name
        if source.suffix.lower() != ".ps1" or not source.exists():
            continue
        if not source.read_bytes().startswith(b"\xef\xbb\xbf"):
            print(f"  [error] {name} 缺少 UTF-8 BOM，PowerShell 5.1 會解析失敗")
            failures += 1
    return failures


def stage() -> Path:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copytree(BUNDLE, STAGE / "AURORA")
    for name in INSTALLER_FILES:
        source = PACKAGING / name
        if source.exists():
            shutil.copy2(source, STAGE / name)
    shutil.copy2(ROOT / "LICENSE", STAGE / "LICENSE.txt")
    return STAGE


def archive(stage_dir: Path) -> Path:
    target = ROOT / "dist" / f"AURORA-{__version__}-windows-x64.zip"
    target.unlink(missing_ok=True)

    files = sorted(item for item in stage_dir.rglob("*") if item.is_file())
    print(f"壓縮 {len(files)} 個檔案…")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for item in files:
            bundle.write(item, item.relative_to(stage_dir))
    return target


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path) -> int:
    """Confirm the archive really contains everything a fresh machine needs."""
    required = (
        "安裝.bat",
        "install.ps1",
        "uninstall.ps1",
        "LICENSE.txt",
        "AURORA/AURORA.exe",
        "AURORA/_internal/PySide6/Qt6Quick.dll",
        "AURORA/_internal/PySide6/plugins/platforms/qwindows.dll",
        "AURORA/_internal/aurora/qml/Main.qml",
        "AURORA/_internal/aurora/qml/Aurora/shaders/poststack.frag.qsb",
        "AURORA/_internal/data/bt_codecs.toml",
    )
    prefixes = ("AURORA/_internal/_cffi_backend", "AURORA/_internal/_miniaudio")

    with zipfile.ZipFile(path) as bundle:
        names = set(bundle.namelist())

    missing = [name for name in required if name not in names]
    for prefix in prefixes:
        if not any(name.startswith(prefix) for name in names):
            missing.append(prefix + "*")

    if missing:
        for name in missing:
            print(f"  [error] 壓縮檔缺少 {name}")
        return 1
    print(f"  壓縮檔內容檢查通過（{len(names)} 個項目）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    options = parser.parse_args()

    if not options.skip_build:
        code = build()
        if code != 0:
            return code

    if not BUNDLE.is_dir():
        print(f"找不到建置產物：{BUNDLE}")
        return 1

    if check_powershell_encoding() != 0:
        return 1

    stage_dir = stage()
    target = archive(stage_dir)
    shutil.rmtree(stage_dir, ignore_errors=True)

    if verify(target) != 0:
        return 1

    size_mb = target.stat().st_size / 1024**2
    digest = checksum(target)
    print(f"\n{target.name}")
    print(f"  大小   {size_mb:.0f} MB")
    print(f"  SHA256 {digest}")
    (target.with_suffix(".zip.sha256")).write_text(
        f"{digest}  {target.name}\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
