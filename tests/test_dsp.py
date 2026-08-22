import math

import numpy as np
import numpy.typing as npt
import pytest

from aurora.core.constants import ANALYSIS_FFT_SIZE, SPECTRUM_BARS
from aurora.core.dsp import (
    LevelMeter,
    RolloffAnalyzer,
    SpectrumProcessor,
    classify_rolloff,
    log_band_edges,
    mix_to_mono,
)

SAMPLE_RATE = 48000


def _sine(freq: float, seconds: float = 0.25, amplitude: float = 0.5) -> npt.NDArray[np.float32]:
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    return (np.sin(2 * np.pi * freq * t) * amplitude).astype(np.float32)


def _lowpassed_noise(cutoff_hz: float, seconds: float = 9.0) -> npt.NDArray[np.float32]:
    """磚牆低通的白噪音 —— 用來模擬有損編碼砍掉高頻的效果。"""
    rng = np.random.default_rng(1234)
    count = int(SAMPLE_RATE * seconds)
    noise = rng.standard_normal(count)
    spectrum = np.fft.rfft(noise)
    spectrum[np.fft.rfftfreq(count, 1 / SAMPLE_RATE) > cutoff_hz] = 0.0
    filtered = np.fft.irfft(spectrum, count)
    return (filtered / np.max(np.abs(filtered)) * 0.5).astype(np.float32)


# ------------------------------------------------------------------ 分頻


def test_band_edges_are_strictly_increasing() -> None:
    """低頻處多個頻段會擠在同一個分箱，必須強制錯開，否則會有寬度為零的空條。"""
    edges = log_band_edges(SAMPLE_RATE)
    assert edges.size == SPECTRUM_BARS + 1
    assert np.all(np.diff(edges) >= 1)


def test_band_edges_stay_within_nyquist() -> None:
    for rate in (8000, 16000, 44100, 48000, 96000):
        edges = log_band_edges(rate)
        assert edges[-1] <= 2048 // 2
        assert np.all(np.diff(edges) >= 1)


# ------------------------------------------------------------------ 混音


def test_mix_to_mono_averages_channels() -> None:
    interleaved = np.array([1.0, -1.0, 0.5, 0.5], dtype=np.float32)
    assert mix_to_mono(interleaved, 2).tolist() == [0.0, 0.5]


def test_mix_to_mono_discards_partial_frame() -> None:
    interleaved = np.array([1.0, 1.0, 0.2], dtype=np.float32)
    assert mix_to_mono(interleaved, 2).tolist() == [1.0]


def test_mix_to_mono_passthrough_for_mono() -> None:
    mono = np.array([0.1, 0.2], dtype=np.float32)
    assert mix_to_mono(mono, 1).tolist() == pytest.approx([0.1, 0.2])


# ------------------------------------------------------------------ 即時頻譜


def test_sine_lands_in_the_expected_band() -> None:
    processor = SpectrumProcessor(SAMPLE_RATE)
    tone = _sine(1000.0)
    for _ in range(30):  # 讓 attack 累積上來
        frame = processor.process(tone, 1 / 60)

    edges = processor.band_edges
    target_bin = 1000.0 * 2048 / SAMPLE_RATE
    expected = int(np.searchsorted(edges, target_bin) - 1)
    assert int(np.argmax(frame.bars)) == pytest.approx(expected, abs=1)


def test_silence_decays_towards_zero() -> None:
    processor = SpectrumProcessor(SAMPLE_RATE)
    for _ in range(20):
        processor.process(_sine(1000.0), 1 / 60)
    for _ in range(400):
        frame = processor.process(np.zeros(2048, dtype=np.float32), 1 / 60)
    assert max(frame.bars) < 0.05


def test_peaks_never_fall_below_bars() -> None:
    processor = SpectrumProcessor(SAMPLE_RATE)
    rng = np.random.default_rng(7)
    for _ in range(120):
        block = (rng.standard_normal(2048) * 0.3).astype(np.float32)
        frame = processor.process(block, 1 / 60)
        assert all(peak >= bar - 1e-6 for peak, bar in zip(frame.peaks, frame.bars, strict=True))


def test_frame_values_stay_normalised() -> None:
    processor = SpectrumProcessor(SAMPLE_RATE)
    loud = (_sine(440.0) * 1.9).astype(np.float32)
    for _ in range(60):
        frame = processor.process(loud, 1 / 60)
    assert all(0.0 <= value <= 1.0 for value in frame.bars)
    assert all(0.0 <= value <= 1.0 for value in frame.peaks)
    assert 0.0 <= frame.rms <= 1.0


def test_reset_clears_state() -> None:
    processor = SpectrumProcessor(SAMPLE_RATE)
    for _ in range(30):
        processor.process(_sine(1000.0), 1 / 60)
    processor.reset()
    frame = processor.process(np.zeros(2048, dtype=np.float32), 1 / 60)
    assert max(frame.bars) == 0.0


# ------------------------------------------------------------------ 頻譜截止


def test_rolloff_reports_insufficient_data_early() -> None:
    analyzer = RolloffAnalyzer(SAMPLE_RATE)
    analyzer.feed(_lowpassed_noise(16000.0, seconds=0.2))
    result = analyzer.result(lossless_container=False)
    assert not result.enough_data
    assert result.label == "資料不足"


@pytest.mark.parametrize("cutoff", [11000.0, 16000.0, 19500.0])
def test_rolloff_measures_the_real_cutoff(cutoff: float) -> None:
    analyzer = RolloffAnalyzer(SAMPLE_RATE)
    analyzer.feed(_lowpassed_noise(cutoff))
    measured = analyzer.cutoff_hz()
    assert measured is not None
    assert abs(measured - cutoff) < 600.0


def test_analyzer_ignores_silent_blocks() -> None:
    analyzer = RolloffAnalyzer(SAMPLE_RATE)
    analyzer.feed(np.zeros(ANALYSIS_FFT_SIZE * 10, dtype=np.float32))
    assert analyzer.frames == 0


def test_fake_lossless_is_flagged() -> None:
    """副檔名是 FLAC，但頻譜在 16kHz 就斷掉 → 幾乎確定是 MP3 轉檔。"""
    result = classify_rolloff(16000.0, lossless_container=True, source_sample_rate=44100)
    assert result.suspected_transcode
    assert result.estimated_kbps == 128


def test_genuine_lossless_is_not_flagged() -> None:
    result = classify_rolloff(21800.0, lossless_container=True, source_sample_rate=44100)
    assert not result.suspected_transcode
    assert result.label == "無損／透明"


def test_lossy_container_is_never_flagged_as_transcode() -> None:
    """MP3 本來就該截止，不需要警告。"""
    result = classify_rolloff(16000.0, lossless_container=False, source_sample_rate=44100)
    assert not result.suspected_transcode


def test_low_sample_rate_source_is_not_flagged() -> None:
    """8kHz 來源的 Nyquist 只有 4kHz，截止低是物理限制而非轉檔。"""
    result = classify_rolloff(3900.0, lossless_container=True, source_sample_rate=8000)
    assert not result.suspected_transcode


# --------------------------------------------------- 分析鏈自己造成的截止


def test_engine_downsampling_makes_the_measurement_inconclusive() -> None:
    """引擎被切到 24 kHz 時，12 kHz 的截止是分析鏈的天花板，不是來源的品質。

    回報過的誤診就是這一條：端點短暫報 24 kHz、引擎跟著切下去，一首 48 kHz
    的 320 kbps MP3 就被面板標成「96 kbps 以下」。
    """
    result = classify_rolloff(
        12000.0,
        lossless_container=False,
        source_sample_rate=48000,
        analysis_sample_rate=24000,
    )
    assert result.analysis_limited
    assert result.estimated_kbps is None
    assert "無法推估" in result.label


def test_genuine_lossless_is_not_accused_when_the_engine_downsamples() -> None:
    """誤報比漏報傷害大：引擎壓著量測時，不能反過來指控來源是轉檔。"""
    result = classify_rolloff(
        11900.0,
        lossless_container=True,
        source_sample_rate=96000,
        analysis_sample_rate=24000,
    )
    assert result.analysis_limited
    assert not result.suspected_transcode


def test_content_well_below_the_analysis_ceiling_is_still_judged() -> None:
    """截止離分析鏈的 Nyquist 還很遠時，量到的就是內容本身，照常下結論。"""
    result = classify_rolloff(
        6000.0,
        lossless_container=False,
        source_sample_rate=48000,
        analysis_sample_rate=24000,
    )
    assert not result.analysis_limited
    assert result.estimated_kbps == 96


def test_hi_res_source_on_a_48k_engine_is_still_called_lossless() -> None:
    """天花板落在最高級距之上時，結論仍然成立，不該退回「無法判定」。

    96 kHz 的檔案跑在 48 kHz 端點上，量到的 24 kHz 是下界 —— 而「至少到
    24 kHz」本來就足以支持「無損／透明」。這一條防的是防呆本身矯枉過正。
    """
    result = classify_rolloff(
        23900.0,
        lossless_container=True,
        source_sample_rate=96000,
        analysis_sample_rate=48000,
    )
    assert not result.analysis_limited
    assert result.label == "無損／透明"
    assert not result.suspected_transcode


def test_analysis_rate_at_or_above_source_changes_nothing() -> None:
    """引擎沒有壓低取樣率時，這道防呆不得影響任何既有判定。"""
    guarded = classify_rolloff(
        16000.0,
        lossless_container=True,
        source_sample_rate=44100,
        analysis_sample_rate=48000,
    )
    assert guarded == classify_rolloff(
        16000.0, lossless_container=True, source_sample_rate=44100
    )
    assert guarded.suspected_transcode


def test_analyzer_reports_its_own_ceiling_not_the_source_quality() -> None:
    """跑在 24 kHz 的分析器要自己知道它量不到 12 kHz 以上。"""
    analyzer = RolloffAnalyzer(24000)
    analyzer.feed(_lowpassed_noise(SAMPLE_RATE / 2))
    result = analyzer.result(lossless_container=True, source_sample_rate=48000)
    assert result.enough_data
    assert result.analysis_limited
    assert not result.suspected_transcode


# ------------------------------------------------------------------ 響度與削波


def test_full_scale_square_wave_is_one_continuous_run() -> None:
    """削波看的是振幅絕對值，所以方波換極性不算中斷 —— 整段是一次事件。"""
    block = np.concatenate(
        [np.ones(10, dtype=np.float32), -np.ones(10, dtype=np.float32)] * 5
    ).astype(np.float32)
    meter = LevelMeter()
    meter.feed(block)
    assert meter.stats().clipped_runs == 1


def test_separate_bursts_count_separately() -> None:
    block = np.concatenate(
        [np.ones(5, dtype=np.float32), np.zeros(5, dtype=np.float32)] * 3
    ).astype(np.float32)
    meter = LevelMeter()
    meter.feed(block)
    assert meter.stats().clipped_runs == 3


def test_clipping_run_shorter_than_threshold_is_ignored() -> None:
    block = np.array([1.0, 1.0, 0.0, 1.0, 1.0, 0.0], dtype=np.float32)
    meter = LevelMeter()
    meter.feed(block)
    assert meter.stats().clipped_runs == 0


def test_clipping_run_spans_block_boundary() -> None:
    """連段跨區塊必須接續，否則串流播放時會少算。"""
    meter = LevelMeter()
    meter.feed(np.array([1.0, 1.0], dtype=np.float32))
    meter.feed(np.array([1.0, 0.0], dtype=np.float32))
    assert meter.stats().clipped_runs == 1


def test_long_run_is_still_only_one_event() -> None:
    meter = LevelMeter()
    meter.feed(np.ones(100_000, dtype=np.float32))
    assert meter.stats().clipped_runs == 1


def test_level_meter_measures_sine_crest_factor() -> None:
    """正弦波的波峰因數理論值是 3.01 dB。"""
    meter = LevelMeter()
    meter.feed(_sine(440.0, seconds=1.0, amplitude=1.0))
    stats = meter.stats()
    assert stats.peak_db == pytest.approx(0.0, abs=0.1)
    assert stats.dynamic_range_db == pytest.approx(20 * math.log10(math.sqrt(2)), abs=0.1)
    assert stats.clipped_runs == 0


def test_empty_meter_is_safe() -> None:
    stats = LevelMeter().stats()
    assert stats.clipped_runs == 0
    assert stats.dynamic_range_db == 0.0


def test_meter_reset_clears_accumulated_state() -> None:
    meter = LevelMeter()
    meter.feed(np.ones(50, dtype=np.float32))
    meter.reset()
    assert meter.stats().clipped_runs == 0
