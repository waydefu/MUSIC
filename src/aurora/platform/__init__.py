"""平台 adapter 的選擇器。

上層一律透過 :func:`adapter` 取得平台能力，不直接 import ``platform_win``
或任何其他平台套件。依賴方向是 ``qml → bridge → audio/library/platform → core``。

**這個套件叫 ``platform`` 不會蓋掉標準函式庫的 ``platform``。**
Python 3 只用絕對匯入，模組內寫 ``import platform`` 拿到的仍是標準函式庫，
只有 ``from aurora.platform import ...`` 才會拿到這裡。

平台專屬實作是**在函式內**才 import 的，因為 ``platform_win`` 於模組層級
就 import ``winreg`` 與 ``ctypes.wintypes`` —— 在 macOS 上光是 import 就會炸。

打包時要留意：這條路徑一旦沒被收進 bundle，:func:`adapter` 會**安靜地**
退回 :class:`~aurora.platform.base.NullAdapter` —— 程式照常啟動、QML 照常
載入、exit code 照樣是 0，只有音質面板變成一片「未知」。
守門的是 ``tools/build_exe.py`` 的 ``_verify_platform_adapter()``，
它比對 ``--validate-qml`` 印出的 adapter 名稱；光看 exit code 抓不到。
"""

from __future__ import annotations

import sys

from aurora.platform.base import NullAdapter, PlatformAdapter

_cached: PlatformAdapter | None = None


def adapter() -> PlatformAdapter:
    """目前平台的 adapter。第一次呼叫時決定，之後沿用同一個實例。"""
    global _cached
    if _cached is None:
        _cached = _select()
    return _cached


def _select() -> PlatformAdapter:
    if sys.platform == "win32":
        from aurora.platform.windows import WindowsAdapter

        return WindowsAdapter()
    if sys.platform == "darwin":
        from aurora.platform.macos import MacOSAdapter

        return MacOSAdapter()
    return NullAdapter()


def reset_cache() -> None:
    """丟掉快取的 adapter。只給測試用。"""
    global _cached
    _cached = None


__all__ = ["NullAdapter", "PlatformAdapter", "adapter", "reset_cache"]
