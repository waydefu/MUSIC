"""DSP 級聯與安全網的測試。

這裡守的是 ``core/dsp_graph.py`` docstring 裡那五條規則。它們不是風格建議：
違反其中任何一條，症狀都會是難以重現的爆音、斷續，或是播放靜靜停住 ——
而不是乾脆的錯誤。所以每一條都要有機器判定得了的測試。

特別是「例外不得殺死回呼」那條。它抓的是**現況**的缺陷：在 graph 進來
之前，``AudioEngine._process`` 完全沒有防護，任何例外都會讓 miniaudio 的
產生器結束，播放停在那裡而 UI 什麼都不知道。
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from aurora.audio.engine import AudioEngine
from aurora.core.dsp_graph import AudioProcessor, DspGraph

FloatArray = npt.NDArray[np.float32]

RATE = 48000


def _signal(frames: int = 512, channels: int = 2) -> FloatArray:
    """確定性的測試訊號。用 sin 而不是隨機值，比對失敗時看得懂。"""
    t = np.arange(frames * channels, dtype=np.float32)
    return np.sin(t * 0.01, dtype=np.float32) * 0.5


class Gain(AudioProcessor):
    """把訊號乘上定值。用來驗證級聯順序與 in-place 語意。"""

    def __init__(self, factor: float, latency: int = 0) -> None:
        self.factor = factor
        self._latency = latency
        self.prepared: tuple[int, int, int] | None = None
        self.resets = 0

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self.prepared = (sample_rate, channels, max_frames)

    def process(self, buf: FloatArray) -> None:
        buf *= self.factor

    def reset(self) -> None:
        self.resets += 1

    @property
    def latency_frames(self) -> int:
        return self._latency


class Exploding(AudioProcessor):
    """一定會拋例外的處理器。"""

    def __init__(self) -> None:
        self.calls = 0

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        pass

    def process(self, buf: FloatArray) -> None:
        self.calls += 1
        raise RuntimeError("boom")

    def reset(self) -> None:
        pass

    @property
    def latency_frames(self) -> int:
        return 0


# ------------------------------------------------------------------ 規則 5：bypass


def test_empty_graph_is_bit_identical() -> None:
    """空 graph 必須逐位元原樣通過 —— 這是加入 graph 前後不變的保證。"""
    graph = DspGraph()
    buf = _signal()
    original = buf.copy()
    graph.process(buf)
    assert np.array_equal(buf, original)


def test_hard_bypass_is_bit_identical() -> None:
    """章程 §15 的 KPI：Hard Bypass 必須 bit-identical，不是「幾乎一樣」。"""
    graph = DspGraph()
    graph.set_stages((Gain(0.5),))
    graph.bypass = True

    buf = _signal()
    original = buf.copy()
    graph.process(buf)
    assert np.array_equal(buf, original)

    # 解除 bypass 之後才會真的動到訊號，證明剛剛不是因為級聯是空的。
    graph.bypass = False
    graph.process(buf)
    assert not np.array_equal(buf, original)


# ------------------------------------------------------------------ 規則 1、3


def test_stages_run_in_order_in_place() -> None:
    graph = DspGraph()
    graph.set_stages((Gain(2.0), Gain(3.0)))
    buf = _signal()
    expected = buf * 6.0
    graph.process(buf)
    assert np.allclose(buf, expected)


def test_latency_is_summed() -> None:
    graph = DspGraph()
    graph.set_stages((Gain(1.0, latency=128), Gain(1.0, latency=64)))
    assert graph.latency_frames == 192


def test_bypassed_graph_reports_no_latency() -> None:
    """bypass 時訊號沒被處理，就不該宣稱有延遲 —— 否則歌詞會對歪。"""
    graph = DspGraph()
    graph.set_stages((Gain(1.0, latency=128),))
    graph.bypass = True
    assert graph.latency_frames == 0


# ------------------------------------------------------------------ 規則 4：安全網


def test_exception_degrades_permanently_and_leaves_audio_untouched() -> None:
    graph = DspGraph()
    boom = Exploding()
    graph.set_stages((boom,))

    buf = _signal()
    original = buf.copy()
    graph.process(buf)

    assert graph.degraded
    assert "RuntimeError" in (graph.degradation_reason or "")
    # 使用者聽到未處理的音訊，不是一片寂靜，也不是半處理的雜訊。
    assert np.array_equal(buf, original)


def test_degraded_graph_does_not_retry_every_callback() -> None:
    """降級後不可以再呼叫壞掉的處理器。

    每 60 ms 拋一次例外比原本的問題更糟：例外物件的建立與 traceback
    會製造大量垃圾，長尾 latency 會直接爆掉。
    """
    graph = DspGraph()
    boom = Exploding()
    graph.set_stages((boom,))

    for _ in range(50):
        graph.process(_signal())

    assert boom.calls == 1


def test_reset_does_not_clear_degradation() -> None:
    """換一首歌不會把壞掉的處理器修好。"""
    graph = DspGraph()
    graph.set_stages((Exploding(),))
    graph.process(_signal())
    assert graph.degraded

    graph.reset()
    assert graph.degraded

    graph.clear_degradation()
    assert not graph.degraded


def test_degradation_is_consumed_once() -> None:
    """跟 take_finished 同一個模式：回呼設旗標，主執行緒取走。"""
    graph = DspGraph()
    graph.set_stages((Exploding(),))
    graph.process(_signal())

    first = graph.take_degradation()
    assert first is not None and "boom" in first
    assert graph.take_degradation() is None
    # 取走的是「事件」，診斷用的原因要留著。
    assert graph.degradation_reason is not None


# ------------------------------------------------------------------ 生命週期


def test_prepare_reaches_every_stage_including_late_arrivals() -> None:
    graph = DspGraph()
    graph.prepare(RATE, 2, 4096)

    early = Gain(1.0)
    graph.set_stages((early,))
    assert early.prepared == (RATE, 2, 4096)

    # 之後才加進來的也要拿到目前的設定，否則它會用未初始化的 buffer。
    late = Gain(1.0)
    graph.set_stages((early, late))
    assert late.prepared == (RATE, 2, 4096)


def test_reset_reaches_every_stage() -> None:
    graph = DspGraph()
    stage = Gain(1.0)
    graph.set_stages((stage,))
    graph.reset()
    assert stage.resets == 1


# ------------------------------------------------------------------ 規則 2：配置


def test_steady_state_does_not_accumulate_allocations() -> None:
    """穩態下不得累積配置。

    判定的是「不成長」而不是「絕對為零」—— NumPy 的 ufunc 與 CPython
    內部本來就有小型配置，去追那些不是長尾的成因。真正要擋的是
    「每次回呼都新建一批 ndarray」那種等級的事。
    """
    graph = DspGraph()
    graph.set_stages((Gain(1.0), Gain(1.0)))
    buf = _signal(2880)

    for _ in range(200):  # 暖機，讓一次性的配置先發生
        graph.process(buf)

    gc.collect()
    before = sys.getallocatedblocks()
    for _ in range(1000):
        graph.process(buf)
    grown = sys.getallocatedblocks() - before

    assert grown < 100, f"每 1000 次回呼累積了 {grown} 個 block"


# ------------------------------------------------------------------ 引擎整合


def test_engine_has_empty_graph_by_default() -> None:
    engine = AudioEngine(RATE)
    assert not engine.graph.active
    assert engine.processing_latency_frames == 0
    engine.close()


def test_engine_prepares_graph_with_room_for_a_full_callback() -> None:
    """max_frames 至少要蓋得住一次裝置回呼，否則處理器會在回呼裡重新配置。"""
    engine = AudioEngine(RATE)
    stage = Gain(1.0)
    engine.graph.set_stages((stage,))
    assert stage.prepared is not None
    assert stage.prepared[0] == RATE
    assert stage.prepared[2] >= RATE * 60 // 1000  # 60 ms 的裝置緩衝
    engine.close()


def test_engine_keeps_playing_when_a_processor_explodes(flac_path: Path) -> None:
    """回歸測試：DSP 出錯不得殺死音訊回呼。

    在 graph 進來之前，_process 完全沒有防護 —— 任何例外都會讓 miniaudio
    的產生器結束，播放停在那裡而 UI 什麼都不知道。這條測試守住修好之後
    的行為。
    """
    engine = AudioEngine(RATE)
    assert engine.load(str(flac_path))
    engine.graph.set_stages((Exploding(),))

    produced = [engine.pump(1024) for _ in range(5)]

    engine.close()
    assert all(count > 0 for count in produced), f"播放中斷了：{produced}"
    assert engine.graph.degraded


def test_engine_output_is_bit_identical_with_and_without_a_dead_graph() -> None:
    """降級之後送出的訊號要與完全沒有 graph 時逐位元相同。

    「安全網有接住」還不夠 —— 接住之後吐出來的必須是原本的音訊，
    不能是被處理到一半的東西。

    這裡直接比對 ``_process`` 的回傳值，不能改用分析器的環形緩衝：
    分析器拿到的是**進 graph 之前**的訊號，兩種情況下必然相同，
    拿它來比等於什麼都沒驗到。
    """
    frame = _signal(1024).tobytes()

    clean = AudioEngine(RATE)
    baseline = clean._process(frame)
    clean.close()

    dead = AudioEngine(RATE)
    dead.graph.set_stages((Exploding(),))
    output = dead._process(frame)
    degraded = dead.graph.degraded
    dead.close()

    assert degraded
    assert output == baseline


@pytest.mark.parametrize("bypass", [True, False])
def test_engine_pump_survives_graph_states(flac_path: Path, bypass: bool) -> None:
    engine = AudioEngine(RATE)
    assert engine.load(str(flac_path))
    engine.graph.set_stages((Gain(0.5),))
    engine.graph.bypass = bypass
    assert engine.pump(1024) > 0
    assert not engine.graph.degraded
    engine.close()
