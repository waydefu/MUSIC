"""Windows adapter。

**這是一層薄包裝，不是新實作。** 真正的邏輯（COM vtable 呼叫、註冊表
讀寫、檔案關聯）留在 ``platform_win/`` 原地不動 —— 那裡有兩百行手寫的
ctypes COM 介面，搬動它只會製造風險而換不到任何好處。

這個檔案存在的唯一理由：讓上層可以只認識 :class:`~aurora.platform.base.PlatformAdapter`，
而 ``platform_win`` 變成 Windows 這條分支的實作細節。
"""

from __future__ import annotations

from aurora.core.models import EndpointSnapshot
from aurora.platform.base import CodecTable, HostContext, NullAdapter
from aurora.platform_win import endpoint, fileassoc, osinfo
from aurora.platform_win.btregistry import radio_usb_vid


class WindowsAdapter(NullAdapter):
    """把 ``platform_win`` 的模組級函式接到 adapter 契約上。"""

    @property
    def name(self) -> str:
        return "Windows"

    def system_animations_enabled(self) -> bool:
        return osinfo.system_animations_enabled()

    def query_endpoints(self) -> EndpointSnapshot:
        return endpoint.query_endpoints()

    def host_context(self, table: CodecTable) -> HostContext:
        # 組建號決定系統內建支援哪些編碼；藍牙晶片的 USB VID 決定
        # 廠商私有編碼（LDAC / aptX 系列）有沒有機會出現。
        return HostContext(osinfo.windows_build(), table.radio_for_vid(radio_usb_vid()))

    def register_file_types(self) -> bool:
        return fileassoc.register_file_types()

    def unregister_file_types(self) -> bool:
        return fileassoc.unregister_file_types()

    def is_registered(self) -> bool:
        return fileassoc.is_registered()

    def open_default_apps_settings(self) -> bool:
        return fileassoc.open_default_apps_settings()
