"""離線候選工具：守住公平比較、有限尾巴及 fail-closed profile。"""

from __future__ import annotations

import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/probe_naturalness.py"
SPEC = importlib.util.spec_from_file_location("naturalness_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def signal(frames: int = 12000) -> np.ndarray:
    return np.random.default_rng(441).normal(0, 0.015, (frames, 2)).astype(np.float32)


def test_dry_is_bit_identical_after_common_preattenuation() -> None:
    source = probe.constant_attenuate(signal(), -12.0)
    rendered = probe.render_arm(source, probe.ARMS[0], rate=48000, profile="synthetic")
    assert np.array_equal(rendered.samples[: len(source)], source)
    assert rendered.diagnostics["latency_frames"] == 0
    assert not rendered.diagnostics["limiter_present"]
    assert not np.any(rendered.samples[len(source) :])


def test_constant_gain_preserves_shape_and_rejects_clipping() -> None:
    source = signal()
    attenuated = probe.constant_attenuate(source, -6.0)
    expected = source.astype(np.float64) * 10 ** (-6 / 20)
    assert np.allclose(attenuated, expected, atol=2e-9, rtol=1e-7)
    with pytest.raises(ValueError, match="衰減"):
        probe.constant_attenuate(source, 0.1)
    with pytest.raises(ValueError, match="滿刻度"):
        probe.constant_attenuate(np.ones((100, 2), dtype=np.float32), 0.0)
    with pytest.raises(ValueError, match="有限"):
        probe.constant_attenuate(np.full((10, 2), np.nan, dtype=np.float32), -6)


@pytest.mark.parametrize("arm", [probe.ARMS[5], probe.ARMS[7]])
def test_effects_chunk_invariance_and_complete_finite_tail(arm: object) -> None:
    source = signal()
    source[-1] = [0.08, -0.06]
    short = probe.render_arm(source, arm, rate=48000, profile="synthetic", block_frames=64)
    long = probe.render_arm(source, arm, rate=48000, profile="synthetic", block_frames=2880)
    assert short.samples.shape == long.samples.shape
    assert np.allclose(short.samples, long.samples, atol=2e-7, rtol=2e-6)
    assert short.diagnostics["aligned_tail_frames"] >= 24000
    assert short.diagnostics["limiter_reduced_frames_including_context_tail"] == 0
    assert not np.any(short.samples[-4800:])
    # 曲尾脈衝經反射後仍有資料，不因 stage latency=0 而丟掉。
    assert np.any(np.abs(short.samples[len(source) : len(source) + 5000]) > 1e-7)


def test_explicit_missing_profile_fails_without_synthetic_fallback() -> None:
    with pytest.raises(ValueError, match="明確"):
        probe.explicit_profile("")
    with pytest.raises(ValueError, match="不存在"):
        probe.explicit_profile("__naturalness_nonexistent_profile__")
    assert probe.explicit_profile("synthetic")["effective"] == "synthetic"


def test_common_target_attenuates_every_arm_and_leaves_true_peak_headroom() -> None:
    rows = [
        {"integrated_lufs": -14.0, "true_peak_dbtp": -3.0},
        {"integrated_lufs": -13.0, "true_peak_dbtp": 0.5},
    ]
    target = probe.common_loudness_target(rows)
    for row in rows:
        gain = target - row["integrated_lufs"]
        assert gain <= 0
        assert row["true_peak_dbtp"] + gain <= -2.0
    with pytest.raises(ValueError, match="有限"):
        probe.common_loudness_target([{"integrated_lufs": -np.inf, "true_peak_dbtp": -np.inf}])


def test_bad_profile_content_fails_even_when_file_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "broken.npz"
    bad.write_bytes(b"not an HRTF dataset")
    monkeypatch.setattr(probe, "resolve_profile", lambda name: bad)
    with pytest.raises(ValueError, match="fallback"):
        probe.render_arm(signal(), probe.ARMS[4], rate=48000, profile="broken")


def test_no_device_is_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline tool attempted device opening")

    monkeypatch.setattr(probe.miniaudio, "PlaybackDevice", forbidden)
    result = probe.render_arm(signal(4096), probe.ARMS[4], rate=48000, profile="synthetic")
    assert np.all(np.isfinite(result.samples))


def test_stream_decoder_uses_real_context_and_rejects_short_source(tmp_path: Path) -> None:
    rate = 48000
    frames = 4 * rate
    rng = np.random.default_rng(90)
    pcm = rng.integers(-2000, 2000, (frames, 2), dtype=np.int16)
    path = tmp_path / "真實前文.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.astype("<i2").tobytes())
    decoded, before, context = probe.decode_context(
        path, start=3.0, seconds=0.5, rate=rate, preroll=2.0
    )
    assert before == 2 * rate
    assert context["decode_start_frame"] == rate
    assert context["real_preroll_seconds"] == 2.0
    expected = pcm[rate : int(3.5 * rate)].astype(np.float32) / 32768
    assert np.array_equal(decoded, expected)
    with_post, _, full_context = probe.decode_context(
        path, start=3.0, seconds=0.5, rate=rate, preroll=2.0, postroll=0.4
    )
    assert np.array_equal(with_post, pcm[rate : int(3.9 * rate)].astype(np.float32) / 32768)
    assert full_context["source_end_frame"] == int(3.5 * rate)
    assert full_context["real_postroll_frames"] == int(0.4 * rate)
    assert not full_context["shortened_postroll_at_source_eof"]
    at_eof, _, eof_context = probe.decode_context(
        path, start=3.0, seconds=0.5, rate=rate, preroll=2.0, postroll=2.0
    )
    assert np.array_equal(at_eof, pcm[rate:].astype(np.float32) / 32768)
    assert eof_context["shortened_postroll_at_source_eof"]
    assert eof_context["real_postroll_seconds"] == 0.5
    assert eof_context["decode_actual_end_frame"] == frames
    aligned, aligned_before, aligned_context = probe.decode_context(
        path, start=3.0, seconds=0.5, rate=rate, preroll=2.0, postroll=0.4, grid_frames=1024
    )
    aligned_start = rate - rate % 1024
    assert np.array_equal(aligned, pcm[aligned_start : int(3.9 * rate)].astype(np.float32) / 32768)
    assert aligned_before >= 2 * rate
    assert aligned_context["decode_start_frame"] % 1024 == 0
    assert aligned_context["alignment_extra_preroll_frames"] == rate % 1024
    with pytest.raises(ValueError, match="長度不足"):
        probe.decode_context(path, start=3.5, seconds=1.0, rate=rate, preroll=2.0)


def test_loudnorm_reads_input_measurements_and_discards_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    def measure(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert command[-3:] == ["-f", "null", "-"]
        assert "print_format=json" in command[command.index("-af") + 1]
        assert isinstance(kwargs["input"], bytes)
        return SimpleNamespace(
            stderr=json.dumps(
                {
                    "input_i": "-19.30",
                    "input_tp": "-6.20",
                    "output_i": "-23.00",
                    "output_tp": "-9.90",
                }
            ).encode()
        )

    monkeypatch.setattr(probe.subprocess, "run", measure)
    measured = probe.measure_loudness(signal(), 48000)
    assert measured["integrated_lufs"] == -19.3
    assert measured["true_peak_dbtp"] == -6.2


def test_real_postroll_crop_matches_full_source_reference() -> None:
    source = signal(48000)
    end = 12000
    arm = probe.ARMS[5]
    reference = probe.render_arm(source, arm, rate=48000, profile="synthetic").samples[:end]
    with_post = probe.render_arm(
        source[: end + 4800], arm, rate=48000, profile="synthetic"
    ).samples[:end]
    truncated = probe.render_arm(source[:end], arm, rate=48000, profile="synthetic").samples[:end]
    assert np.allclose(with_post, reference, atol=2e-7, rtol=2e-6)
    assert float(np.abs(truncated - reference).max()) > 1e-4


def test_delivered_group_gate_rejects_pairwise_spread_hidden_by_target_tolerance() -> None:
    rows = [
        {"integrated_lufs": -20.09, "true_peak_dbtp": -3.0},
        {"integrated_lufs": -19.91, "true_peak_dbtp": -3.0},
    ]
    for row in rows:
        probe.validate_delivered_loudness([row], -20.0)
    with pytest.raises(RuntimeError, match="pairwise"):
        probe.validate_delivered_loudness(rows, -20.0)


def test_global_stft_grid_makes_off_grid_two_and_four_second_contexts_converge(
    tmp_path: Path,
) -> None:
    rate = 48000
    pcm = np.rint(signal(6 * rate) * 32768).astype("<i2")
    source = pcm.astype(np.float32) / 32768
    path = tmp_path / "STFT全曲基線.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.tobytes())
    start = 4.2
    start_frame = round(start * rate)
    segment_frames = 16000
    arm = probe.ARMS[5]
    reference = probe.render_arm(source, arm, rate=rate, profile="synthetic").samples[
        start_frame : start_frame + segment_frames
    ]
    for preroll in (2.0, 4.0):
        decoded, before, context = probe.decode_context(
            path,
            start=start,
            seconds=segment_frames / rate,
            rate=rate,
            preroll=preroll,
            postroll=1.0,
            grid_frames=1024,
        )
        assert context["decode_start_frame"] % 1024 == 0
        assert before >= round(preroll * rate)
        actual = probe.render_arm(decoded, arm, rate=rate, profile="synthetic").samples[
            before : before + segment_frames
        ]
        assert np.allclose(actual, reference, atol=2e-7, rtol=2e-6)
        legacy_start = start_frame - round(preroll * rate)
        assert legacy_start % 1024 != 0
        legacy = probe.render_arm(
            source[legacy_start : start_frame + segment_frames + rate],
            arm,
            rate=rate,
            profile="synthetic",
        ).samples[round(preroll * rate) : round(preroll * rate) + segment_frames]
        assert float(np.abs(legacy - reference).max()) > 1e-4
