"""把各路資訊組裝成一份完整的訊號鏈報告。

輸出長這樣（由 QualityPanel 呈現）::

    來源  FLAC · 44.1 kHz / 16-bit / 立體聲 · 無損        ✓實測
      ↓   解碼為 32-bit float
    引擎  44.1 kHz → 48 kHz                      ⚠ 有重取樣
      ↓
    輸出  AirPods Pro #3 · 藍牙 A2DP · 立體聲              ✓實測
    端點  48 kHz / 16-bit                                ✓實測
    編碼  AAC                                            ⓘ推定
    量測  頻譜截止 20.8 kHz → 與無損相符                    ✓實測

純邏輯，可對造出來的 EndpointInfo 直接斷言輸出內容。
"""

from __future__ import annotations

from aurora.core.models import (
    AudioFormat,
    ChainStage,
    CodecInfo,
    Confidence,
    EndpointInfo,
    LevelStats,
    QualityReport,
    RolloffResult,
    Track,
    TransportKind,
)

#: 星等扣分表。滿分 5 星，扣完夾在 1..5。
_PENALTY_HFP = 3
_PENALTY_A2DP = 1
_PENALTY_LOSSY_SOURCE = 1
_PENALTY_RESAMPLE = 1
_PENALTY_TRANSCODE = 1
_PENALTY_CLIPPING = 1

#: 削波樣本數超過這個值才扣分 —— 個位數的滿刻度樣本多半是母帶本來就這樣。
_CLIPPING_TOLERANCE = 8


def _source_stage(track: Track | None) -> ChainStage:
    if track is None or track.fmt is None:
        return ChainStage("來源", "尚未載入曲目", Confidence.UNKNOWN)

    parts = [track.codec.upper() or "未知格式", track.fmt.describe()]
    parts.append("無損" if track.lossless else "有損")
    if track.bitrate_kbps:
        parts.append(f"{track.bitrate_kbps} kbps")
    return ChainStage("來源", " · ".join(parts))


def _engine_stage(source: AudioFormat | None, engine: AudioFormat | None) -> ChainStage:
    if engine is None:
        return ChainStage("引擎", "尚未啟動", Confidence.UNKNOWN)

    if source is None:
        return ChainStage("引擎", f"{engine.sample_rate / 1000:g} kHz / 32-bit float")

    if source.sample_rate == engine.sample_rate:
        return ChainStage("引擎", f"{engine.sample_rate / 1000:g} kHz · 未重取樣")

    return ChainStage(
        "引擎",
        f"{source.sample_rate / 1000:g} kHz → {engine.sample_rate / 1000:g} kHz",
        warn=True,
    )


def _output_stage(endpoint: EndpointInfo | None) -> ChainStage:
    if endpoint is None:
        return ChainStage("輸出", "找不到輸出裝置", Confidence.UNKNOWN, warn=True)

    fmt = endpoint.effective_format
    channels = fmt.channel_label if fmt else "未知聲道"
    return ChainStage(
        "輸出",
        f"{endpoint.friendly_name} · {endpoint.transport.label} · {channels}",
        warn=endpoint.transport is TransportKind.BLUETOOTH_HFP,
    )


def _endpoint_stage(endpoint: EndpointInfo | None) -> ChainStage:
    fmt = endpoint.effective_format if endpoint else None
    if fmt is None:
        return ChainStage("端點", "讀不到端點格式", Confidence.UNKNOWN)
    return ChainStage("端點", fmt.describe())


def _codec_stage(codec: CodecInfo) -> ChainStage:
    return ChainStage("編碼", codec.name, codec.confidence)


def _measurement_stage(rolloff: RolloffResult, levels: LevelStats | None) -> ChainStage:
    if not rolloff.enough_data:
        return ChainStage("量測", "累積樣本不足，尚無法判斷", Confidence.UNKNOWN)

    detail = f"頻譜截止 {(rolloff.cutoff_hz or 0) / 1000:.1f} kHz → {rolloff.label}"
    if levels is not None and levels.clipped_runs:
        detail += f" · 削波 {levels.clipped_runs} 處"
    return ChainStage("量測", detail, warn=rolloff.suspected_transcode)


def _collect_warnings(
    endpoint: EndpointInfo | None,
    source: AudioFormat | None,
    engine: AudioFormat | None,
    rolloff: RolloffResult,
    levels: LevelStats | None,
    hfp_also_connected: bool,
) -> list[str]:
    warnings: list[str] = []

    if endpoint is not None and endpoint.transport is TransportKind.BLUETOOTH_HFP:
        warnings.append(
            "目前走的是藍牙通話模式（HFP），頻寬只有音樂模式的一小部分，"
            "音質會嚴重受限。關閉正在佔用麥克風的程式即可切回 A2DP。"
        )
    elif hfp_also_connected:
        warnings.append(
            "偵測到同一支耳機的 Hands-Free 端點也在連線。"
            "若音質突然變差，多半是被某個程式搶去當通話裝置了。"
        )

    if source is not None and engine is not None and source.sample_rate != engine.sample_rate:
        warnings.append(
            f"來源 {source.sample_rate} Hz 與輸出端點 {engine.sample_rate} Hz 不一致，"
            "訊號經過一次重取樣。"
        )

    if rolloff.suspected_transcode:
        warnings.append(
            f"容器宣稱無損，但實測頻譜在 {(rolloff.cutoff_hz or 0) / 1000:.1f} kHz 就截止了 —— "
            "這個檔案很可能是由有損來源轉檔而來。"
        )

    if levels is not None and levels.clipped_runs > _CLIPPING_TOLERANCE:
        warnings.append(f"偵測到 {levels.clipped_runs} 處削波，音量峰值已超出滿刻度。")

    return warnings


def _rate(
    endpoint: EndpointInfo | None,
    track: Track | None,
    source: AudioFormat | None,
    engine: AudioFormat | None,
    rolloff: RolloffResult,
    levels: LevelStats | None,
) -> int:
    penalty = 0

    if endpoint is not None:
        if endpoint.transport is TransportKind.BLUETOOTH_HFP:
            penalty += _PENALTY_HFP
        elif endpoint.transport is TransportKind.BLUETOOTH_A2DP:
            penalty += _PENALTY_A2DP

    if track is not None and not track.lossless:
        penalty += _PENALTY_LOSSY_SOURCE

    if source is not None and engine is not None and source.sample_rate != engine.sample_rate:
        penalty += _PENALTY_RESAMPLE

    if rolloff.suspected_transcode:
        penalty += _PENALTY_TRANSCODE

    if levels is not None and levels.clipped_runs > _CLIPPING_TOLERANCE:
        penalty += _PENALTY_CLIPPING

    return max(1, min(5, 5 - penalty))


def build_report(
    *,
    track: Track | None,
    engine_format: AudioFormat | None,
    endpoint: EndpointInfo | None,
    codec: CodecInfo,
    rolloff: RolloffResult,
    levels: LevelStats | None = None,
    hfp_also_connected: bool = False,
) -> QualityReport:
    """組裝完整報告。這是 QualityPanel 唯一需要呼叫的入口。"""
    source = track.fmt if track else None

    stages = (
        _source_stage(track),
        _engine_stage(source, engine_format),
        _output_stage(endpoint),
        _endpoint_stage(endpoint),
        _codec_stage(codec),
        _measurement_stage(rolloff, levels),
    )
    warnings = _collect_warnings(
        endpoint, source, engine_format, rolloff, levels, hfp_also_connected
    )

    return QualityReport(
        stages=stages,
        codec=codec,
        rolloff=rolloff,
        levels=levels,
        stars=_rate(endpoint, track, source, engine_format, rolloff, levels),
        warnings=tuple(warnings),
    )
