"""平台縫的守門測試。

這個檔案守的不是功能，是**結構**。兩件事：

1. 每個 adapter 都滿足契約，而且 macOS 的那個在**任何**平台都 import 得起來。
2. 上層沒有繞過契約直接去碰 ``platform_win``。

第二條特別重要。維護者在 Windows、另一位開發者在 macOS，兩人都無法在本機
驗證對方的平台；只要有人在 ``bridge/`` 裡多寫一行 ``import platform_win``，
macOS 就會回到「連 import 都過不了」的狀態，而寫的人自己看不見。
這條測試就是那道機器可判定的圍籬（PROJECT_PLAN.md §3.3 的第 2 條規則）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from aurora.platform import PlatformAdapter, adapter, reset_cache
from aurora.platform.base import NullAdapter
from aurora.platform.macos import MacOSAdapter

ROOT = Path(__file__).resolve().parents[1]

#: 契約上的全部成員。硬寫出來而不是自動推導 —— 這樣新增方法時
#: 會強迫你回來這裡確認每個 adapter 都跟上了。
CONTRACT = (
    "name",
    "system_animations_enabled",
    "query_endpoints",
    "host_context",
    "register_file_types",
    "unregister_file_types",
    "is_registered",
    "open_default_apps_settings",
)


def _adapter_classes() -> list[type]:
    """所有 adapter 實作。Windows 的只在 Windows 上載入得了。"""
    classes: list[type] = [NullAdapter, MacOSAdapter]
    if sys.platform == "win32":
        from aurora.platform.windows import WindowsAdapter

        classes.append(WindowsAdapter)
    return classes


# ------------------------------------------------------------------ 契約


@pytest.mark.parametrize("cls", _adapter_classes(), ids=lambda c: c.__name__)
def test_adapter_satisfies_contract(cls: type) -> None:
    instance = cls()
    for member in CONTRACT:
        assert hasattr(instance, member), f"{cls.__name__} 少了 {member}"
    assert isinstance(instance, PlatformAdapter)


def test_macos_adapter_imports_on_every_platform() -> None:
    """macOS adapter 不得在模組層級 import 平台專屬東西。

    ``platform_win`` 就是踩了這個坑（模組層級 import ``winreg``），
    才害得整個 ``bridge/quality.py`` 在 macOS 上連 import 都過不了。
    這條測試在 Windows 的 CI 上跑，確保 macOS 那邊不會重演同一件事。
    """
    assert MacOSAdapter().name == "macOS"


def test_null_adapter_never_raises() -> None:
    """降級基準的每個方法都要能安全呼叫。

    「查不到裝置資訊絕不能讓播放中斷」是 ``platform_win/`` 既有的原則，
    契約層要繼續守住。
    """
    from aurora.core.btcodec import default_table

    null = NullAdapter()
    assert null.system_animations_enabled() is True
    assert null.query_endpoints().default is None
    assert null.host_context(default_table()).windows_build == 0
    assert null.register_file_types() is False
    assert null.unregister_file_types() is False
    assert null.is_registered() is False
    assert null.open_default_apps_settings() is False


def test_adapter_is_cached() -> None:
    reset_cache()
    first = adapter()
    assert adapter() is first
    reset_cache()


# ------------------------------------------------------------------ 圍籬


def _upper_layer_files() -> list[Path]:
    """契約之上的那幾層。這些檔案不准直接碰 ``platform_win``。"""
    files = sorted((ROOT / "src" / "aurora" / "bridge").glob("*.py"))
    files.append(ROOT / "src" / "aurora" / "__main__.py")
    return files


@pytest.mark.parametrize("path", _upper_layer_files(), ids=lambda p: p.name)
def test_upper_layers_do_not_import_platform_win(path: Path) -> None:
    """只有 ``platform/windows.py`` 可以 import ``platform_win``。

    繞過契約在 Windows 上完全正常，所以本機測試抓不到 —— 只有這條
    靜態檢查會。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.startswith("aurora.platform_win")]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "aurora.platform_win"
        ):
            offenders.append(node.module or "")
    assert not offenders, (
        f"{path.name} 直接 import 了 {offenders}；"
        "請改走 aurora.platform.adapter()，否則 macOS 會連 import 都過不了。"
    )
