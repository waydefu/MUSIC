import numpy as np
import numpy.typing as npt

from aurora.core.onset import OnsetDetector

SAMPLE_RATE = 48000


def _click_track(times: list[float], seconds: float = 3.0) -> npt.NDArray[np.float32]:
    """在指定時間放入短促的噪音爆點，其餘為靜音。"""
    rng = np.random.default_rng(99)
    signal = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    burst = int(SAMPLE_RATE * 0.02)
    envelope = np.linspace(1.0, 0.0, burst, dtype=np.float32) ** 2
    for moment in times:
        start = int(moment * SAMPLE_RATE)
        noise = rng.standard_normal(burst).astype(np.float32)
        signal[start : start + burst] += noise * envelope * 0.8
    return signal


def test_detects_evenly_spaced_clicks() -> None:
    expected = [0.5, 1.0, 1.5, 2.0, 2.5]
    detector = OnsetDetector(SAMPLE_RATE)
    detected = detector.feed(_click_track(expected))

    assert len(detected) == len(expected)
    for actual, want in zip(detected, expected, strict=True):
        # 偵測點落在包含該爆點的分析框起點，最多早 fft_size / sr ≈ 21ms
        assert -0.03 <= actual - want <= 0.005


def test_silence_produces_no_onsets() -> None:
    detector = OnsetDetector(SAMPLE_RATE)
    assert detector.feed(np.zeros(SAMPLE_RATE * 2, dtype=np.float32)) == []


def test_steady_tone_does_not_keep_triggering() -> None:
    """持續的音不是鼓點。起音處觸發一次是合理的，之後應該安靜。"""
    t = np.arange(SAMPLE_RATE * 2, dtype=np.float32) / SAMPLE_RATE
    tone = (np.sin(2 * np.pi * 220.0 * t) * 0.6).astype(np.float32)
    detector = OnsetDetector(SAMPLE_RATE)
    assert len(detector.feed(tone)) <= 1


def test_streaming_in_chunks_matches_single_shot() -> None:
    """一次餵完與分批餵入必須得到相同結果，否則音訊回呼裡就不能用。"""
    signal = _click_track([0.4, 0.9, 1.4, 1.9])

    single = OnsetDetector(SAMPLE_RATE).feed(signal)

    chunked_detector = OnsetDetector(SAMPLE_RATE)
    chunked: list[float] = []
    for start in range(0, signal.size, 1024):
        chunked.extend(chunked_detector.feed(signal[start : start + 1024]))

    assert single == chunked


def test_reset_restores_initial_state() -> None:
    detector = OnsetDetector(SAMPLE_RATE)
    detector.feed(_click_track([0.5, 1.0]))
    detector.reset()
    assert detector.feed(np.zeros(SAMPLE_RATE, dtype=np.float32)) == []


def test_minimum_interval_prevents_double_triggering() -> None:
    """同一個鼓點不該被連續兩幀各觸發一次。"""
    detector = OnsetDetector(SAMPLE_RATE)
    detected = detector.feed(_click_track([1.0], seconds=2.0))
    assert len(detected) == 1
