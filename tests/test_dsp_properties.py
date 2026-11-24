"""Deterministic generative DSP checks: independent partitions, finite output, exact bypass."""

from __future__ import annotations

import numpy as np
import pytest

from aurora.core.dsp_graph import DspGraph, FloatArray
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
@pytest.mark.parametrize("binaural", [False, True])
@pytest.mark.parametrize("seed", [35, 122])
def test_randomized_partition_invariance(rate: int, binaural: bool, seed: int) -> None:
    rng = np.random.default_rng(seed)
    frames = 12000
    pcm = rng.uniform(-0.15, 0.15, frames * 2).astype(np.float32)
    amount = float(rng.uniform(0.05, 1.0))

    def render(random_partitions: bool) -> FloatArray:
        spatial = SpatialUpmix()
        reflections = EarlyReflections()
        for stage in (spatial, reflections):
            stage.amount = amount
            stage.hrtf_profile = "synthetic"
            stage.binaural = binaural
        graph = DspGraph()
        graph.prepare(rate, 2, 2048)
        graph.set_snapshot_processors((spatial, reflections))
        graph.set_stages((spatial, reflections))
        output = pcm.copy()
        start = 0
        while start < frames:
            count = int(rng.integers(1, 2049)) if random_partitions else 1024
            stop = min(start + count, frames)
            graph.process(output[start * 2 : stop * 2])
            assert not graph.degraded
            start = stop
        assert np.isfinite(output).all()
        return output

    np.testing.assert_allclose(render(True), render(False), atol=3e-6, rtol=3e-6)


@pytest.mark.parametrize("seed", range(8))
def test_bypass_preserves_arbitrary_finite_pcm(seed: int) -> None:
    rng = np.random.default_rng(seed)
    samples = rng.uniform(-1.0, 1.0, 2048).astype(np.float32)
    before = samples.tobytes()
    graph = DspGraph()
    graph.prepare(48000, 2, 1024)
    graph.set_stages((SpatialUpmix(), EarlyReflections()))
    graph.bypass = True
    graph.process(samples)
    assert samples.tobytes() == before
