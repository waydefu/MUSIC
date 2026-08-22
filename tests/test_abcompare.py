"""對齊 A/B 比較的測試。

這裡驗的是「比較本身是公平的」。全部用合成訊號，因為要斷言的是精確的
數值關係（延遲多少框、音量差多少 dB），真實音檔做不到這種確定性。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from aurora.core.abcompare import (
    align,
    compare,
    estimate_latency_frames,
    match_gain_db,
)
from aurora.core.dsp_graph import AudioProcessor, DspGraph

FloatArray = npt.NDArray[np.float32]

CHANNELS = 2
RATE = 48000


def _tone(frames: int, freq: float = 440.0, amplitude: float = 0.5) -> FloatArray:
    """交錯立體聲正弦波。左右給一點差異，才驗得出聲道處理有沒有出錯。

    **不要拿它量延遲。** 純音是週期性的，互相關在每個週期都有等高峰，
    延遲無法唯一決定 —— 那正是 :func:`estimate_latency_frames` 會回 None
    的情況。要量延遲請用 :func:`_program`。
    """
    t = np.arange(frames, dtype=np.float64) / RATE
    left = np.sin(2 * np.pi * freq * t) * amplitude
    right = np.sin(2 * np.pi * freq * t * 1.5) * amplitude * 0.8
    return np.stack([left, right], axis=1).astype(np.float32).reshape(-1)


def _program(frames: int) -> FloatArray:
    """不規則的節目訊號：噪音鋪底 + 低音 + 瞬態。

    延遲量測需要非週期訊號。真實音樂本來就是這樣，這裡只是用固定種子
    把它變成確定性的（做法與 tools/make_test_audio.py 一致）。
    """
    rng = np.random.default_rng(4242)
    t = np.arange(frames, dtype=np.float64) / RATE
    mono = rng.standard_normal(frames) * 0.15 + np.sin(2 * np.pi * 110.0 * t) * 0.2
    for start in range(0, frames, RATE // 4):  # 每 0.25 秒一個瞬態
        burst = min(600, frames - start)
        if burst <= 0:
            break
        mono[start : start + burst] += rng.standard_normal(burst) * np.exp(
            -np.linspace(0.0, 8.0, burst)
        )
    mono /= np.abs(mono).max() * 1.1
    right = np.roll(mono, 32) * 0.9
    return np.stack([mono, right], axis=1).astype(np.float32).reshape(-1)


def _delay(signal: FloatArray, frames: int, channels: int = CHANNELS) -> FloatArray:
    """把訊號往後推 ``frames`` 框，前面補零 —— 模擬處理器的演算法延遲。"""
    return np.concatenate([np.zeros(frames * channels, dtype=np.float32), signal])


# ------------------------------------------------------------------ 對齊


def test_align_removes_the_declared_latency() -> None:
    reference = _tone(4096)
    processed = _delay(reference, 128)

    ref, proc = align(reference, processed, 128, CHANNELS)
    assert np.allclose(ref, proc)


def test_align_without_latency_is_a_no_op() -> None:
    reference = _tone(1024)
    ref, proc = align(reference, reference, 0, CHANNELS)
    assert np.array_equal(ref, reference)
    assert np.array_equal(proc, reference)


def test_align_never_leaves_a_partial_frame() -> None:
    """截半框會讓左右聲道錯位，後面所有計算都會歪掉。"""
    reference = _tone(1000)
    processed = _delay(reference, 7)[:-3]  # 刻意留下不整除的長度
    ref, proc = align(reference, processed, 7, CHANNELS)
    assert ref.size % CHANNELS == 0
    assert ref.size == proc.size


def test_align_rejects_negative_latency() -> None:
    """處理器不可能讓訊號提前。負值一定是算錯了，要當場爆掉。"""
    with pytest.raises(ValueError, match="latency_frames"):
        align(_tone(64), _tone(64), -1, CHANNELS)


# ------------------------------------------------------------------ 延遲實測


@pytest.mark.parametrize("latency", [0, 1, 64, 512, 2048])
def test_estimated_latency_matches_the_real_delay(latency: int) -> None:
    """這條是章程 §1.2「不只看 frame count」的機器版本。"""
    reference = _program(32768)
    processed = _delay(reference, latency)
    assert estimate_latency_frames(reference, processed, CHANNELS) == latency


def test_estimate_returns_none_on_silence() -> None:
    """量不出來就誠實回 None。猜一個延遲比沒有延遲更難除錯。"""
    silence = np.zeros(8192 * CHANNELS, dtype=np.float32)
    assert estimate_latency_frames(silence, silence, CHANNELS) is None


def test_estimate_refuses_to_guess_on_a_periodic_signal() -> None:
    """純音的延遲在數學上無法唯一決定，這時必須回 None 而不是挑一個峰值。

    互相關在每個週期都有等高峰。挑一個交差會給出「看起來精確、實際上
    隨機」的答案 —— 那比沒有答案更糟，因為它會讓下游的對齊全部歪掉，
    而且沒有任何症狀指向這裡。
    """
    reference = _tone(32768)
    processed = _delay(reference, 300)
    assert estimate_latency_frames(reference, processed, CHANNELS) is None


def test_estimate_returns_none_when_signals_are_unrelated() -> None:
    rng = np.random.default_rng(7)
    reference = _program(16384)
    noise = rng.standard_normal(reference.size).astype(np.float32) * 0.5
    assert estimate_latency_frames(reference, noise, CHANNELS) is None


# ------------------------------------------------------------------ 音量匹配


@pytest.mark.parametrize("gain_db", [-12.0, -3.0, 3.0, 6.0])
def test_match_gain_recovers_a_known_offset(gain_db: float) -> None:
    reference = _tone(8192)
    louder = reference * (10.0 ** (gain_db / 20.0))
    # processed 大了 gain_db，所以要 -gain_db 才對得回去。
    assert match_gain_db(reference, louder) == pytest.approx(-gain_db, abs=0.01)


def test_match_gain_is_zero_for_silence() -> None:
    silence = np.zeros(1024, dtype=np.float32)
    assert match_gain_db(silence, silence) == 0.0


# ------------------------------------------------------------------ 完整比較


def test_identical_signals_compare_as_identical() -> None:
    reference = _tone(8192)
    result = compare(reference, reference, latency_frames=0, channels=CHANNELS)

    assert result.frames == 8192
    assert result.applied_gain_db == pytest.approx(0.0, abs=1e-6)
    assert result.rms_delta_db == pytest.approx(0.0, abs=1e-6)
    assert result.correlation == pytest.approx(1.0, abs=1e-6)
    assert result.level_matched


def test_pure_gain_change_is_fully_absorbed_by_level_matching() -> None:
    """只有音量差時，匹配後應該完全一樣 —— 這正是 A/B 要消除的因素。"""
    reference = _tone(8192)
    louder = reference * 2.0

    result = compare(reference, louder, latency_frames=0, channels=CHANNELS)
    assert result.applied_gain_db == pytest.approx(-6.02, abs=0.05)
    assert result.rms_delta_db == pytest.approx(0.0, abs=1e-6)
    assert result.correlation == pytest.approx(1.0, abs=1e-6)
    assert result.level_matched


def test_delayed_signal_compares_as_identical_once_aligned() -> None:
    reference = _program(16384)
    processed = _delay(reference, 256)

    misaligned = compare(reference, processed, latency_frames=0, channels=CHANNELS)
    aligned = compare(reference, processed, latency_frames=256, channels=CHANNELS)

    # 沒對齊時相關性明顯掉下來；對齊後回到 1。
    assert aligned.correlation > misaligned.correlation
    assert aligned.correlation == pytest.approx(1.0, abs=1e-6)


def test_level_matched_flag_follows_the_charter_threshold() -> None:
    """章程 §15：A/B 的 RMS 差要 ≤0.5 dB。"""
    reference = _tone(8192)
    result = compare(reference, reference * 4.0, latency_frames=0, channels=CHANNELS)
    # 音量匹配之後殘差應該遠小於門檻，不管原本差多少。
    assert abs(result.rms_delta_db) < 0.01
    assert result.level_matched


def test_empty_overlap_does_not_crash() -> None:
    """延遲比訊號本身還長時要回空結果，不是拋例外。"""
    reference = _tone(64)
    result = compare(reference, reference, latency_frames=999, channels=CHANNELS)
    assert result.frames == 0


# ------------------------------------------------------------------ 與 graph 串起來


class DelayProcessor(AudioProcessor):
    """申報並實作固定延遲。用來驗證 A/B 與 graph 的延遲帳對得上。"""

    def __init__(self, frames: int, *, declared: int | None = None) -> None:
        self._frames = frames
        self._declared = frames if declared is None else declared
        self._tail = np.zeros(0, dtype=np.float32)
        self._channels = CHANNELS

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._channels = channels
        self._tail = np.zeros(self._frames * channels, dtype=np.float32)

    def process(self, buf: FloatArray) -> None:
        combined = np.concatenate([self._tail, buf])
        buf[:] = combined[: buf.size]
        self._tail = combined[buf.size :]

    def reset(self) -> None:
        self._tail = np.zeros(self._frames * self._channels, dtype=np.float32)

    @property
    def latency_frames(self) -> int:
        return self._declared


def _render(graph: DspGraph, source: FloatArray, block_frames: int = 1024) -> FloatArray:
    """把訊號分塊餵過 graph，模擬回呼。"""
    out = source.copy()
    step = block_frames * CHANNELS
    for start in range(0, out.size, step):
        graph.process(out[start : start + step])
    return out


def test_declared_latency_matches_measured_latency() -> None:
    """處理器申報的延遲要和實際造成的延遲相符。

    申報錯了不會有任何症狀，直到歌詞對不上或 A/V 歪掉才發現 ——
    這條測試把它變成當場就會紅的東西。
    """
    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, 4096)
    graph.set_stages((DelayProcessor(256),))

    source = _program(32768)
    processed = _render(graph, source)

    measured = estimate_latency_frames(source, processed, CHANNELS)
    assert measured == graph.latency_frames == 256


def test_a_lying_processor_is_caught() -> None:
    """申報 0 但實際延遲 128 的處理器要被抓出來。"""
    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, 4096)
    graph.set_stages((DelayProcessor(128, declared=0),))

    source = _program(32768)
    processed = _render(graph, source)

    assert graph.latency_frames == 0
    assert estimate_latency_frames(source, processed, CHANNELS) == 128
