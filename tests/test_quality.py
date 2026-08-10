from aurora.core.dsp import classify_rolloff
from aurora.core.models import (
    AudioFormat,
    CodecInfo,
    Confidence,
    EndpointInfo,
    LevelStats,
    RolloffResult,
    Track,
    TransportKind,
)
from aurora.core.quality import build_report

CD_FORMAT = AudioFormat(44100, 2, 16)
ENGINE_48K = AudioFormat(48000, 2, 32, is_float=True)

AAC_CODEC = CodecInfo("AAC", Confidence.INFERRED, ("Apple 裝置",))
PCM_CODEC = CodecInfo("無壓縮 PCM", Confidence.MEASURED, ())
NO_DATA = RolloffResult(enough_data=False)


def _flac() -> Track:
    return Track(
        path=r"D:\music\song.flac",
        title="測試曲",
        fmt=CD_FORMAT,
        codec="flac",
        lossless=True,
        bitrate_kbps=921,
    )


def _mp3() -> Track:
    return Track(
        path=r"D:\music\song.mp3",
        title="測試曲",
        fmt=CD_FORMAT,
        codec="mp3",
        lossless=False,
        bitrate_kbps=320,
    )


def _endpoint(
    transport: TransportKind, sample_rate: int = 48000, channels: int = 2
) -> EndpointInfo:
    return EndpointInfo(
        id="{test}",
        friendly_name="AirPods Pro",
        description="Headphones",
        enumerator="BTHENUM",
        instance_id="BTHENUM\\test",
        transport=transport,
        device_format=AudioFormat(sample_rate, channels, 16),
    )


def _labels(report: object) -> dict[str, str]:
    return {stage.label: stage.detail for stage in report.stages}  # type: ignore[attr-defined]


# ------------------------------------------------------------------ 訊號鏈


def test_chain_has_all_six_stages() -> None:
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.BLUETOOTH_A2DP),
        codec=AAC_CODEC,
        rolloff=NO_DATA,
    )
    assert [stage.label for stage in report.stages] == [
        "來源",
        "引擎",
        "輸出",
        "端點",
        "編碼",
        "量測",
    ]


def test_source_stage_describes_the_file() -> None:
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.WIRED),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
    )
    source = _labels(report)["來源"]
    assert "FLAC" in source and "44.1 kHz" in source and "無損" in source


def test_resampling_is_flagged() -> None:
    """44.1kHz 來源丟到 48kHz 端點，中間必然有一次重取樣。"""
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.WIRED),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
    )
    engine_stage = next(stage for stage in report.stages if stage.label == "引擎")
    assert engine_stage.warn
    assert "44.1 kHz → 48 kHz" in engine_stage.detail
    assert any("重取樣" in warning for warning in report.warnings)


def test_matched_rates_are_not_flagged() -> None:
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
    )
    engine_stage = next(stage for stage in report.stages if stage.label == "引擎")
    assert not engine_stage.warn
    assert not any("重取樣" in warning for warning in report.warnings)


def test_codec_stage_carries_its_confidence() -> None:
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.BLUETOOTH_A2DP),
        codec=AAC_CODEC,
        rolloff=NO_DATA,
    )
    codec_stage = next(stage for stage in report.stages if stage.label == "編碼")
    assert codec_stage.confidence is Confidence.INFERRED
    assert codec_stage.confidence.badge == "ⓘ推定"


# ------------------------------------------------------------------ 警告


def test_hfp_produces_a_prominent_warning() -> None:
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(16000, 1, 32, is_float=True),
        endpoint=_endpoint(TransportKind.BLUETOOTH_HFP, sample_rate=16000, channels=1),
        codec=CodecInfo("mSBC", Confidence.DERIVED, ()),
        rolloff=NO_DATA,
    )
    assert any("通話模式" in warning for warning in report.warnings)
    assert report.stars <= 2


def test_hfp_also_connected_warns_even_while_on_a2dp() -> None:
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.BLUETOOTH_A2DP),
        codec=AAC_CODEC,
        rolloff=NO_DATA,
        hfp_also_connected=True,
    )
    assert any("Hands-Free" in warning for warning in report.warnings)


def test_fake_lossless_warning_quotes_the_measured_cutoff() -> None:
    rolloff = classify_rolloff(16000.0, lossless_container=True, source_sample_rate=44100)
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=rolloff,
    )
    assert any("轉檔" in warning and "16.0 kHz" in warning for warning in report.warnings)


def test_minor_clipping_is_tolerated() -> None:
    """個位數的滿刻度樣本多半是母帶本來就這樣，不值得警告。"""
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
        levels=LevelStats(-14.0, -0.1, 13.9, clipped_runs=3),
    )
    assert not any("削波" in warning for warning in report.warnings)


def test_heavy_clipping_is_reported() -> None:
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
        levels=LevelStats(-8.0, 0.0, 8.0, clipped_runs=4200),
    )
    assert any("削波" in warning for warning in report.warnings)


# ------------------------------------------------------------------ 評級


def test_wired_lossless_matched_rate_is_five_stars() -> None:
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=classify_rolloff(21800.0, lossless_container=True, source_sample_rate=44100),
    )
    assert report.stars == 5
    assert report.warnings == ()


def test_rating_degrades_down_the_chain() -> None:
    """有線無損 > 藍牙無損 > 藍牙有損 > 通話模式。"""

    def stars(endpoint: EndpointInfo, track: Track, engine: AudioFormat) -> int:
        return build_report(
            track=track,
            engine_format=engine,
            endpoint=endpoint,
            codec=AAC_CODEC,
            rolloff=NO_DATA,
        ).stars

    wired = stars(
        _endpoint(TransportKind.WIRED, 44100), _flac(), AudioFormat(44100, 2, 32, is_float=True)
    )
    a2dp_lossless = stars(
        _endpoint(TransportKind.BLUETOOTH_A2DP, 44100),
        _flac(),
        AudioFormat(44100, 2, 32, is_float=True),
    )
    a2dp_lossy = stars(
        _endpoint(TransportKind.BLUETOOTH_A2DP, 44100),
        _mp3(),
        AudioFormat(44100, 2, 32, is_float=True),
    )
    hfp = stars(
        _endpoint(TransportKind.BLUETOOTH_HFP, 16000, 1),
        _mp3(),
        AudioFormat(16000, 1, 32, is_float=True),
    )

    assert wired > a2dp_lossless > a2dp_lossy > hfp


def test_stars_stay_within_range() -> None:
    report = build_report(
        track=_mp3(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.BLUETOOTH_HFP, 8000, 1),
        codec=CodecInfo("CVSD", Confidence.DERIVED, ()),
        rolloff=classify_rolloff(3500.0, lossless_container=False, source_sample_rate=8000),
        levels=LevelStats(-6.0, 0.0, 6.0, clipped_runs=9999),
    )
    assert 1 <= report.stars <= 5


# ------------------------------------------------------------------ 邊界


def test_no_track_does_not_crash() -> None:
    report = build_report(
        track=None,
        engine_format=None,
        endpoint=None,
        codec=CodecInfo("未知", Confidence.UNKNOWN, ()),
        rolloff=NO_DATA,
    )
    assert _labels(report)["來源"] == "尚未載入曲目"
    assert _labels(report)["輸出"] == "找不到輸出裝置"
    assert report.stars >= 1


def test_measurement_stage_says_insufficient_before_enough_samples() -> None:
    report = build_report(
        track=_flac(),
        engine_format=ENGINE_48K,
        endpoint=_endpoint(TransportKind.WIRED),
        codec=PCM_CODEC,
        rolloff=NO_DATA,
    )
    measurement = next(stage for stage in report.stages if stage.label == "量測")
    assert "不足" in measurement.detail
    assert measurement.confidence is Confidence.UNKNOWN


def test_measurement_stage_reports_cutoff_once_available() -> None:
    report = build_report(
        track=_flac(),
        engine_format=AudioFormat(44100, 2, 32, is_float=True),
        endpoint=_endpoint(TransportKind.WIRED, sample_rate=44100),
        codec=PCM_CODEC,
        rolloff=classify_rolloff(20800.0, lossless_container=True, source_sample_rate=44100),
    )
    measurement = next(stage for stage in report.stages if stage.label == "量測")
    assert "20.8 kHz" in measurement.detail
    assert not measurement.warn
    # 20.8 kHz 在無損容器裡是完全正常的收斂，不該被當成轉檔而扣分
    assert report.stars == 5
