"""平台 adapter 的契約，以及一個「什麼都查不到」的基準實作。

上層（``bridge/``、``__main__.py``）只認識這裡的 :class:`PlatformAdapter`，
不直接 import 任何平台套件。這條線是 macOS 能不能在不重寫演算法的前提下
加進來的關鍵。

**契約的型別必須全部中立。** 回傳 :class:`~aurora.core.models.EndpointSnapshot`
與 :class:`~aurora.core.btcodec.HostContext` 這種住在 ``core/`` 的值物件；
一旦有任何一個方法回傳 ``platform_win`` 裡的型別，抽象層就反過來依賴了
Windows，這個縫就白開了。

:class:`NullAdapter` 是所有 adapter 的降級基準：每個方法都回「查不到」或
「做不到」，而且**不拋例外**。新平台從繼承它開始，一次實作一個方法，
沒實作的部分自動降級 —— UI 顯示「未知裝置」，而不是崩潰。
這與 ``platform_win/`` 既有的「失敗就降級」原則是同一條。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aurora.core.btcodec import CodecTable, HostContext, RadioInfo
from aurora.core.models import EndpointSnapshot


@runtime_checkable
class PlatformAdapter(Protocol):
    """上層需要從作業系統取得的全部東西。

    刻意做得很小。每加一個方法，macOS／未來平台就多一件必須實作的事，
    所以只有「真的有呼叫端」的能力才放進來。
    """

    @property
    def name(self) -> str:
        """給診斷與音質面板顯示用的平台名稱。"""
        ...

    # ------------------------------------------------------------ 系統偏好

    def system_animations_enabled(self) -> bool:
        """使用者是否允許動畫。關掉時要移除位移類動效（無障礙硬性要求）。"""
        ...

    # ------------------------------------------------------------ 音訊端點

    def query_endpoints(self) -> EndpointSnapshot:
        """目前的輸出端點。查不到就回空的 snapshot，不要拋例外。"""
        ...

    def host_context(self, table: CodecTable) -> HostContext:
        """藍牙編碼推定需要的本機環境。

        傳入 codec table 而不是讓上層自己組，是因為「要看哪些系統資訊」
        本身就是平台專屬的：Windows 看組建號與藍牙晶片的 USB VID，
        macOS 兩者都沒有對應概念。
        """
        ...

    # ------------------------------------------------------------ 檔案關聯

    def register_file_types(self) -> bool: ...

    def unregister_file_types(self) -> bool: ...

    def is_registered(self) -> bool: ...

    def open_default_apps_settings(self) -> bool:
        """開啟系統的「預設應用程式」設定頁。做不到就回 ``False``。"""
        ...


class NullAdapter:
    """全部降級的基準實作。

    用途有二：未知平台的退路，以及新平台 adapter 的起點 ——
    繼承它，然後一次覆寫一個方法。
    """

    @property
    def name(self) -> str:
        return "未知平台"

    def system_animations_enabled(self) -> bool:
        # 查不到就假設要動畫。這是多數使用者的預期，而且關掉動畫的人
        # 通常會自己去設定裡關。
        return True

    def query_endpoints(self) -> EndpointSnapshot:
        return EndpointSnapshot()

    def host_context(self, table: CodecTable) -> HostContext:
        # build 0 與未知 radio 會讓編碼推定退到最低確信度，
        # 面板顯示「無法判定」而不是猜一個。
        return HostContext(0, table.radio_for_vid(None))

    def register_file_types(self) -> bool:
        return False

    def unregister_file_types(self) -> bool:
        return False

    def is_registered(self) -> bool:
        return False

    def open_default_apps_settings(self) -> bool:
        return False


__all__ = ["CodecTable", "HostContext", "NullAdapter", "PlatformAdapter", "RadioInfo"]
