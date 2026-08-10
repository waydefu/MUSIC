"""從註冊表讀藍牙裝置的廠商資訊。

音訊端點本身**不帶**藍牙廠商代碼 —— ``PKEY_Device_InstanceId`` 回傳的是
``SWD\\MMDEVAPI\\{0.0.0.00000000}.{guid}`` 這種音訊子系統的路徑。
所以要另外從 ``HKLM\\SYSTEM\\CurrentControlSet\\Enum\\BTHENUM`` 湊出對應：

``Dev_<MAC>``
    存放裝置的 FriendlyName，例如 ``Dev_AA11BB22CC33`` → ``AirPods Pro``。
``{0000110b-…}_VID&<ns><company>_PID&<pid>``
    A2DP Sink 服務鍵，鍵名帶廠商代碼，底下的執行個體名帶 MAC，
    例如 ``7&1a2b3c4d&2&AA11BB22CC33_C00000000``。

兩邊用 MAC 接起來，就得到「裝置名稱 → 藍牙 SIG 公司代碼」。
端點名稱可能帶後綴（``AirPods Pro Hands-Free``），所以比對用前綴。

全部唯讀，且任何一步失敗都只是少一項資訊，不影響播放。
"""

from __future__ import annotations

import re
import winreg
from dataclasses import dataclass

_BTHENUM = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
_BTHUSB_ENUM = r"SYSTEM\CurrentControlSet\Services\BTHUSB\Enum"

#: A2DP Sink 與 Hands-Free 的服務 UUID 前綴。
_SERVICE_KEYS = ("{0000110b-", "{0000111e-")
#: 服務鍵名裡的 ``VID&<2 byte namespace><2 byte company>``。
#: namespace ``0001`` 才是藍牙 SIG 的公司代碼空間。
_VID_PATTERN = re.compile(r"VID&(\w{4})(\w{4})", re.IGNORECASE)
#: 執行個體名尾端的 12 位十六進位 MAC。
_MAC_PATTERN = re.compile(r"&([0-9A-F]{12})(?:_|$)", re.IGNORECASE)
#: 藍牙晶片的 USB Vendor ID。
_USB_VID_PATTERN = re.compile(r"VID_([0-9A-F]{4})", re.IGNORECASE)

_SIG_NAMESPACE = "0001"


@dataclass(frozen=True, slots=True)
class BluetoothDevice:
    mac: str
    name: str
    company_id: int | None = None


def _subkeys(key: winreg.HKEYType) -> list[str]:
    names: list[str] = []
    index = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, index))
        except OSError:
            return names
        index += 1


def _read_string(path: str, name: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(value) if isinstance(value, str) else None


def _macs_to_names() -> dict[str, str]:
    """``Dev_<MAC>`` 子鍵 → FriendlyName。"""
    result: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _BTHENUM) as root:
            device_keys = [name for name in _subkeys(root) if name.lower().startswith("dev_")]
    except OSError:
        return result

    for device_key in device_keys:
        mac = device_key[4:].upper()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{_BTHENUM}\{device_key}") as key:
                instances = _subkeys(key)
        except OSError:
            continue
        for instance in instances:
            name = _read_string(rf"{_BTHENUM}\{device_key}\{instance}", "FriendlyName")
            if name:
                result[mac] = name
                break
    return result


def _macs_to_company_ids() -> dict[str, int]:
    """A2DP / HFP 服務鍵 → 該 MAC 的藍牙 SIG 公司代碼。"""
    result: dict[str, int] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _BTHENUM) as root:
            service_keys = [
                name
                for name in _subkeys(root)
                if any(name.lower().startswith(prefix) for prefix in _SERVICE_KEYS)
            ]
    except OSError:
        return result

    for service_key in service_keys:
        matched = _VID_PATTERN.search(service_key)
        # LOCALMFG&xxxx 這類沒有 VID 的後備鍵直接跳過
        if not matched or matched.group(1) != _SIG_NAMESPACE:
            continue
        company_id = int(matched.group(2), 16)

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{_BTHENUM}\{service_key}") as key:
                instances = _subkeys(key)
        except OSError:
            continue

        for instance in instances:
            mac_match = _MAC_PATTERN.search(instance)
            if mac_match:
                result.setdefault(mac_match.group(1).upper(), company_id)
    return result


def scan_bluetooth_devices() -> tuple[BluetoothDevice, ...]:
    """列出已配對且能查到名稱的藍牙音訊裝置。"""
    names = _macs_to_names()
    companies = _macs_to_company_ids()
    return tuple(
        BluetoothDevice(mac, name, companies.get(mac)) for mac, name in sorted(names.items())
    )


def match_company_id(endpoint_name: str, devices: tuple[BluetoothDevice, ...]) -> int | None:
    """把音訊端點名稱對回藍牙裝置的公司代碼。

    端點名稱可能是 ``AirPods Pro`` 或 ``AirPods Pro Hands-Free``，
    所以取「名稱最長且為端點名稱前綴」的那台 —— 避免短名稱誤命中。
    """
    lowered = endpoint_name.strip().lower()
    best: BluetoothDevice | None = None
    for device in devices:
        if device.company_id is None or not device.name:
            continue
        if lowered.startswith(device.name.lower()) and (
            best is None or len(device.name) > len(best.name)
        ):
            best = device
    return best.company_id if best else None


def radio_usb_vid() -> int | None:
    """本機藍牙晶片的 USB Vendor ID（例：Intel 為 ``0x8087``）。"""
    value = _read_string(_BTHUSB_ENUM, "0")
    if not value:
        return None
    matched = _USB_VID_PATTERN.search(value)
    return int(matched.group(1), 16) if matched else None
