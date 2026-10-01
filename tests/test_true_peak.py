"""用獨立的 FFT 插值驗證輸出，不拿限幅器自己的偵測器當 oracle。"""

from __future__ import annotations

import numpy as np
import pytest

from aurora.core.acoustics import fft_true_peak as fft_peak
from aurora.core.constants import LIMITER_CEILING
from aurora.core.dsp_graph import DspGraph
from aurora.core.dynamics import Limiter
from aurora.core.eq import GraphicEqualizer
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix


def render(signal: np.ndarray, rate: int = 48000, block: int = 2880) -> np.ndarray:
    limiter = Limiter()
    limiter.prepare(rate, signal.shape[1], block)
    # 補靜音把延遲與濾波器尾巴送出，FFT 的首尾不會把熱訊號接到零。
    padding = max(2048, limiter.latency_frames * 4)
    padded = np.pad(signal.astype(np.float32), ((padding, padding), (0, 0)))
    out = padded.copy()
    for start in range(0, out.shape[0], block):
        limiter.process(out[start : start + block].reshape(-1))
    return out


@pytest.mark.parametrize("rate", [44100, 48000, 96000, 192000])
@pytest.mark.parametrize("kind", ["quarter", "clipped"])
def test_output_true_peak_is_below_minus_one_dbtp(rate: int, kind: str) -> None:
    n = np.arange(16384)
    if kind == "quarter":
        mono = 1.2 * np.sin(2 * np.pi * n / 4 + np.pi / 4)
    else:
        mono = 0.9 * np.tanh(
            3
            * (
                np.sin(2 * np.pi * 2100 * n / rate)
                + 0.7 * np.sin(2 * np.pi * 5300 * n / rate + 1)
                + 0.5 * np.sin(2 * np.pi * 11900 * n / rate + 2)
            )
        )
    signal = np.column_stack((mono, -0.8 * mono))
    assert fft_peak(signal) > 10 ** (-1 / 20), "素材必須真的超過 true-peak 目標"
    # 目標是絕對 −1 dBTP，不能只跟可被誤改的常數比較。
    assert fft_peak(render(signal, rate)) <= 10 ** (-1 / 20) + 1e-5


@pytest.mark.parametrize("block", [1, 7, 63, 137, 4096])
def test_true_peak_is_independent_of_callback_partition(block: int) -> None:
    rng = np.random.default_rng(211)
    signal = rng.standard_normal((4096, 2)) * 0.6
    signal[1023:1026] *= 4.0
    assert np.allclose(render(signal, block=block), render(signal), atol=2e-7, rtol=0)


def test_peak_between_samples_engages_even_when_samples_are_safe() -> None:
    mono = 1.1 * np.sin(2 * np.pi * np.arange(4096) / 4 + np.pi / 4)
    assert np.abs(mono).max() < LIMITER_CEILING
    limiter = Limiter()
    limiter.prepare(48000, 2, 4096)
    signal = np.column_stack((mono, mono)).astype(np.float32).reshape(-1)
    limiter.process(signal)
    assert limiter.engaged_frames > 0


def test_limiter_reset_discards_detector_and_gain_history() -> None:
    limiter = Limiter()
    limiter.prepare(48000, 2, 2880)
    hot = np.full(5760, 4.0, dtype=np.float32)
    limiter.process(hot)
    limiter.reset()
    silence = np.zeros(5760, dtype=np.float32)
    limiter.process(silence)
    assert np.count_nonzero(silence) == 0


@pytest.mark.parametrize("kind", ["noise", "clipped_noise", "burst", "nyquist_band"])
def test_full_band_stress_true_peak(kind: str) -> None:
    rng = np.random.default_rng(12345)
    for case in range(10):
        signal = rng.normal(0.0, 1.0, (16384, 2))
        if kind == "clipped_noise":
            signal = np.clip(signal * 2.0, -0.95, 0.95)
        elif kind == "burst":
            signal *= 0.01
            signal[500:520] = rng.normal(0.0, 3.0, (20, 2))
            signal[-20:] = rng.normal(0.0, 3.0, (20, 2))
        elif kind == "nyquist_band":
            mono = 1.2 * np.sin(2 * np.pi * np.arange(16384) * (0.45 + case * 0.0049) + 0.78)
            signal = np.column_stack((mono, mono))
        assert fft_peak(render(signal)) <= 10 ** (-1 / 20) + 1e-5, (kind, case)
        assert fft_peak(render(signal), factor=8) <= 10 ** (-1 / 20) + 1e-5, (kind, case)


@pytest.mark.parametrize("channels", [1, 2, 6])
def test_linked_channels_keep_their_ratios(channels: int) -> None:
    mono = 1.2 * np.sin(2 * np.pi * np.arange(8192) / 4 + np.pi / 4)
    ratios = np.linspace(0.25, 1.0, channels)
    output = render(mono[:, None] * ratios)
    assert np.allclose(output, output[:, -1:] * (ratios / ratios[-1]), atol=1e-7, rtol=0)


@pytest.mark.parametrize("lookahead", [0, 1, 64])
def test_small_lookahead_and_larger_than_prepared_blocks(lookahead: int) -> None:
    limiter = Limiter(lookahead=lookahead)
    limiter.prepare(48000, 2, 7)
    signal = np.zeros((8192, 2), dtype=np.float32)
    signal[2000:2100] = 4.0
    limiter.process(signal.reshape(-1))
    assert fft_peak(signal) <= 10 ** (-1 / 20) + 1e-5


def test_nonfinite_samples_do_not_poison_detector_history() -> None:
    limiter = Limiter()
    limiter.prepare(48000, 2, 2880)
    signal = np.zeros(5760, dtype=np.float32)
    signal[10:13] = [np.nan, np.inf, -np.inf]
    limiter.process(signal)
    assert np.count_nonzero(signal) == 0
    assert np.all(np.isfinite(signal))
    limiter.process(signal)
    assert np.count_nonzero(signal) == 0


def test_extreme_finite_input_stays_finite_and_bounded() -> None:
    hot = np.full((8192, 2), np.finfo(np.float32).max, dtype=np.float32)
    output = render(hot)
    assert np.all(np.isfinite(output))
    assert np.abs(output).max() <= LIMITER_CEILING + 1e-6


def test_quiet_audio_is_bit_identical_after_declared_delay() -> None:
    rng = np.random.default_rng(851)
    signal = rng.normal(0.0, 0.01, (8192, 2)).astype(np.float32)
    limiter = Limiter()
    limiter.prepare(48000, 2, 8192)
    output = signal.copy()
    limiter.process(output.reshape(-1))
    delay = limiter.latency_frames
    assert np.array_equal(output[delay:], signal[:-delay])
    assert limiter.engaged_frames == 0


@pytest.mark.parametrize("binaural", [False, True])
def test_full_effects_chain_respects_true_peak(binaural: bool) -> None:
    eq, spatial, reflections, limiter = (
        GraphicEqualizer(),
        SpatialUpmix(),
        EarlyReflections(),
        Limiter(),
    )
    graph = DspGraph()
    graph.prepare(48000, 2, 5760)
    graph.set_stages((eq, spatial, reflections, limiter))
    eq.set_gains([12.0] * 10)
    spatial.amount = reflections.amount = 1.0
    spatial.binaural = reflections.binaural = binaural
    rng = np.random.default_rng(715)
    signal = np.clip(rng.normal(0.0, 2.0, (32768, 2)), -0.95, 0.95)
    output = np.pad(signal.astype(np.float32), ((8192, 8192), (0, 0)))
    for start in range(0, len(output), 2880):
        graph.process(output[start : start + 2880].reshape(-1))
    assert not graph.degraded, graph.degradation_reason
    assert fft_peak(output) <= 10 ** (-1 / 20) + 1e-5


def test_fft_oracle_reconstructs_quarter_rate_tone() -> None:
    mono = np.sin(2 * np.pi * np.arange(1024) / 4 + np.pi / 4)
    assert fft_peak(mono[:, None]) == pytest.approx(1.0, abs=1e-12)
