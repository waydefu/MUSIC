"""等化器／空間音效 ViewModel 的測試。

這一層不做 DSP，所以這裡驗的是**接線**：級聯有沒有在對的時候掛上去、
設定有沒有存對、以及停用時使用者調好的曲線會不會被弄丟。

最後一條特別重要 —— 它是開發時真的寫錯過的地方：停用時處理器會被填成
全平（不然 graph 裡還是會跑 FFT），如果 UI 從處理器讀值，滑桿就會歸零、
使用者的曲線憑空消失。設定檔才是增益的唯一真相來源。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from aurora.audio.engine import AudioEngine
from aurora.bridge.audiofx import AudioFxController
from aurora.core.config import Config
from aurora.core.constants import EQ_BAND_HZ, EQ_GAIN_LIMIT_DB
from aurora.core.dynamics import Limiter, OutputMeter
from aurora.core.eq import GraphicEqualizer
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix

#: 掛上去的級聯應該長什麼樣。用型別而不是數量斷言 —— 數量對不上時
#: 只會說「4 != 5」，型別對不上時會直接指出少了哪一級。
EXPECTED_CHAIN = (GraphicEqualizer, SpatialUpmix, EarlyReflections, Limiter, OutputMeter)


def _chain_types(engine: AudioEngine) -> tuple[type, ...]:
    return tuple(type(stage) for stage in engine.graph.stages)

BANDS = len(EQ_BAND_HZ)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def fx() -> object:
    _app()
    engine = AudioEngine()
    config = Config()
    controller = AudioFxController(engine, config)
    yield controller, engine, config
    engine.close()


# ------------------------------------------------------------------ 預設狀態


def test_everything_is_off_by_default(fx: object) -> None:
    """使用者沒開過音效就不該付任何代價 —— 沒有級聯、沒有延遲。"""
    controller, engine, _ = fx
    assert not controller.eqEnabled
    assert controller.spatialAmount == 0.0
    assert engine.graph.stages == ()
    assert controller.latencyMs == 0.0


def test_enabling_a_flat_eq_installs_nothing(fx: object) -> None:
    """全平的 EQ 等於沒有 EQ。開關打開但曲線沒動時不該掛級聯。

    否則使用者只是好奇按了開關，就白白付了限幅器的延遲與運算。
    """
    controller, engine, _ = fx
    controller.setEqEnabled(True)
    assert controller.eqEnabled
    assert engine.graph.stages == ()
    assert controller.latencyMs == 0.0


# ------------------------------------------------------------------ 掛載時機


def test_a_boosted_band_installs_the_chain(fx: object) -> None:
    controller, engine, _ = fx
    controller.setEqEnabled(True)
    controller.setBandGain(5, 6.0)

    assert _chain_types(engine) == EXPECTED_CHAIN
    assert controller.latencyMs > 0.0


def test_spatial_alone_installs_the_chain(fx: object) -> None:
    controller, engine, _ = fx
    controller.setSpatialAmount(0.5)
    assert _chain_types(engine) == EXPECTED_CHAIN
    assert controller.latencyMs > 0.0


def test_turning_everything_off_removes_the_chain(fx: object) -> None:
    controller, engine, _ = fx
    controller.setEqEnabled(True)
    controller.setBandGain(3, 8.0)
    controller.setSpatialAmount(0.7)
    assert engine.graph.stages != ()

    controller.setEqEnabled(False)
    controller.setSpatialAmount(0.0)
    assert engine.graph.stages == ()
    assert controller.latencyMs == 0.0


# ------------------------------------------------------------------ 曲線不可以憑空消失


def test_disabling_keeps_the_user_curve(fx: object) -> None:
    """**這是實作時寫錯過的地方。**

    停用時處理器被填成全平，但 UI 顯示的曲線必須留著 —— 不然使用者
    關掉再打開，辛苦調的設定就沒了。
    """
    controller, _, config = fx
    controller.setEqEnabled(True)
    controller.setBandGain(0, 9.0)
    controller.setBandGain(9, -6.0)

    controller.setEqEnabled(False)
    assert controller.bandGains[0] == pytest.approx(9.0)
    assert controller.bandGains[9] == pytest.approx(-6.0)
    assert config.eq_gains[0] == pytest.approx(9.0)

    controller.setEqEnabled(True)
    assert controller.bandGains[0] == pytest.approx(9.0)


def test_reset_zeroes_every_band(fx: object) -> None:
    controller, engine, _ = fx
    controller.setEqEnabled(True)
    controller.setBandGain(2, 10.0)
    controller.resetEq()

    assert all(value == 0.0 for value in controller.bandGains)
    # 歸零之後又變成全平，級聯要跟著卸下來。
    assert engine.graph.stages == ()


# ------------------------------------------------------------------ 設定持久化


def test_settings_are_written_to_config(fx: object) -> None:
    controller, _, config = fx
    controller.setEqEnabled(True)
    controller.setBandGain(4, 5.0)
    controller.setSpatialAmount(0.35)

    assert config.eq_enabled is True
    assert config.eq_gains[4] == pytest.approx(5.0)
    assert config.spatial_amount == pytest.approx(0.35)


def test_settings_are_restored_from_config() -> None:
    _app()
    engine = AudioEngine()
    config = Config()
    config.eq_enabled = True
    config.eq_gains = [3.0] * BANDS
    config.spatial_amount = 0.8

    controller = AudioFxController(engine, config)
    try:
        assert controller.eqEnabled
        assert controller.bandGains[0] == pytest.approx(3.0)
        assert controller.spatialAmount == pytest.approx(0.8)
        assert _chain_types(engine) == EXPECTED_CHAIN
    finally:
        engine.close()


def test_gains_are_clamped_before_being_stored(fx: object) -> None:
    """設定檔不該累積超出範圍的數字，否則之後很難分辨是誰寫壞的。"""
    controller, _, config = fx
    controller.setEqEnabled(True)
    controller.setBandGain(1, 999.0)
    assert config.eq_gains[1] == pytest.approx(EQ_GAIN_LIMIT_DB)
    assert controller.bandGains[1] == pytest.approx(EQ_GAIN_LIMIT_DB)


def test_out_of_range_band_index_is_ignored(fx: object) -> None:
    controller, _, _ = fx
    before = list(controller.bandGains)
    controller.setBandGain(-1, 6.0)
    controller.setBandGain(BANDS + 5, 6.0)
    assert controller.bandGains == before


# ------------------------------------------------------------------ 顯示用資訊


def test_headroom_explains_why_boosting_is_not_louder(fx: object) -> None:
    """UI 要能解釋「拉高了卻沒變大聲」，不然使用者會以為滑桿壞了。"""
    controller, _, _ = fx
    controller.setEqEnabled(True)
    controller.setBandGain(6, 8.0)
    assert controller.headroomDb == pytest.approx(-8.0)

    controller.setEqEnabled(False)
    assert controller.headroomDb == 0.0


def test_band_labels_match_band_count(fx: object) -> None:
    controller, _, _ = fx
    assert len(controller.bandLabels) == BANDS
    assert controller.gainLimit == pytest.approx(EQ_GAIN_LIMIT_DB)


# ------------------------------------------------------------------ 降級回報


def test_poll_surfaces_a_degraded_graph(fx: object) -> None:
    """回呼裡不能發 Qt signal，所以降級要靠主執行緒輪詢撈出來。"""
    import numpy as np

    controller, engine, _ = fx

    class Exploding:
        def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None: ...
        def process(self, buf: object) -> None:
            raise RuntimeError("boom")
        def reset(self) -> None: ...
        @property
        def latency_frames(self) -> int:
            return 0

    engine.graph.set_stages((Exploding(),))
    engine.graph.process(np.zeros(512, dtype=np.float32))
    assert engine.graph.degraded

    seen: list[str] = []
    controller.degraded.connect(seen.append)
    controller.poll()
    assert seen and "boom" in seen[0]

    # 事件只該回報一次，不然每個 UI 幀都會跳一次提示。
    controller.poll()
    assert len(seen) == 1
