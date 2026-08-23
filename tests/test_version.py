"""版本號的單一真相來源，以及它那兩份不得不存在的副本。

AGENTS.md 說版本的真相來源是 ``src/aurora/__init__.py``。那句話對，但不完整
—— 實際上有兩個地方**沒辦法**從那裡讀：

* ``pyproject.toml`` —— 打包工具在 import 之前就要知道版本。
* ``packaging/install.ps1`` —— 它在使用者的機器上執行，那裡沒有 Python，
  而它寫進登錄檔的解除安裝版本會直接顯示在「應用程式與功能」裡。

副本本身無法避免，能避免的是**它們默默走鐘**。0.1.0 那次就走鐘了：
`__version__` 是唯一被記得要改的地方，另外兩份沒人看管。所以改成由這裡
釘住三者相等 —— 這條在 CI 上跑，而 `make_release.py` 的檢查不會。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import aurora

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = ROOT / "packaging" / "install.ps1"


def test_pyproject_version_matches_the_package() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    assert pyproject["project"]["version"] == aurora.__version__


def test_installer_version_matches_the_package() -> None:
    """對不上的話，使用者在「應用程式與功能」裡看到的是錯的版本。

    那種錯特別難查：程式本身顯示新版，作業系統顯示舊版，而回報 bug 的人
    通常是看後者。
    """
    text = INSTALL_PS1.read_text(encoding="utf-8-sig")
    match = re.search(r"\$version\s*=\s*'([^']+)'", text)
    assert match is not None, "install.ps1 裡找不到 $version"
    assert match.group(1) == aurora.__version__


def test_install_scripts_keep_their_utf8_bom() -> None:
    """PowerShell 5.1 沒有 BOM 就用系統 ANSI 代碼頁（繁中是 cp950）讀 .ps1。

    實測過：少了 BOM 安裝腳本 100% 解析失敗，使用者看到的是整頁
    "Unexpected token" 而不是安裝畫面（AGENTS.md 不變量 8）。

    ``make_release.py`` 也擋這件事，但那支只在發行時跑。這條在 CI 上跑，
    所以「改了 .ps1 卻用錯編碼存檔」當下就會紅，不必等到要發行才發現。
    """
    scripts = sorted((ROOT / "packaging").glob("*.ps1"))
    assert scripts, "packaging/ 裡找不到任何 .ps1"
    for script in scripts:
        assert script.read_bytes().startswith(b"\xef\xbb\xbf"), f"{script.name} 缺少 UTF-8 BOM"
