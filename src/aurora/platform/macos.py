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
    """macOS 平台能力。目前全部沿用降級行為，逐一覆寫中。"""

    @property
    def name(self) -> str:
        return "macOS"
