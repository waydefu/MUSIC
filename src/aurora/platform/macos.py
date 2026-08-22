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

from aurora.core.models import (
    AudioFormat,
    EndpointInfo,
    EndpointSnapshot,
    TransportKind,
    strip_hfp_suffix,
)
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
        objc.class_getClassMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.class_getClassMethod.restype = ctypes.c_void_p
        objc.class_getInstanceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.class_getInstanceMethod.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        workspace_class = objc.objc_getClass(b"NSWorkspace")
        shared_workspace = objc.sel_registerName(b"sharedWorkspace")
        reduce_motion = objc.sel_registerName(b"accessibilityDisplayShouldReduceMotion")
        if (
            not workspace_class
            or not shared_workspace
            or not reduce_motion
            # Selector 可以註冊卻沒有實作；直接傳訊息會觸發 Objective-C 例外，
            # Python 無法攔住。先在 runtime 查詢，舊版 macOS 才能誠實降級。
            or not objc.class_getClassMethod(workspace_class, shared_workspace)
            or not objc.class_getInstanceMethod(workspace_class, reduce_motion)
        ):
            raise RuntimeError("NSWorkspace Objective-C runtime symbols are unavailable")

        objc.objc_msgSend.restype = ctypes.c_void_p
        workspace = objc.objc_msgSend(workspace_class, shared_workspace)
        if not workspace:
            raise RuntimeError("NSWorkspace.sharedWorkspace returned nil")

        objc.objc_msgSend.restype = ctypes.c_bool
        return bool(objc.objc_msgSend(workspace, reduce_motion))

    @staticmethod
    def _classify_transport(
        enumerator: str,
        name: str,
        device_format: AudioFormat | None,
        mix_format: AudioFormat | None,
    ) -> TransportKind:
        """將 Core Audio transport FourCC 映射為平台中立的傳輸型態。"""
        if enumerator == "blue":
            is_hfp_name = strip_hfp_suffix(name) != name.strip()
            is_hfp_format = any(
                audio_format is not None
                and audio_format.channels == 1
                and audio_format.sample_rate in (8000, 16000, 32000)
                for audio_format in (device_format, mix_format)
            )
            return (
                TransportKind.BLUETOOTH_HFP
                if is_hfp_name or is_hfp_format
                else TransportKind.BLUETOOTH_A2DP
            )
        if enumerator in {"", "blea", "airp", "virt"}:
            return TransportKind.UNKNOWN
        if enumerator in {"bltn", "pci ", "usb ", "1394", "hdmi", "dprt", "eavb", "thun", "ccwd"}:
            return TransportKind.WIRED
        # Aggregate、網路與未來 transport 不應被誤標成「沒有藍牙壓縮」。
        return TransportKind.UNKNOWN

    def query_endpoints(self) -> EndpointSnapshot:
        """讀出可用輸出端點；Core Audio 出錯時保留空白的安全降級。"""
        try:
            default_id, active = self._query_coreaudio()
        except Exception:
            return EndpointSnapshot()

        # 不能另讀一次 default device：裝置可能正好在兩次呼叫之間切換。用同一輪
        # 枚舉到的值物件，讓 ``default`` 一定是 ``active`` 裡的同一個端點。
        default = next((item for item in active if item.id == default_id), None)
        return EndpointSnapshot(default=default, active=active)

    def _query_coreaudio(self) -> tuple[str | None, tuple[EndpointInfo, ...]]:
        """以 Core Audio 讀出預設輸出 UID 與 alive 的 output devices。

        Core Audio 的數值常數是 C header 裡的 FourCC。這裡刻意不引入 PyObjC：
        這份小型 ``ctypes`` bridge 足夠讀取 HAL，且在 Windows import 本模組時
        完全不會碰到任何 macOS framework。
        """
        import ctypes
        import math

        class AudioObjectPropertyAddress(ctypes.Structure):
            _fields_ = (
                ("selector", ctypes.c_uint32),
                ("scope", ctypes.c_uint32),
                ("element", ctypes.c_uint32),
            )

        class AudioStreamBasicDescription(ctypes.Structure):
            _fields_ = (
                ("sample_rate", ctypes.c_double),
                ("format_id", ctypes.c_uint32),
                ("format_flags", ctypes.c_uint32),
                ("bytes_per_packet", ctypes.c_uint32),
                ("frames_per_packet", ctypes.c_uint32),
                ("bytes_per_frame", ctypes.c_uint32),
                ("channels_per_frame", ctypes.c_uint32),
                ("bits_per_channel", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32),
            )

        def fourcc(value: str) -> int:
            return int.from_bytes(value.encode("ascii"), "big")

        def fourcc_text(value: int | None) -> str:
            if value is None or value == 0:
                return ""
            raw = value.to_bytes(4, "big")
            if all(32 <= byte <= 126 for byte in raw):
                return raw.decode("ascii")
            return f"0x{value:08X}"

        scope_global = fourcc("glob")
        scope_output = fourcc("outp")
        element_main = 0
        system_object = 1
        property_devices = fourcc("dev#")
        property_default_output = fourcc("dOut")
        property_uid = fourcc("uid ")
        property_name = fourcc("lnam")
        property_manufacturer = fourcc("lmak")
        property_transport = fourcc("tran")
        property_alive = fourcc("livn")
        property_streams = fourcc("stm#")
        property_nominal_rate = fourcc("nsrt")
        property_virtual_format = fourcc("sfmt")
        property_physical_format = fourcc("pft ")
        linear_pcm = fourcc("lpcm")
        audio_format_flag_is_float = 1 << 0
        utf8 = 0x08000100

        coreaudio = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        corefoundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        get_property_data_size = coreaudio.AudioObjectGetPropertyDataSize
        get_property_data_size.argtypes = (
            ctypes.c_uint32,
            ctypes.POINTER(AudioObjectPropertyAddress),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        get_property_data_size.restype = ctypes.c_int32
        get_property_data = coreaudio.AudioObjectGetPropertyData
        get_property_data.argtypes = (
            ctypes.c_uint32,
            ctypes.POINTER(AudioObjectPropertyAddress),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        )
        get_property_data.restype = ctypes.c_int32
        corefoundation.CFStringGetLength.argtypes = (ctypes.c_void_p,)
        corefoundation.CFStringGetLength.restype = ctypes.c_long
        corefoundation.CFStringGetMaximumSizeForEncoding.argtypes = (
            ctypes.c_long,
            ctypes.c_uint32,
        )
        corefoundation.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
        corefoundation.CFStringGetCString.argtypes = (
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        )
        corefoundation.CFStringGetCString.restype = ctypes.c_bool
        corefoundation.CFRelease.argtypes = (ctypes.c_void_p,)
        corefoundation.CFRelease.restype = None

        def address(selector: int, scope: int = scope_global) -> AudioObjectPropertyAddress:
            return AudioObjectPropertyAddress(selector, scope, element_main)

        def read_uint32(object_id: int, selector: int, scope: int = scope_global) -> int | None:
            value = ctypes.c_uint32()
            size = ctypes.c_uint32(ctypes.sizeof(value))
            status = get_property_data(
                object_id,
                ctypes.byref(address(selector, scope)),
                0,
                None,
                ctypes.byref(size),
                ctypes.byref(value),
            )
            if status != 0 or size.value != ctypes.sizeof(value):
                return None
            return int(value.value)

        def read_float64(object_id: int, selector: int, scope: int = scope_global) -> float | None:
            value = ctypes.c_double()
            size = ctypes.c_uint32(ctypes.sizeof(value))
            status = get_property_data(
                object_id,
                ctypes.byref(address(selector, scope)),
                0,
                None,
                ctypes.byref(size),
                ctypes.byref(value),
            )
            if status != 0 or size.value != ctypes.sizeof(value):
                return None
            return float(value.value)

        def read_object_ids(
            object_id: int, selector: int, scope: int = scope_global
        ) -> tuple[int, ...] | None:
            data_size = ctypes.c_uint32()
            if (
                get_property_data_size(
                    object_id,
                    ctypes.byref(address(selector, scope)),
                    0,
                    None,
                    ctypes.byref(data_size),
                )
                != 0
            ):
                return None
            item_size = ctypes.sizeof(ctypes.c_uint32)
            if data_size.value % item_size != 0:
                return None
            count = data_size.value // item_size
            # HAL 應只會回傳少數裝置；異常大小絕不讓診斷查詢配置無界記憶體。
            if count > 4096:
                return None
            if count == 0:
                return ()
            values = (ctypes.c_uint32 * count)()
            bytes_read = ctypes.c_uint32(data_size.value)
            if (
                get_property_data(
                    object_id,
                    ctypes.byref(address(selector, scope)),
                    0,
                    None,
                    ctypes.byref(bytes_read),
                    values,
                )
                != 0
                or bytes_read.value != data_size.value
            ):
                return None
            return tuple(int(value) for value in values)

        def read_cf_string(object_id: int, selector: int, scope: int = scope_global) -> str:
            reference = ctypes.c_void_p()
            size = ctypes.c_uint32(ctypes.sizeof(reference))
            status = get_property_data(
                object_id,
                ctypes.byref(address(selector, scope)),
                0,
                None,
                ctypes.byref(size),
                ctypes.byref(reference),
            )
            if status != 0 or size.value != ctypes.sizeof(reference) or not reference.value:
                return ""
            try:
                length = corefoundation.CFStringGetLength(reference)
                capacity = corefoundation.CFStringGetMaximumSizeForEncoding(length, utf8) + 1
                if capacity <= 1 or capacity > 65536:
                    return ""
                buffer = ctypes.create_string_buffer(capacity)
                if not corefoundation.CFStringGetCString(reference, buffer, capacity, utf8):
                    return ""
                return buffer.value.decode("utf-8", errors="replace")
            finally:
                corefoundation.CFRelease(reference)

        def is_valid_sample_rate(value: float | None) -> bool:
            return value is not None and math.isfinite(value) and 4000 <= value <= 768000

        def read_stream_format(
            stream_id: int, selector: int, nominal_rate: float | None = None
        ) -> AudioFormat | None:
            description = AudioStreamBasicDescription()
            size = ctypes.c_uint32(ctypes.sizeof(description))
            status = get_property_data(
                stream_id,
                ctypes.byref(address(selector)),
                0,
                None,
                ctypes.byref(size),
                ctypes.byref(description),
            )
            if status != 0 or size.value != ctypes.sizeof(description):
                return None
            # AudioFormat 僅描述 PCM。若 HAL 報的是壓縮或未知格式，不能把它
            # 偽裝成整數 PCM；保留 None 才是對音質面板誠實的降級。
            if description.format_id != linear_pcm:
                return None
            sample_rate = (
                float(nominal_rate)
                if nominal_rate is not None and is_valid_sample_rate(nominal_rate)
                else float(description.sample_rate)
            )
            if (
                not is_valid_sample_rate(sample_rate)
                or not 1 <= description.channels_per_frame <= 32
                or not 1 <= description.bits_per_channel <= 64
            ):
                return None
            return AudioFormat(
                sample_rate=round(sample_rate),
                channels=int(description.channels_per_frame),
                bits_per_sample=int(description.bits_per_channel),
                is_float=bool(description.format_flags & audio_format_flag_is_float),
            )

        def read_endpoint(device_id: int) -> EndpointInfo | None:
            # 讀不到 alive 或 output streams 時，不能誠實地稱它為可用的輸出端點。
            if not read_uint32(device_id, property_alive):
                return None
            streams = read_object_ids(device_id, property_streams, scope_output)
            if not streams:
                return None

            # UID 是穩定 ID；極少數壞掉的 HAL property 則以這次 boot 的 object ID
            # 保留端點，不能因為單一欄位失敗而整筆資料消失。
            uid = read_cf_string(device_id, property_uid) or str(device_id)
            name = read_cf_string(device_id, property_name) or uid
            manufacturer = read_cf_string(device_id, property_manufacturer)
            transport = read_uint32(device_id, property_transport)
            transport_name = fourcc_text(transport)
            nominal_rate = read_float64(device_id, property_nominal_rate)
            device_format: AudioFormat | None = None
            mix_format: AudioFormat | None = None
            for stream_id in streams:
                if device_format is None:
                    device_format = read_stream_format(
                        stream_id, property_physical_format, nominal_rate
                    )
                if mix_format is None:
                    mix_format = read_stream_format(stream_id, property_virtual_format)
                if device_format is not None and mix_format is not None:
                    break

            return EndpointInfo(
                id=uid,
                friendly_name=name,
                description=manufacturer,
                enumerator=transport_name,
                instance_id="",
                transport=self._classify_transport(
                    transport_name, name, device_format, mix_format
                ),
                device_format=device_format,
                mix_format=mix_format,
                company_id=None,
            )

        device_ids = read_object_ids(system_object, property_devices)
        if device_ids is None:
            raise RuntimeError("Core Audio did not return a device list")
        default_device_id = read_uint32(system_object, property_default_output)
        active_pairs: list[tuple[int, EndpointInfo]] = []
        for device_id in device_ids:
            try:
                endpoint = read_endpoint(device_id)
            except Exception:
                # 裝置拔除或 HAL 在重設時可能只讓其中一筆查詢失敗；其餘端點仍可用。
                continue
            if endpoint is not None:
                active_pairs.append((device_id, endpoint))
        default_id = next(
            (item.id for device_id, item in active_pairs if device_id == default_device_id),
            None,
        )
        return default_id, tuple(item for _, item in active_pairs)
