"""端點解析測試。

``WAVEFORMATEX`` 的 fixture 全部是從本機註冊表
``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Render``
實際抓下來的位元組，不是我編的 —— 這樣格式解析器對真實資料有回歸保護。
"""

from __future__ import annotations

import struct
import sys

import pytest

# 這裡必須用 allow_module_level 的 skip，不能只靠 pytestmark 的 skipif。
#
# skipif 只跳過「執行」，不阻止「import」—— 下面那幾行 module-level 的
# platform_win import 在收集階段就會跑，而 btregistry 會 import winreg，
# 在 macOS 上直接 ModuleNotFoundError，整個收集中斷。
# 原本的 skipif 之所以看起來沒問題，只是因為以前沒有非 Windows 的 CI。
if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Windows 專屬", allow_module_level=True)

from aurora.core.btcodec import HostContext, RadioInfo, default_table, resolve_codec
from aurora.core.models import EndpointSnapshot, TransportKind
from aurora.platform_win.btregistry import BluetoothDevice, match_company_id
from aurora.platform_win.endpoint import classify_transport, parse_wave_format

# --- 本機實際抓到的 PKEY_AudioEngine_DeviceFormat 位元組 -------------------
# 註冊表版本前面多了 8 個位元組的標頭，COM 版本沒有。

AIRPODS_A2DP = bytes.fromhex(
    "4100000001000000feff020080bb000000ee0200040010001600"
    "1000030000000100000000001000800000aa00389b71"
)
AIRPODS_HFP_NARROW = bytes.fromhex(
    "4100000001000000feff0100401f0000803e000002001000160"
    "01000040000000100000000001000800000aa00389b71"
)
AIRPODS_HFP_WIDE = bytes.fromhex(
    "4100000001000000feff0100803e0000007d000002001000160"
    "01000040000000100000000001000800000aa00389b71"
)
TECHNICS_A2DP = bytes.fromhex(
    "4100000001000000feff020080bb000000ee0200040010001600"
    "1000030000000100000000001000800000aa00389b71"
)


# ------------------------------------------------------------------ 格式解析


def test_parses_real_a2dp_blob() -> None:
    fmt = parse_wave_format(AIRPODS_A2DP)
    assert fmt is not None
    assert (fmt.sample_rate, fmt.channels, fmt.bits_per_sample) == (48000, 2, 16)
    assert not fmt.is_float


def test_parses_real_narrowband_hfp_blob() -> None:
    """8 kHz 單聲道 —— 這就是通話模式音質崩壞的原因。"""
    fmt = parse_wave_format(AIRPODS_HFP_NARROW)
    assert fmt is not None
    assert (fmt.sample_rate, fmt.channels) == (8000, 1)


def test_parses_real_wideband_hfp_blob() -> None:
    fmt = parse_wave_format(AIRPODS_HFP_WIDE)
    assert fmt is not None
    assert (fmt.sample_rate, fmt.channels) == (16000, 1)


def test_technics_and_airpods_negotiate_the_same_a2dp_format() -> None:
    assert parse_wave_format(TECHNICS_A2DP) == parse_wave_format(AIRPODS_A2DP)


def _waveformatex(tag: int, channels: int, rate: int, bits: int, cb_size: int = 0) -> bytes:
    block = channels * bits // 8
    return struct.pack("<HHIIHHH", tag, channels, rate, rate * block, block, bits, cb_size)


def test_parses_plain_pcm_without_registry_prefix() -> None:
    fmt = parse_wave_format(_waveformatex(0x0001, 2, 44100, 16))
    assert fmt is not None
    assert (fmt.sample_rate, fmt.channels, fmt.bits_per_sample) == (44100, 2, 16)
    assert not fmt.is_float


def test_detects_ieee_float_format() -> None:
    fmt = parse_wave_format(_waveformatex(0x0003, 2, 48000, 32))
    assert fmt is not None
    assert fmt.is_float


def test_detects_float_subformat_inside_extensible() -> None:
    """EXTENSIBLE 的 wFormatTag 一律是 0xFFFE，真正的型別藏在 SubFormat GUID 裡。"""
    header = _waveformatex(0xFFFE, 2, 48000, 32, cb_size=22)
    float_guid = struct.pack("<I", 3) + bytes.fromhex("0000100080000aa00389b71".rjust(24, "0"))
    extension = struct.pack("<HI", 32, 3) + float_guid[:16]
    fmt = parse_wave_format(header + extension)
    assert fmt is not None
    assert fmt.is_float


def test_rejects_garbage() -> None:
    assert parse_wave_format(b"") is None
    assert parse_wave_format(b"\x00" * 64) is None
    assert parse_wave_format(bytes(range(48))) is None


def test_rejects_absurd_sample_rate() -> None:
    assert parse_wave_format(_waveformatex(0x0001, 2, 999_999_999, 16)) is None


# ------------------------------------------------------------------ 傳輸分類


def test_enumerator_determines_transport() -> None:
    assert classify_transport("BTHENUM", "AirPods Pro") is TransportKind.BLUETOOTH_A2DP
    assert (
        classify_transport("BTHHFENUM", "AirPods Pro Hands-Free") is TransportKind.BLUETOOTH_HFP
    )
    assert classify_transport("INTELAUDIO", "喇叭") is TransportKind.WIRED
    assert classify_transport("USB", "Dell WH3024 Headset") is TransportKind.WIRED
    assert classify_transport("HDAUDIO", "NVIDIA Output") is TransportKind.WIRED
    assert classify_transport("", "?") is TransportKind.UNKNOWN


def test_unified_endpoint_falls_back_to_name() -> None:
    """Windows 11 有時把 A2DP 與 HFP 併成單一端點，只剩名稱可分辨。"""
    assert (
        classify_transport("BTHENUM", "Technics EAH-AZ100 Hands-Free")
        is TransportKind.BLUETOOTH_HFP
    )
    assert (
        classify_transport("BTHENUM", "AirPods Pro Hands-Free AG Audio")
        is TransportKind.BLUETOOTH_HFP
    )


# ------------------------------------------------------------------ 名稱 → 廠商


def _devices() -> tuple[BluetoothDevice, ...]:
    """本機註冊表實際掃到的內容。"""
    return (
        BluetoothDevice("778899AABBCC", "AirPods Pro 2", 0x004C),
        BluetoothDevice("AA11BB22CC33", "AirPods Pro", 0x004C),
        BluetoothDevice("DD44EE55FF66", "Technics EAH-AZ100", 0x0094),
        BluetoothDevice("112233445566", "藍牙喇叭", 0x000F),
    )


def test_matches_exact_endpoint_name() -> None:
    assert match_company_id("Technics EAH-AZ100", _devices()) == 0x0094


def test_matches_endpoint_name_with_hands_free_suffix() -> None:
    assert match_company_id("AirPods Pro Hands-Free", _devices()) == 0x004C


def test_unrelated_endpoint_matches_nothing() -> None:
    assert match_company_id("喇叭 (Conexant ISST Audio)", _devices()) is None


def test_longest_matching_name_wins() -> None:
    """短名稱是長名稱前綴時不可誤命中。"""
    devices = (
        BluetoothDevice("AAA", "Buds", 0x1111),
        BluetoothDevice("BBB", "Buds Pro Max", 0x2222),
    )
    assert match_company_id("Buds Pro Max", devices) == 0x2222
    assert match_company_id("Buds", devices) == 0x1111


# ------------------------------------------------------------------ 端到端


def _endpoint(name: str, enumerator: str, blob: bytes, company: int | None):  # type: ignore[no-untyped-def]
    from aurora.core.models import EndpointInfo

    return EndpointInfo(
        id=f"{{{name}}}",
        friendly_name=name,
        description="",
        enumerator=enumerator,
        instance_id="",
        transport=classify_transport(enumerator, name),
        device_format=parse_wave_format(blob),
        company_id=company,
    )


def test_real_airpods_a2dp_resolves_to_aac_on_this_machine() -> None:
    """本機是 Intel 晶片 + Windows 11 → AirPods 應推定為 AAC。"""
    endpoint = _endpoint("AirPods Pro", "BTHENUM", AIRPODS_A2DP, 0x004C)
    codec = resolve_codec(endpoint, HostContext(22631, RadioInfo(0x8087, "Intel", "intel")))
    assert codec.name == "AAC"


def test_real_hfp_endpoint_resolves_to_cvsd() -> None:
    endpoint = _endpoint("AirPods Pro Hands-Free", "BTHHFENUM", AIRPODS_HFP_NARROW, 0x004C)
    codec = resolve_codec(endpoint, HostContext(22631, RadioInfo(0x8087, "Intel", "intel")))
    assert codec.name == "CVSD"


def test_technics_ldac_is_unavailable_on_intel_windows() -> None:
    """這支耳機支援 LDAC，但 Windows 不支援 LDAC，所以實際跑 AAC。"""
    endpoint = _endpoint("Technics EAH-AZ100", "BTHENUM", TECHNICS_A2DP, 0x0094)
    codec = resolve_codec(endpoint, HostContext(22631, RadioInfo(0x8087, "Intel", "intel")))
    assert codec.name == "AAC"
    assert any("LDAC" in reason for reason in codec.reasons)


# ------------------------------------------------------------------ 快照


def test_snapshot_detects_hfp_sibling() -> None:
    a2dp = _endpoint("AirPods Pro", "BTHENUM", AIRPODS_A2DP, 0x004C)
    hfp = _endpoint("AirPods Pro Hands-Free", "BTHHFENUM", AIRPODS_HFP_NARROW, 0x004C)
    assert EndpointSnapshot(default=a2dp, active=(a2dp, hfp)).hfp_also_connected


def test_snapshot_ignores_other_devices_hfp() -> None:
    a2dp = _endpoint("AirPods Pro", "BTHENUM", AIRPODS_A2DP, 0x004C)
    other = _endpoint("Technics EAH-AZ100 Hands-Free", "BTHHFENUM", AIRPODS_HFP_NARROW, 0x0094)
    assert not EndpointSnapshot(default=a2dp, active=(a2dp, other)).hfp_also_connected


def test_snapshot_on_wired_output_never_warns() -> None:
    wired = _endpoint("喇叭 (Conexant ISST Audio)", "INTELAUDIO", b"", None)
    assert not EndpointSnapshot(default=wired, active=(wired,)).hfp_also_connected


def test_empty_snapshot_is_safe() -> None:
    assert not EndpointSnapshot().hfp_also_connected


# ------------------------------------------------------------------ 真機查詢


def test_live_query_returns_a_usable_snapshot() -> None:
    """實際打 COM。不斷言具體裝置（會隨機器變），只確認流程不炸且資料自洽。"""
    from aurora.platform_win.endpoint import query_endpoints

    snapshot = query_endpoints()
    if snapshot.default is None:
        pytest.skip("這台機器沒有預設輸出裝置")

    assert snapshot.default.friendly_name
    assert snapshot.default.id
    assert snapshot.default.transport in set(TransportKind)
    # 預設端點必定也在啟用清單裡
    assert any(item.id == snapshot.default.id for item in snapshot.active)


def test_live_query_formats_are_plausible() -> None:
    from aurora.platform_win.endpoint import query_endpoints

    for info in query_endpoints().active:
        fmt = info.effective_format
        if fmt is None:
            continue
        assert 4000 <= fmt.sample_rate <= 768000
        assert 1 <= fmt.channels <= 32


def test_codec_table_covers_every_live_endpoint() -> None:
    """每個實際端點都要得到一個判定結果，不能有例外或空字串。"""
    from aurora.platform_win.btregistry import radio_usb_vid
    from aurora.platform_win.endpoint import query_endpoints
    from aurora.platform_win.osinfo import windows_build

    table = default_table()
    context = HostContext(windows_build(), table.radio_for_vid(radio_usb_vid()))
    for info in query_endpoints().active:
        codec = resolve_codec(info, context, table)
        assert codec.name
        assert codec.confidence is not None
