"""輸出端點取樣率同步的守門測試。

守的是一條實際回報過的 bug：``QualityController`` 以前只在**裝置 ID 改變**
時通知引擎對齊取樣率。同一支耳機在連線初期報 24 kHz、之後自己恢復成
48 kHz 時，ID 從頭到尾沒變，於是引擎切下去就再也沒有人通知它回來 ——
整條鏈變成 48 → 24 → 48 kHz，而第一段砍掉的高頻不會因為後面升回去就回來。

另一半是相反方向的要求：過渡值不能立刻拖著引擎重建裝置。兩件事互相拉扯，
所以放在同一個檔案裡一起守。

這裡不會開音訊裝置 —— ``AudioEngine`` 沒載入曲目時 ``configure_output``
只改內部取樣率與分析器，不碰 miniaudio。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

import pytest
from PySide6.QtCore import QCoreApplication

from aurora.audio.engine import AudioEngine
from aurora.bridge import quality as quality_module
from aurora.bridge.quality import QualityController
from aurora.core.constants import ENDPOINT_RATE_CONFIRM_POLLS
from aurora.core.models import (
    AudioFormat,
    EndpointInfo,
    EndpointSnapshot,
    TransportKind,
)
from aurora.platform.base import NullAdapter

HEADPHONES = "{bt-headphones}"
SPEAKERS = "{usb-speakers}"


def _endpoint(rate: int, device_id: str = HEADPHONES) -> EndpointInfo:
    return EndpointInfo(
        id=device_id,
        friendly_name="AirPods Pro",
        description="Headphones",
        enumerator="blue",
        instance_id="",
        transport=TransportKind.BLUETOOTH_A2DP,
        device_format=AudioFormat(rate, 2, 32, is_float=True),
    )


class _ScriptedAdapter(NullAdapter):
    """照劇本回答端點查詢。

    劇本的每一格是一次輪詢的結果：``None`` 代表查不到裝置，``(id, rate)``
    代表那一輪讀到的端點。跑完劇本後停在最後一格 —— 現實裡的端點也是
    停在某個狀態，不會消失。
    """

    def __init__(self, script: Sequence[tuple[str, int] | None]) -> None:
        self._script = list(script)
        self.polls = 0

    def query_endpoints(self) -> EndpointSnapshot:
        entry = self._script[min(self.polls, len(self._script) - 1)]
        self.polls += 1
        if entry is None:
            return EndpointSnapshot()
        endpoint = _endpoint(entry[1], entry[0])
        return EndpointSnapshot(default=endpoint, active=(endpoint,))


Rig = Callable[..., tuple[QualityController, AudioEngine]]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    """組一台「端點照劇本走、引擎照通知走」的測試機。

    連線方式與 ``PlayerController`` 一致：``outputRateChanged`` 直接餵給
    ``configure_output``。斷言看的是引擎最後真的跑在幾 kHz，不是有沒有發訊號 ——
    使用者聽到的是前者。
    """
    QCoreApplication.instance() or QCoreApplication([])
    engines: list[AudioEngine] = []

    def build(
        script: Sequence[tuple[str, int] | None], engine_rate: int = 48000
    ) -> tuple[QualityController, AudioEngine]:
        engine = AudioEngine(engine_rate)
        engines.append(engine)
        # 同一個實例，不是每次呼叫都新建一個 —— 劇本的進度就存在它身上。
        scripted = _ScriptedAdapter(script)
        monkeypatch.setattr(quality_module, "adapter", lambda: scripted)
        controller = QualityController(engine)
        controller.outputRateChanged.connect(engine.configure_output)
        return controller, engine

    yield build

    for engine in engines:
        engine.close()


def _poll(controller: QualityController, times: int) -> None:
    for _ in range(times):
        controller.refresh_endpoint()


# ------------------------------------------------------------------ 回得去


def test_same_device_changing_rate_still_reaches_the_engine(rig: Rig) -> None:
    """同一支耳機 24 kHz → 48 kHz，引擎必須跟著回到 48 kHz。

    這就是原本壞掉的那一條：ID 沒變，舊程式碼就什麼都不做。
    """
    controller, engine = rig(
        [(HEADPHONES, 24000)] * ENDPOINT_RATE_CONFIRM_POLLS
        + [(HEADPHONES, 48000)] * ENDPOINT_RATE_CONFIRM_POLLS
    )

    _poll(controller, ENDPOINT_RATE_CONFIRM_POLLS)
    assert engine.sample_rate == 24000, "端點穩定在 24 kHz 時引擎本來就該跟上"

    _poll(controller, ENDPOINT_RATE_CONFIRM_POLLS)
    assert engine.sample_rate == 48000, "端點回到 48 kHz，引擎不能卡在 24 kHz"


def test_device_swap_aligns_the_engine(rig: Rig) -> None:
    """換裝置這條原本就會動的路徑不能被改壞。"""
    controller, engine = rig([(SPEAKERS, 44100)] * ENDPOINT_RATE_CONFIRM_POLLS)
    names: list[str] = []
    controller.deviceChanged.connect(names.append)

    _poll(controller, ENDPOINT_RATE_CONFIRM_POLLS)

    assert engine.sample_rate == 44100
    assert names == ["AirPods Pro"], "換裝置的 toast 只該跳一次"


# ------------------------------------------------------------------ 不亂跟


def test_a_single_transient_reading_never_reaches_the_engine(rig: Rig) -> None:
    """藍牙剛連上時的過渡格式只出現一輪，不該讓引擎降取樣。

    降下去是不可逆的：高頻在那一次重取樣就沒了。所以寧可慢一輪。
    """
    controller, engine = rig([(HEADPHONES, 24000), (HEADPHONES, 48000)])

    _poll(controller, 6)

    assert engine.sample_rate == 48000


def test_flapping_rate_is_not_chased(rig: Rig) -> None:
    """24／48 來回跳時，引擎維持現狀，不是每輪重建一次裝置。"""
    controller, engine = rig([(HEADPHONES, 24000), (HEADPHONES, 48000)] * 4)

    _poll(controller, 8)

    assert engine.sample_rate == 48000


def test_endpoint_disappearing_leaves_the_engine_alone(rig: Rig) -> None:
    """讀不到端點時維持現狀 —— 退回預設值只會換來一次沒必要的裝置重建。"""
    controller, engine = rig(
        [(HEADPHONES, 44100)] * ENDPOINT_RATE_CONFIRM_POLLS + [None, None, None]
    )

    _poll(controller, ENDPOINT_RATE_CONFIRM_POLLS)
    assert engine.sample_rate == 44100

    _poll(controller, 3)
    assert engine.sample_rate == 44100
