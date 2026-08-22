"""編碼判定測試。

固定用本機實測到的真實資料當基準：Intel 藍牙晶片 (USB VID 0x8087)、
Windows 11 23H2 (build 22631)、AirPods Pro (公司代碼 0x004C)、
Technics EAH-AZ100 (公司代碼 0x0094)。
"""

import pytest

from aurora.core.btcodec import CodecTable, HostContext, RadioInfo, default_table, resolve_codec
from aurora.core.models import AudioFormat, Confidence, EndpointInfo, TransportKind

INTEL = RadioInfo(0x8087, "Intel", "intel")
QUALCOMM = RadioInfo(0x0CF3, "Qualcomm Atheros", "qualcomm")

WIN11 = 22631
WIN10 = 19045


@pytest.fixture(scope="module")
def table() -> CodecTable:
    return default_table()


def _endpoint(
    *,
    name: str,
    transport: TransportKind,
    company_id: int | None = None,
    sample_rate: int = 48000,
    channels: int = 2,
) -> EndpointInfo:
    return EndpointInfo(
        id="{0.0.0.00000000}.{test}",
        friendly_name=name,
        description="Headphones",
        enumerator="BTHENUM",
        instance_id="BTHENUM\\test",
        transport=transport,
        device_format=AudioFormat(sample_rate, channels, 16),
        company_id=company_id,
    )


# ------------------------------------------------------------------ 有線


def test_wired_output_is_measured_not_inferred(table: CodecTable) -> None:
    endpoint = _endpoint(name="喇叭 (Conexant ISST Audio)", transport=TransportKind.WIRED)
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.confidence is Confidence.MEASURED
    assert "無壓縮" in codec.name


# ------------------------------------------------------------------ HFP（推導）


@pytest.mark.parametrize(
    ("sample_rate", "expected"),
    [(8000, "CVSD"), (16000, "mSBC"), (32000, "LC3-SWB")],
)
def test_hfp_codec_is_derived_from_endpoint_rate(
    table: CodecTable, sample_rate: int, expected: str
) -> None:
    """HFP 取樣率與編碼是一對一關係，屬於推導而非推定。"""
    endpoint = _endpoint(
        name="AirPods Pro Hands-Free",
        transport=TransportKind.BLUETOOTH_HFP,
        sample_rate=sample_rate,
        channels=1,
    )
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.name == expected
    assert codec.confidence is Confidence.DERIVED


def test_unknown_hfp_rate_is_reported_as_unknown(table: CodecTable) -> None:
    endpoint = _endpoint(
        name="怪裝置",
        transport=TransportKind.BLUETOOTH_HFP,
        sample_rate=44100,
        channels=1,
    )
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.confidence is Confidence.UNKNOWN


def test_hfp_is_still_derived_without_windows_context(table: CodecTable) -> None:
    """HFP 只依端點格式判定，不能因為主機不是 Windows 而降級。"""
    endpoint = _endpoint(
        name="AirPods Pro Hands-Free",
        transport=TransportKind.BLUETOOTH_HFP,
        sample_rate=16000,
        channels=1,
    )
    codec = resolve_codec(endpoint, HostContext(0, INTEL), table)
    assert codec.name == "mSBC"
    assert codec.confidence is Confidence.DERIVED


# ------------------------------------------------------------------ A2DP（推定）


def test_airpods_on_windows11_infers_aac(table: CodecTable) -> None:
    endpoint = _endpoint(
        name="AirPods Pro",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x004C,
    )
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.name == "AAC"
    assert codec.confidence is Confidence.INFERRED
    assert codec.reasons


def test_ldac_headphones_on_windows_fall_back_to_aac(table: CodecTable) -> None:
    """Technics EAH-AZ100 支援 LDAC，但 Windows 不原生支援 LDAC，
    所以實際上跑的是 AAC。推理依據必須說明 LDAC 為何被排除。"""
    endpoint = _endpoint(
        name="Technics EAH-AZ100",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x0094,
    )
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.name == "AAC"
    assert any("LDAC" in reason for reason in codec.reasons)


def test_aptx_requires_qualcomm_radio(table: CodecTable) -> None:
    """同一支 Qualcomm 耳機，換晶片就換結果 —— 這是 aptX 的實際限制。"""
    endpoint = _endpoint(
        name="某支 Qualcomm 耳機",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x001D,
    )
    on_qualcomm = resolve_codec(endpoint, HostContext(WIN11, QUALCOMM), table)
    on_intel = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)

    assert on_qualcomm.name == "aptX"
    assert on_intel.name == "AAC"


def test_windows10_has_no_aac(table: CodecTable) -> None:
    endpoint = _endpoint(
        name="AirPods Pro",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x004C,
    )
    codec = resolve_codec(endpoint, HostContext(WIN10, INTEL), table)
    assert codec.name == "SBC"


def test_unknown_device_is_honest_about_uncertainty(table: CodecTable) -> None:
    endpoint = _endpoint(
        name="某台沒聽過的喇叭",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x9999,
    )
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.name == "SBC 或 AAC"
    assert codec.confidence is Confidence.INFERRED
    assert any("沒有這台裝置" in reason for reason in codec.reasons)


def test_a2dp_is_unknown_without_windows_context(table: CodecTable) -> None:
    """macOS 等非 Windows 平台不可套用 Windows A2DP 能力對照表。"""
    endpoint = _endpoint(
        name="AirPods Pro",
        transport=TransportKind.BLUETOOTH_A2DP,
        company_id=0x004C,
    )
    codec = resolve_codec(endpoint, HostContext(0, INTEL), table)
    assert codec.name == "未知"
    assert codec.confidence is Confidence.UNKNOWN
    assert any("非 Windows" in reason for reason in codec.reasons)


def test_model_match_beats_vendor_match(table: CodecTable) -> None:
    """名稱對到機型時要用機型的能力，而不是退回廠商的通用清單。"""
    codecs, source = table.device_codecs("Sony WH-1000XM5", 0x012D)
    assert "LDAC" in codecs
    assert source is not None and "機型" in source


def test_radio_lookup_from_usb_vid(table: CodecTable) -> None:
    assert table.radio_for_vid(0x8087).family == "intel"
    assert table.radio_for_vid(0x0CF3).family == "qualcomm"
    assert table.radio_for_vid(None).family == "unknown"
    assert table.radio_for_vid(0xFFFF).family == "unknown"


def test_host_codecs_explain_themselves(table: CodecTable) -> None:
    codecs, reasons = table.host_codecs(HostContext(WIN11, INTEL))
    assert codecs == ["SBC", "AAC"]
    assert any("Intel" in reason and "aptX" in reason for reason in reasons)


def test_unknown_transport_does_not_pretend_to_know(table: CodecTable) -> None:
    endpoint = _endpoint(name="?", transport=TransportKind.UNKNOWN)
    codec = resolve_codec(endpoint, HostContext(WIN11, INTEL), table)
    assert codec.confidence is Confidence.UNKNOWN
