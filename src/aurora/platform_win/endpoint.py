"""用 ctypes 直接呼叫 Windows Core Audio COM，查出目前的輸出端點與其格式。

為什麼不用 pycaw / comtypes：我們只需要五個介面的七個方法，手寫約兩百行
就能換到「零額外相依 + PyInstaller 零 hidden-import 風險」。COM 介面的
vtable 版面是 ABI 的一部分，不會變動。

各介面的 vtable 索引（前三個永遠是 IUnknown 的 QueryInterface/AddRef/Release）::

    IMMDeviceEnumerator   3 EnumAudioEndpoints   4 GetDefaultAudioEndpoint
    IMMDeviceCollection   3 GetCount             4 Item
    IMMDevice             3 Activate             4 OpenPropertyStore   5 GetId
    IPropertyStore        5 GetValue
    IAudioClient          8 GetMixFormat

設計原則：**任何一步失敗都只是少一項資訊**。整個模組不會往外拋例外，
查不到就回 ``None``，UI 顯示「未知裝置」而不是崩潰。
"""

from __future__ import annotations

import contextlib
import ctypes
import struct
from collections.abc import Callable, Iterator
from ctypes import POINTER, byref, c_void_p, wintypes
from dataclasses import dataclass

from aurora.core.models import AudioFormat, EndpointInfo, TransportKind
from aurora.platform_win.btregistry import (
    BluetoothDevice,
    match_company_id,
    scan_bluetooth_devices,
)

_ole32 = ctypes.WinDLL("ole32")

# ---------------------------------------------------------------- 常數

_CLSID_MM_DEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMM_DEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAUDIO_CLIENT = "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"

_E_RENDER = 0
_E_CONSOLE = 0
_DEVICE_STATE_ACTIVE = 0x1
_CLSCTX_ALL = 0x17
_STGM_READ = 0
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106

_VT_LPWSTR = 31
_VT_BLOB = 65

_DEVICE_CLASS_GUID = "{a45c254e-df1c-4efd-8020-67d146a850e0}"
_PKEY_DEVICE_FRIENDLY_NAME = (_DEVICE_CLASS_GUID, 14)
_PKEY_DEVICE_DESC = (_DEVICE_CLASS_GUID, 2)
_PKEY_DEVICE_ENUMERATOR_NAME = (_DEVICE_CLASS_GUID, 24)
_PKEY_DEVICE_INSTANCE_ID = ("{78c34fc8-104a-4aca-9ea4-524d52996e57}", 256)
_PKEY_AUDIO_ENGINE_DEVICE_FORMAT = ("{f19f064d-082c-4e27-bc73-6882a1bb8e4c}", 0)

#: 這些 enumerator 代表訊號沒有經過藍牙壓縮。
_BLUETOOTH_A2DP_ENUMERATOR = "BTHENUM"
_BLUETOOTH_HFP_ENUMERATOR = "BTHHFENUM"

#: Windows 會在藍牙耳機的通話端點名稱後面加這些後綴。
_HFP_NAME_SUFFIXES = (" hands-free ag audio", " hands-free", " hands free")

_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE
#: KSDATAFORMAT_SUBTYPE_IEEE_FLOAT 的 Data1
_SUBTYPE_IEEE_FLOAT = 3


# ---------------------------------------------------------------- 結構


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    )


class _PropertyKey(ctypes.Structure):
    _fields_ = (("fmtid", _Guid), ("pid", wintypes.DWORD))


class _Blob(ctypes.Structure):
    # 必須是 c_ubyte：c_byte 是有號的，位元組值 >127 讀出來會是負數。
    _fields_ = (("cbSize", wintypes.ULONG), ("pBlobData", POINTER(ctypes.c_ubyte)))


class _PropVariantUnion(ctypes.Union):
    _fields_ = (
        ("pwszVal", ctypes.c_wchar_p),
        ("blob", _Blob),
        ("raw", ctypes.c_ubyte * 16),
    )


class _PropVariant(ctypes.Structure):
    _fields_ = (
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("u", _PropVariantUnion),
    )


# ---------------------------------------------------------------- COM 基礎


def _guid(text: str) -> _Guid:
    value = _Guid()
    _ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(value))
    return value


def _property_key(source: tuple[str, int]) -> _PropertyKey:
    return _PropertyKey(_guid(source[0]), source[1])


def _method(pointer: c_void_p, index: int, *argtypes: type) -> Callable[..., int]:
    """從介面指標的 vtable 取出第 ``index`` 個方法。

    restype 用 ``ctypes.HRESULT``，ctypes 會在 FAILED 時自動轉成 ``OSError``，
    呼叫端只要包 try/except 就好，不必逐一比對 HRESULT 值。
    """
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(pointer: c_void_p | None) -> None:
    if pointer is None or not pointer.value:
        return
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)
    prototype(vtable[2])(pointer)


@contextlib.contextmanager
def _com_apartment() -> Iterator[None]:
    """確保這條執行緒有 COM。

    Qt 主執行緒通常已經初始化過（拖放需要 OLE），這時 ``CoInitializeEx``
    會回 ``S_FALSE``；若對方用了不同的執行緒模型則回 ``RPC_E_CHANGED_MODE``，
    兩種情況都代表「已經有 COM 可用」，直接沿用即可，也不該去 Uninitialize。
    """
    result = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    owns = result >= 0 and result != 1
    try:
        yield
    finally:
        if owns:
            _ole32.CoUninitialize()


# ---------------------------------------------------------------- 讀屬性


def _read_property(store: c_void_p, key: tuple[str, int]) -> _PropVariant | None:
    variant = _PropVariant()
    try:
        get_value = _method(store, 5, POINTER(_PropertyKey), POINTER(_PropVariant))
        get_value(store, byref(_property_key(key)), byref(variant))
    except OSError:
        return None
    return variant


def _read_string_property(store: c_void_p, key: tuple[str, int]) -> str:
    variant = _read_property(store, key)
    if variant is None:
        return ""
    try:
        return variant.u.pwszVal or "" if variant.vt == _VT_LPWSTR else ""
    finally:
        _ole32.PropVariantClear(byref(variant))


def _read_blob_property(store: c_void_p, key: tuple[str, int]) -> bytes:
    variant = _read_property(store, key)
    if variant is None:
        return b""
    try:
        if variant.vt != _VT_BLOB or not variant.u.blob.pBlobData:
            return b""
        size = int(variant.u.blob.cbSize)
        return ctypes.string_at(variant.u.blob.pBlobData, size)
    finally:
        _ole32.PropVariantClear(byref(variant))


# ---------------------------------------------------------------- 格式解析


def parse_wave_format(data: bytes) -> AudioFormat | None:
    """把 ``WAVEFORMATEX`` / ``WAVEFORMATEXTENSIBLE`` 位元組解析成 :class:`AudioFormat`。

    同一份資料經由 COM 取得時從位移 0 開始，而註冊表裡的
    ``PKEY_AudioEngine_DeviceFormat`` 前面多了 8 個位元組的標頭。
    兩個位移都試，用 wFormatTag 與取樣率是否合理來判斷哪個才對。
    """
    for offset in (0, 8):
        if len(data) < offset + 18:
            continue
        tag, channels, rate, _avg, _block, bits, _cb = struct.unpack_from("<HHIIHHH", data, offset)
        if tag not in (_WAVE_FORMAT_PCM, _WAVE_FORMAT_IEEE_FLOAT, _WAVE_FORMAT_EXTENSIBLE):
            continue
        if not 1 <= channels <= 32 or not 4000 <= rate <= 768000:
            continue

        is_float = tag == _WAVE_FORMAT_IEEE_FLOAT
        if tag == _WAVE_FORMAT_EXTENSIBLE and len(data) >= offset + 40:
            (subformat_data1,) = struct.unpack_from("<I", data, offset + 24)
            is_float = subformat_data1 == _SUBTYPE_IEEE_FLOAT
        return AudioFormat(rate, channels, bits, is_float)
    return None


def _mix_format(device: c_void_p) -> AudioFormat | None:
    """用 ``IAudioClient::GetMixFormat`` 取得目前共用模式的混音格式。"""
    client = c_void_p()
    try:
        activate = _method(device, 3, POINTER(_Guid), wintypes.DWORD, c_void_p, POINTER(c_void_p))
        activate(device, byref(_guid(_IID_IAUDIO_CLIENT)), _CLSCTX_ALL, None, byref(client))
    except OSError:
        return None

    pointer = c_void_p()
    try:
        get_mix_format = _method(client, 8, POINTER(c_void_p))
        get_mix_format(client, byref(pointer))
        if not pointer.value:
            return None
        # 先讀 18 個位元組的 WAVEFORMATEX，再依 cbSize 決定要不要多讀擴充欄位
        header = ctypes.string_at(pointer, 18)
        (extra,) = struct.unpack_from("<H", header, 16)
        return parse_wave_format(ctypes.string_at(pointer, 18 + extra))
    except OSError:
        return None
    finally:
        if pointer.value:
            _ole32.CoTaskMemFree(pointer)
        _release(client)


# ---------------------------------------------------------------- 分類


def _strip_hfp_suffix(name: str) -> str:
    lowered = name.lower()
    for suffix in _HFP_NAME_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name.strip()


def classify_transport(enumerator: str, name: str) -> TransportKind:
    """由 enumerator 判定傳輸型態。這是 100% 可靠的實測值，不是推測。"""
    upper = enumerator.upper()
    if upper == _BLUETOOTH_HFP_ENUMERATOR:
        return TransportKind.BLUETOOTH_HFP
    if upper == _BLUETOOTH_A2DP_ENUMERATOR:
        # Windows 11 有時把 A2DP 與 HFP 併成單一端點，這時只剩名稱可分辨
        return (
            TransportKind.BLUETOOTH_HFP
            if _strip_hfp_suffix(name) != name.strip()
            else TransportKind.BLUETOOTH_A2DP
        )
    if not enumerator:
        return TransportKind.UNKNOWN
    # 非藍牙 enumerator（USB / HDAUDIO / INTELAUDIO / SWD…）一律歸為未經藍牙壓縮。
    # 這裡宣稱的只是「沒走藍牙」，而這點由 enumerator 就足以確定。
    return TransportKind.WIRED


# ---------------------------------------------------------------- 端點讀取


def _read_endpoint(device: c_void_p, devices: tuple[BluetoothDevice, ...]) -> EndpointInfo | None:
    store = c_void_p()
    identifier = ctypes.c_wchar_p()
    try:
        open_store = _method(device, 4, wintypes.DWORD, POINTER(c_void_p))
        open_store(device, _STGM_READ, byref(store))
        get_id = _method(device, 5, POINTER(ctypes.c_wchar_p))
        get_id(device, byref(identifier))
    except OSError:
        _release(store)
        return None

    try:
        name = _read_string_property(store, _PKEY_DEVICE_FRIENDLY_NAME)
        description = _read_string_property(store, _PKEY_DEVICE_DESC)
        enumerator = _read_string_property(store, _PKEY_DEVICE_ENUMERATOR_NAME)
        instance_id = _read_string_property(store, _PKEY_DEVICE_INSTANCE_ID)
        device_format = parse_wave_format(
            _read_blob_property(store, _PKEY_AUDIO_ENGINE_DEVICE_FORMAT)
        )
        transport = classify_transport(enumerator, name)
        company_id = (
            match_company_id(name, devices)
            if transport in (TransportKind.BLUETOOTH_A2DP, TransportKind.BLUETOOTH_HFP)
            else None
        )
        return EndpointInfo(
            id=identifier.value or "",
            friendly_name=name,
            description=description,
            enumerator=enumerator,
            instance_id=instance_id,
            transport=transport,
            device_format=device_format,
            mix_format=_mix_format(device),
            company_id=company_id,
        )
    finally:
        _release(store)
        if identifier.value:
            _ole32.CoTaskMemFree(identifier)


@dataclass(frozen=True, slots=True)
class EndpointSnapshot:
    """某一瞬間的輸出裝置狀態。"""

    default: EndpointInfo | None = None
    active: tuple[EndpointInfo, ...] = ()

    @property
    def hfp_also_connected(self) -> bool:
        """目前走 A2DP，但同一支耳機的通話端點也在線上。

        這是實務上最常見的「音質突然變差」原因：某個程式開了麥克風，
        Windows 就把耳機切成通話模式。提早告訴使用者可以省下很多困惑。
        """
        if self.default is None or self.default.transport is not TransportKind.BLUETOOTH_A2DP:
            return False
        base = _strip_hfp_suffix(self.default.friendly_name).lower()
        return any(
            item.transport is TransportKind.BLUETOOTH_HFP
            and _strip_hfp_suffix(item.friendly_name).lower() == base
            for item in self.active
        )


def query_endpoints() -> EndpointSnapshot:
    """讀出預設輸出端點與所有啟用中的輸出端點。失敗時回傳空快照。"""
    try:
        with _com_apartment():
            return _query()
    except OSError:
        return EndpointSnapshot()


def _query() -> EndpointSnapshot:
    enumerator = c_void_p()
    try:
        _ole32.CoCreateInstance(
            byref(_guid(_CLSID_MM_DEVICE_ENUMERATOR)),
            None,
            _CLSCTX_ALL,
            byref(_guid(_IID_IMM_DEVICE_ENUMERATOR)),
            byref(enumerator),
        )
    except OSError:
        return EndpointSnapshot()
    if not enumerator.value:
        return EndpointSnapshot()

    bluetooth = scan_bluetooth_devices()
    try:
        return EndpointSnapshot(
            default=_query_default(enumerator, bluetooth),
            active=_query_active(enumerator, bluetooth),
        )
    finally:
        _release(enumerator)


def _query_default(
    enumerator: c_void_p, bluetooth: tuple[BluetoothDevice, ...]
) -> EndpointInfo | None:
    device = c_void_p()
    try:
        get_default = _method(enumerator, 4, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))
        get_default(enumerator, _E_RENDER, _E_CONSOLE, byref(device))
    except OSError:
        return None  # 沒有任何輸出裝置時 GetDefaultAudioEndpoint 會失敗，這是正常情況
    try:
        return _read_endpoint(device, bluetooth) if device.value else None
    finally:
        _release(device)


def _query_active(
    enumerator: c_void_p, bluetooth: tuple[BluetoothDevice, ...]
) -> tuple[EndpointInfo, ...]:
    collection = c_void_p()
    try:
        enum_endpoints = _method(enumerator, 3, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p))
        enum_endpoints(enumerator, _E_RENDER, _DEVICE_STATE_ACTIVE, byref(collection))
    except OSError:
        return ()
    if not collection.value:
        return ()

    found: list[EndpointInfo] = []
    try:
        count = wintypes.UINT()
        get_count = _method(collection, 3, POINTER(wintypes.UINT))
        get_count(collection, byref(count))

        item = _method(collection, 4, wintypes.UINT, POINTER(c_void_p))
        for index in range(int(count.value)):
            device = c_void_p()
            try:
                item(collection, index, byref(device))
            except OSError:
                continue
            try:
                info = _read_endpoint(device, bluetooth) if device.value else None
            finally:
                _release(device)
            if info is not None:
                found.append(info)
    except OSError:
        pass
    finally:
        _release(collection)
    return tuple(found)
