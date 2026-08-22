"""macOS adapter —— **骨架，尚未實作**。

目前每個能力都沿用 :class:`~aurora.platform.base.NullAdapter` 的降級行為，
所以 AURORA 在 macOS 上「跑得起來、播得出聲」，只是音質面板的裝置與編碼
欄位會顯示未知。這是刻意的：先讓 import 鏈與 QML 在 macOS 上通，
再一個一個把能力補上。

## 給接手的人

一次覆寫一個方法，每補一個就跑一次 CI。沒覆寫的自動降級，不會壞。

``system_animations_enabled``
    對應 ``NSWorkspace.shared.accessibilityDisplayShouldReduceMotion``。
    注意語意是**相反**的：那個 API 回 ``True`` 代表使用者要「減少動態」，
    所以這裡要回它的反面。這是無障礙硬性要求，優先度最高、也最容易做。

``query_endpoints``
    Core Audio 的 ``AudioObjectGetPropertyData`` +
    ``kAudioHardwarePropertyDefaultOutputDevice``。要填的是**中立的**
    :class:`~aurora.core.models.EndpointSnapshot`，欄位語意照
    ``platform_win/endpoint.py`` 的既有用法對齊，不要另立一套。
    藍牙耳機在 macOS 上同樣有 A2DP／HFP 兩個端點，
    :attr:`EndpointSnapshot.hfp_also_connected` 的邏輯可以直接沿用。

``host_context``
    ``bt_codecs.toml`` 目前只有 ``[windows]`` 區段，推定規則是 Windows 專屬的。
    在資料表長出 macOS 區段之前，**維持降級**是誠實的做法 ——
    寧可顯示「無法判定」，也不要套一組不適用的規則然後給出錯誤的自信。

``register_file_types`` / ``open_default_apps_settings``
    macOS 靠 app bundle 的 ``Info.plist``（``CFBundleDocumentTypes``），
    不是執行期註冊。本階段不打包，所以**維持回 False**，不要硬做。

## 兩條限制

1. **這個檔案必須在任何平台都 import 得起來。** 測試會在 Windows 上
   import 它來驗證是否滿足 Protocol。所以 macOS 專屬的匯入
   （``Foundation``、``ctypes`` 綁 CoreAudio…）一律寫在方法內部，
   不要放模組層級 —— ``platform_win`` 就是踩了這個坑，才害得整個
   ``bridge/quality.py`` 在 macOS 上連 import 都過不了。
2. **失敗一律降級，不要拋例外。** 查不到裝置資訊絕不能讓播放中斷。

其他 macOS 專屬的地雷（APFS 的 NFD 正規化、``app_data_dir()``）
見 ``PROJECT_PLAN.md`` 的 §8.3。
"""

from __future__ import annotations

from aurora.platform.base import NullAdapter


class MacOSAdapter(NullAdapter):
    """macOS 平台能力。目前其餘能力仍沿用降級行為，逐一覆寫中。"""

    @property
    def name(self) -> str:
        return "macOS"

    def system_animations_enabled(self) -> bool:
        """依 macOS 的 Reduce Motion 偏好決定是否保留位移動效。

        原生 API 的語意剛好相反；查詢失敗時沿用 ``NullAdapter`` 的預設，
        讓無障礙偏好查詢本身絕不阻斷播放器啟動。
        """
        try:
            return not self._read_reduce_motion()
        except Exception:
            return True

    def _read_reduce_motion(self) -> bool:
        """以 Objective-C runtime 讀取 ``NSWorkspace`` 的 Reduce Motion 設定。

        不使用 PyObjC，避免新增依賴與打包時的 hidden-import 風險。這些原生
        載入刻意留在方法內，讓本模組仍可在 Windows 的契約測試中 import。
        """
        import ctypes

        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        workspace_class = objc.objc_getClass(b"NSWorkspace")
        shared_workspace = objc.sel_registerName(b"sharedWorkspace")
        reduce_motion = objc.sel_registerName(b"accessibilityDisplayShouldReduceMotion")
        if not workspace_class or not shared_workspace or not reduce_motion:
            raise RuntimeError("NSWorkspace Objective-C runtime symbols are unavailable")

        objc.objc_msgSend.restype = ctypes.c_void_p
        workspace = objc.objc_msgSend(workspace_class, shared_workspace)
        if not workspace:
            raise RuntimeError("NSWorkspace.sharedWorkspace returned nil")

        objc.objc_msgSend.restype = ctypes.c_bool
        return bool(objc.objc_msgSend(workspace, reduce_motion))
