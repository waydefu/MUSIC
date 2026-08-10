"""Windows 版本與系統動畫偏好。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

#: SystemParametersInfoW 的 SPI_GETCLIENTAREAANIMATION。
#: 使用者在「設定 → 協助工具 → 視覺效果 → 動畫效果」關掉動畫時會變成 False。
_SPI_GET_CLIENT_AREA_ANIMATION = 0x1042


def windows_build() -> int:
    """目前的 Windows 組建號。Windows 11 是 22000 起跳。"""
    version = getattr(sys, "getwindowsversion", None)
    if version is None:
        return 0
    return int(version().build)


def system_animations_enabled() -> bool:
    """讀 Windows 的「動畫效果」系統偏好。

    使用者關掉它就代表不想看到位移類動畫，我們要照做 ——
    Apple HIG 與 Material Design 都把尊重這個設定列為硬性要求。
    讀不到時預設回 ``True``（維持動效），因為多數機器是開著的。
    """
    try:
        enabled = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GET_CLIENT_AREA_ANIMATION,
            0,
            ctypes.byref(enabled),
            0,
        )
    except (OSError, AttributeError):
        return True
    return bool(enabled.value) if ok else True
