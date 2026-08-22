"""藍牙編碼判定。

三種確信等級，UI 必須照實區分：

``MEASURED``
    有線／內建裝置 —— 根本沒有藍牙編碼這回事，直接說「無壓縮傳輸」。
``DERIVED``
    HFP 通話模式 —— 端點取樣率與編碼是一對一關係（8k=CVSD、16k=mSBC、
    32k=LC3-SWB），這是推導不是猜測。
``INFERRED``
    A2DP 音樂模式 —— Windows 不提供這項資訊，只能由「耳機支援的編碼」∩
    「本機 Windows 與藍牙晶片支援的編碼」取優先序最高者，並附上推理依據。

對照資料全在 ``data/bt_codecs.toml``，新增機型不必改這裡。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from aurora.core.models import AudioFormat, CodecInfo, Confidence, EndpointInfo, TransportKind
from aurora.core.paths import data_file


@dataclass(frozen=True, slots=True)
class RadioInfo:
    """本機藍牙晶片。aptX 只在 Qualcomm 家族上才可能出現。"""

    usb_vid: int | None = None
    name: str = "未知"
    family: str = "unknown"


@dataclass(frozen=True, slots=True)
class HostContext:
    """做推定時需要知道的本機環境。"""

    windows_build: int
    radio: RadioInfo


class CodecTable:
    """``bt_codecs.toml`` 的記憶體表示。"""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._priority: list[str] = list(raw.get("meta", {}).get("priority", []))
        windows = raw.get("windows", {})
        self._windows_base: list[str] = list(windows.get("base", ["SBC"]))
        self._windows_tiers: list[dict[str, Any]] = list(windows.get("tier", []))
        self._radio_dependent: dict[str, str] = dict(windows.get("radio_dependent", {}))
        self._radios: list[dict[str, Any]] = list(raw.get("radio", []))
        self._vendors: list[dict[str, Any]] = list(raw.get("vendor", []))
        self._models: list[dict[str, Any]] = list(raw.get("model", []))
        self._hfp: list[dict[str, Any]] = list(raw.get("hfp", []))

    # ------------------------------------------------------------ 載入

    @classmethod
    def load(cls, path: Path | None = None) -> CodecTable:
        target = path or data_file("bt_codecs.toml")
        with target.open("rb") as handle:
            return cls(tomllib.load(handle))

    # ------------------------------------------------------------ 查表

    def radio_for_vid(self, usb_vid: int | None) -> RadioInfo:
        if usb_vid is None:
            return RadioInfo()
        for entry in self._radios:
            if int(entry["usb_vid"]) == usb_vid:
                return RadioInfo(usb_vid, str(entry["name"]), str(entry.get("family", "unknown")))
        return RadioInfo(usb_vid, f"未知晶片 (VID {usb_vid:04X})", "unknown")

    def host_codecs(self, context: HostContext) -> tuple[list[str], list[str]]:
        """回傳（本機支援的編碼, 推理依據）。"""
        codecs = list(self._windows_base)
        reasons = [f"Windows 保證支援 {'／'.join(self._windows_base)}"]

        for tier in self._windows_tiers:
            if context.windows_build >= int(tier["min_build"]):
                codecs.extend(str(item) for item in tier["codecs"])
                reasons.append(str(tier.get("label", "")))

        for codec, required_family in self._radio_dependent.items():
            if context.radio.family == required_family:
                codecs.append(codec)
                reasons.append(f"{context.radio.name} 晶片可支援 {codec}")
            else:
                reasons.append(f"{context.radio.name} 晶片非 {required_family}，無 {codec}")

        return list(dict.fromkeys(codecs)), [item for item in reasons if item]

    def device_codecs(self, name: str, company_id: int | None) -> tuple[list[str], str | None]:
        """回傳（裝置支援的編碼, 比對到的來源說明）。機型優先於廠商。"""
        lowered = name.lower()
        for entry in self._models:
            if str(entry["match"]).lower() in lowered:
                return [str(item) for item in entry["codecs"]], f"機型 {entry['name']}"

        if company_id is not None:
            for entry in self._vendors:
                if int(entry["company_id"]) == company_id:
                    return (
                        [str(item) for item in entry["codecs"]],
                        f"{entry['name']} 裝置（公司代碼 {company_id:04X}）",
                    )
        return [], None

    def hfp_codec(self, sample_rate: int) -> tuple[str, str] | None:
        for entry in self._hfp:
            if int(entry["sample_rate"]) == sample_rate:
                return str(entry["codec"]), str(entry.get("label", ""))
        return None

    def rank(self, codec: str) -> int:
        """優先序索引，數字小的較優先。表上沒有的排最後。"""
        try:
            return self._priority.index(codec)
        except ValueError:
            return len(self._priority)


@lru_cache(maxsize=1)
def default_table() -> CodecTable:
    """全域共用的對照表。檔案不變就只讀一次。"""
    return CodecTable.load()


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------


def derive_hfp_codec(fmt: AudioFormat | None, table: CodecTable) -> CodecInfo:
    """HFP 的編碼由端點格式唯一決定，屬於推導而非推定。"""
    if fmt is None:
        return CodecInfo("未知", Confidence.UNKNOWN, ("讀不到端點格式",))

    matched = table.hfp_codec(fmt.sample_rate)
    if matched is None:
        return CodecInfo(
            "未知 HFP 編碼",
            Confidence.UNKNOWN,
            (f"端點 {fmt.sample_rate} Hz 不在已知的 HFP 取樣率表中",),
        )

    codec, label = matched
    return CodecInfo(
        codec,
        Confidence.DERIVED,
        (
            f"HFP 端點 {fmt.sample_rate} Hz / {fmt.channel_label} ⇒ {codec}（{label}）",
            "取樣率與 HFP 編碼是一對一關係，非推測",
        ),
    )


def infer_a2dp_codec(
    device_name: str,
    company_id: int | None,
    context: HostContext,
    table: CodecTable,
) -> CodecInfo:
    """A2DP 編碼推定：裝置能力 ∩ 本機能力，取優先序最高者。"""
    host, host_reasons = table.host_codecs(context)
    device, device_source = table.device_codecs(device_name, company_id)

    if not device:
        # 裝置能力不明。SBC 是 A2DP 強制編碼所以一定有；AAC 只能說「可能」。
        fallback = "SBC"
        if "AAC" in host:
            fallback = "SBC 或 AAC"
        return CodecInfo(
            fallback,
            Confidence.INFERRED,
            (
                "對照表中沒有這台裝置，無法得知它支援哪些編碼",
                *host_reasons,
                "SBC 是 A2DP 強制編碼，必定可用",
            ),
        )

    common = [codec for codec in device if codec in host]
    dropped = [codec for codec in device if codec not in host]

    reasons: list[str] = []
    if device_source:
        reasons.append(f"{device_source} 支援 {'／'.join(device)}")
    reasons.extend(host_reasons)
    if dropped:
        reasons.append(f"{'／'.join(dropped)} 不在本機支援範圍內，已排除")

    if not common:
        return CodecInfo(
            "SBC",
            Confidence.INFERRED,
            (*reasons, "雙方沒有共同的進階編碼，只能退回強制的 SBC"),
        )

    winner = min(common, key=table.rank)
    return CodecInfo(winner, Confidence.INFERRED, tuple(reasons))


def resolve_codec(
    endpoint: EndpointInfo,
    context: HostContext,
    table: CodecTable | None = None,
) -> CodecInfo:
    """依傳輸型態分派到對應的判定路徑。這是外部唯一需要呼叫的入口。"""
    active = table or default_table()

    if endpoint.transport is TransportKind.WIRED:
        return CodecInfo(
            "無壓縮 PCM",
            Confidence.MEASURED,
            ("有線／內建裝置，音訊未經藍牙編碼壓縮",),
        )

    if endpoint.transport is TransportKind.BLUETOOTH_HFP:
        return derive_hfp_codec(endpoint.effective_format, active)

    if endpoint.transport is TransportKind.BLUETOOTH_A2DP:
        # A2DP 的對照表只描述 Windows 與其藍牙晶片能力；其他平台不能借用它猜測。
        if context.windows_build <= 0:
            return CodecInfo(
                "未知",
                Confidence.UNKNOWN,
                ("非 Windows 主機沒有可用的 A2DP 編碼推定依據",),
            )
        return infer_a2dp_codec(
            endpoint.friendly_name,
            endpoint.company_id,
            context,
            active,
        )

    return CodecInfo("未知", Confidence.UNKNOWN, ("無法判斷輸出裝置的傳輸型態",))
