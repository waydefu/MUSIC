"""量測音訊回呼的執行時間分布。

**為什麼需要這個工具**：章程把「Python 的 GIL／GC 造成長尾 latency」列為
Critical 風險（R1），但到目前為止**一次都沒有量過**。在往回呼裡放任何 DSP
之前，得先知道現在還剩多少餘裕 —— 否則只能靠「Python 應該慢」這種直覺
做決策，而那正是章程要擋的。

量的是什麼：``AudioEngine._process`` 的執行時間。**解碼不包含在內** ——
``_process`` 收到的已經是解好的 frame，miniaudio 在產生器鏈的上游做完解碼。
這與章程 §1.1 引用的「既有 _process() 平均約 0.256 ms」是同一個定義，
兩邊的數字可以直接對照。真正的回呼預算還要再加上解碼，這一點在解讀
結果時不能忘記。

兩種模式：

``--offline``
    用 :meth:`AudioEngine.pump` 手動推進，不開音訊裝置、不出聲。
    CI 上唯一能跑的模式，但**只有 p50 可用**。

    實測（2026-08，同一台機器、同一份程式碼跑五次）：p50 穩定在
    0.116–0.126 ms，max 卻從 0.58 ms 跳到 16.1 ms —— 28 倍。
    原因是 offline 全速推進、CPU 完全飽和，尾端量到的是機器上其他東西的
    干擾。諷刺的是 ``--device`` 反而被音訊時鐘節流（每 60 ms 才來一次，
    中間 CPU 是閒的），尾巴乾淨得多：同一天量到 max 只有 3.57 ms。

    所以「便宜的量法」不只是不準，是**會比真實情況更糟**。抓回歸只比 p50。

``--device``
    真實 ``PlaybackDevice`` + Qt 事件迴圈 + 60 Hz 分析器 tick。
    這才是章程 §6.3 要求的量測條件，但**只能在實體機器上跑**：
    hosted CI runner 沒有音訊裝置，而且共用 VM 的鄰居噪音會直接污染
    p99／p99.9 —— 那恰好是這個工具唯一的重點。不準的尾端數字比沒有
    數字更危險，因為它會讓人以為問題已經被量過了。

``--device`` 預設靜音。靜音不影響量測代表性：``_process`` 的增益分支
只看 ``gain != 1.0``，音量 0.0 與 0.8 走的是同一條路徑。

**已知的涵蓋缺口**：``--device`` 只跑分析器 tick，沒有載入 QML、沒有實際
算繪。真實的 UI 執行緒負載比這裡更重，所以量到的數字是**下界**，不是上界。
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np
import numpy.typing as npt

from aurora.audio.engine import AudioEngine
from aurora.core.constants import FALLBACK_SAMPLE_RATE, UI_TICK_HZ

ROOT = Path(__file__).resolve().parents[1]
#: 預設素材。由 tools/make_test_audio.py 產生，內容是確定性的。
DEFAULT_SOURCE = ROOT / "tests" / "_generated" / "test.flac"

#: 章程 §1.1 的基準環境：48 kHz、buffersize 60 ms → 每次回呼 2880 frames。
#: offline 模式用這個值才能跟 device 模式與章程的數字對照。
REFERENCE_FRAMES = 2880

#: 丟棄前面這麼多次回呼。第一次呼叫會觸發 numpy 的惰性初始化與各種
#: 首次配置，計進去只會讓 max 變成一個沒有意義的離群值。
WARMUP_CALLBACKS = 200


class TimedEngine(AudioEngine):
    """在 ``_process`` 外面包一層計時。

    刻意用繼承而不是改動 :mod:`aurora.audio.engine` —— 量測工具不該
    在生產路徑上留下任何東西。

    計時樣本寫進預先配置好的 ndarray 而不是 list.append，因為 append
    會在回呼執行緒上配置記憶體，那正是我們想量的東西之一。
    """

    def __init__(self, sample_rate: int, capacity: int) -> None:
        super().__init__(sample_rate)
        self._elapsed = np.zeros(capacity, dtype=np.float64)
        self._frames = np.zeros(capacity, dtype=np.int32)
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def samples_ms(self) -> npt.NDArray[np.float64]:
        return self._elapsed[: self._count] * 1000.0

    def frames_per_call(self) -> npt.NDArray[np.int32]:
        return self._frames[: self._count]

    def _process(self, frame: object) -> bytes:
        start = time.perf_counter()
        out = super()._process(frame)
        elapsed = time.perf_counter() - start
        if self._count < self._elapsed.size:
            self._elapsed[self._count] = elapsed
            self._frames[self._count] = len(out) // 4 // 2  # float32 立體聲
            self._count += 1
        return out


def _percentiles(samples_ms: npt.NDArray[np.float64]) -> list[tuple[str, float]]:
    rows = [
        ("mean", float(samples_ms.mean())),
        ("p50", float(np.percentile(samples_ms, 50))),
        ("p95", float(np.percentile(samples_ms, 95))),
        ("p99", float(np.percentile(samples_ms, 99))),
        ("p99.9", float(np.percentile(samples_ms, 99.9))),
        ("max", float(samples_ms.max())),
    ]
    return rows


def _report(
    samples_ms: npt.NDArray[np.float64],
    frames: npt.NDArray[np.int32],
    sample_rate: int,
    mode: str,
    pressure: Pressure | None,
) -> int:
    """印出結果，並依章程 §6.3 的預算判定是否超標。回傳 process exit code。"""
    unique = np.unique(frames)
    if unique.size == 1:
        frames_each = int(unique[0])
        deadline_ms = frames_each / sample_rate * 1000.0
        frame_note = f"{frames_each} frames"
    else:
        # 回呼大小不固定時，用最小的那個算 deadline —— 最嚴格的情況。
        frames_each = int(unique.min())
        deadline_ms = frames_each / sample_rate * 1000.0
        frame_note = f"{unique.min()}–{unique.max()} frames（以最小值計 deadline）"

    print()
    print(f"模式        {mode}")
    print(f"取樣率      {sample_rate} Hz")
    print(f"每次回呼    {frame_note}")
    print(f"deadline    {deadline_ms:.2f} ms")
    print(f"樣本數      {samples_ms.size}（已丟棄前 {WARMUP_CALLBACKS} 次暖機）")
    print()
    print(f"  {'指標':<8} {'時間':>10}   {'佔 deadline':>12}")
    print(f"  {'-' * 8} {'-' * 10}   {'-' * 12}")
    for label, value in _percentiles(samples_ms):
        print(f"  {label:<8} {value:>7.3f} ms   {value / deadline_ms * 100:>11.2f}%")

    if pressure is not None:
        print()
        print(f"淨 block    {pressure.net_blocks:+.2f} ／回呼（累積：非零代表有東西沒被釋放）")
        if pressure.gen0_per_call > 0:
            every = 1.0 / pressure.gen0_per_call
            print(f"gen0 回收   每 {every:.0f} 次回呼一次（churn：這才是 R1 的長尾來源）")
        else:
            print("gen0 回收   量測窗內未觸發（churn 低）")

    # 章程 §6.3 的預算。offline 模式不做判定 —— 它的數字不具權威性。
    print()
    if mode != "device":
        print("※ offline 模式**只有 p50 可用**。")
        print("  實測（2026-08，同機同碼跑五次）：p50 穩定在 0.116–0.126 ms，")
        print("  但 max 從 0.58 跳到 16.1 ms —— 28 倍。offline 全速灌滿 CPU，")
        print("  尾端量到的是機器噪音，不是程式碼。device 模式反而被音訊時鐘")
        print("  節流，尾巴更乾淨（實測 max 3.57 ms）。")
        print("  抓回歸請只比 p50；章程 §6.3 的判定需要 --device。")
        return 0

    budget = [
        ("mean", float(samples_ms.mean()), 10.0),
        ("p99", float(np.percentile(samples_ms, 99)), 25.0),
        ("max", float(samples_ms.max()), 50.0),
    ]
    failed = False
    for label, value, limit in budget:
        pct = value / deadline_ms * 100
        mark = "OK  " if pct <= limit else "超標"
        if pct > limit:
            failed = True
        print(f"  [{mark}] {label:<5} {pct:6.2f}%  ≤ {limit:.0f}%")
    return 1 if failed else 0


class Pressure(NamedTuple):
    """記憶體壓力的兩個面向。**兩者量的不是同一件事。**"""

    #: 每次回呼的淨 block 增量。抓的是「累積」—— 有東西沒被釋放。
    net_blocks: float
    #: 每次回呼觸發的 gen0 回收次數。抓的是「churn」—— 配置了又馬上丟。
    #:
    #: 這一項才是章程 R1 真正的指標。配置又立刻釋放的 ndarray 淨 block
    #: 是零，看起來很乾淨，但那些垃圾照樣會累積到觸發 gen0 回收，
    #: 而回收發生在哪一次回呼上是不可控的 —— 那就是長尾的來源。
    gen0_per_call: float


def _measure_pressure(engine: TimedEngine, frames: int, rounds: int) -> Pressure:
    """量穩態下的記憶體壓力。

    判定標準刻意是「穩態下不成長」而不是「絕對為零」—— NumPy 的 ufunc 與
    CPython 內部都會產生小型配置，去追那些不是 R1 的成因，只是浪費時間。
    真正要擋的是「每 60 ms 新建一批 ndarray／FFT workspace／filter buffer」。
    """
    gc.collect()
    blocks_before = sys.getallocatedblocks()
    gen0_before = gc.get_stats()[0]["collections"]

    for _ in range(rounds):
        if engine.pump(frames) == 0:
            engine.seek(0.0)

    gen0_after = gc.get_stats()[0]["collections"]
    blocks_after = sys.getallocatedblocks()
    return Pressure(
        net_blocks=(blocks_after - blocks_before) / rounds,
        gen0_per_call=(gen0_after - gen0_before) / rounds,
    )


def install_chain(engine: AudioEngine, chain: str) -> None:
    """把要量測的 DSP 級聯掛上去。

    ``eq`` 刻意用**最大增益**：十段全開 +12 dB 是使用者做得到的最壞情況，
    量最壞情況才有意義。核心長度與 FFT 成本跟增益值無關，但「全平時直接
    跳過」的最佳化會讓平坦設定量不到東西。
    """
    if chain == "none":
        return
    if chain == "eq":
        from aurora.core.constants import EQ_BAND_HZ, EQ_GAIN_LIMIT_DB
        from aurora.core.dynamics import Limiter, OutputMeter
        from aurora.core.eq import GraphicEqualizer

        equalizer = GraphicEqualizer()
        engine.graph.set_stages((equalizer, Limiter(), OutputMeter()))
        equalizer.set_gains([EQ_GAIN_LIMIT_DB] * len(EQ_BAND_HZ))
        return
    raise ValueError(f"未知的 chain：{chain}")


def run_offline(source: Path, sample_rate: int, target: int, frames: int, chain: str) -> int:
    engine = TimedEngine(sample_rate, capacity=target + WARMUP_CALLBACKS + 16)
    install_chain(engine, chain)
    if not engine.load(str(source)):
        print(f"載入失敗：{source}", file=sys.stderr)
        return 2

    # 素材只有十幾秒，要湊到數千次回呼一定得繞回開頭。
    # seek 本身不會呼叫 _process，所以不會混進計時樣本。
    total = target + WARMUP_CALLBACKS
    while engine.count < total:
        if engine.pump(frames) == 0 and not engine.seek(0.0):
            break

    if engine.count <= WARMUP_CALLBACKS:
        print("樣本不足，可能是素材太短或載入失敗。", file=sys.stderr)
        return 2

    # 窗要夠大才問得出 gen0 —— CPython 的門檻是「配置減釋放 > 700」，
    # 窗太小的話「沒觸發」可能只是還沒累積到，而不是真的乾淨。
    pressure = _measure_pressure(engine, frames, rounds=2000)
    engine.close()
    return _report(
        engine.samples_ms()[WARMUP_CALLBACKS:],
        engine.frames_per_call()[WARMUP_CALLBACKS:],
        sample_rate,
        "offline",
        pressure,
    )


def run_device(source: Path, sample_rate: int, target: int, muted: bool, chain: str) -> int:
    """真實裝置 + Qt 事件迴圈 + 60 Hz 分析器 tick。"""
    from PySide6.QtCore import QCoreApplication, QTimer

    app = QCoreApplication(sys.argv[:1])
    engine = TimedEngine(sample_rate, capacity=target + WARMUP_CALLBACKS + 4096)
    engine.muted = muted
    install_chain(engine, chain)

    if not engine.load(str(source)):
        print(f"載入失敗：{source}", file=sys.stderr)
        return 2
    if not engine.play():
        print("開不出音訊裝置。這個模式需要實體音效卡。", file=sys.stderr)
        return 2

    total = target + WARMUP_CALLBACKS

    # 模擬 UI 執行緒：60 Hz 的分析器 tick 是主執行緒上最貴的固定成本，
    # 它與音訊回呼搶 GIL，正是 R1 要抓的情境。
    dt = 1.0 / UI_TICK_HZ
    ui = QTimer()
    ui.setInterval(int(1000 / UI_TICK_HZ))
    ui.timeout.connect(lambda: engine.analyzer.tick(dt))
    ui.start()

    def poll() -> None:
        if engine.take_finished():
            engine.seek(0.0)
            engine.play()
        if engine.count >= total:
            app.quit()

    watchdog = QTimer()
    watchdog.setInterval(50)
    watchdog.timeout.connect(poll)
    watchdog.start()

    app.exec()
    engine.close()

    if engine.count <= WARMUP_CALLBACKS:
        print("樣本不足。", file=sys.stderr)
        return 2

    return _report(
        engine.samples_ms()[WARMUP_CALLBACKS:],
        engine.frames_per_call()[WARMUP_CALLBACKS:],
        sample_rate,
        "device",
        None,  # 事件迴圈與 Qt 自己的配置會蓋掉訊號，這個模式不量配置
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="量測 AudioEngine._process 的執行時間分布。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline",
        action="store_const",
        const="offline",
        dest="mode",
        help="用 pump() 推進，不開音訊裝置。CI 可跑，但數字不具權威性。",
    )
    mode.add_argument(
        "--device",
        action="store_const",
        const="device",
        dest="mode",
        help="真實裝置 + Qt 事件迴圈。權威數字，只能在實體機器上跑。",
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_SOURCE, help="音訊素材")
    parser.add_argument("--rate", type=int, default=FALLBACK_SAMPLE_RATE, help="取樣率")
    parser.add_argument(
        "--callbacks",
        type=int,
        default=5000,
        help="要蒐集的回呼數（暖機之外）。章程 §6.3 要求至少數千次才談 p99.9。",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=REFERENCE_FRAMES,
        help=f"offline 模式每次推進的框數（預設 {REFERENCE_FRAMES}，對齊 60 ms 緩衝）",
    )
    parser.add_argument(
        "--unmuted",
        action="store_true",
        help="device 模式實際出聲。預設靜音，靜音不影響量測代表性。",
    )
    parser.add_argument(
        "--chain",
        choices=("none", "eq"),
        default="none",
        help="要掛上去量的 DSP 級聯。eq = 十段全開 +12 dB + 限幅器 + 輸出電表。",
    )
    parser.set_defaults(mode="offline")
    options = parser.parse_args(argv)

    if not options.file.is_file():
        print(f"找不到素材：{options.file}", file=sys.stderr)
        print("先跑：uv run python tools/make_test_audio.py", file=sys.stderr)
        return 2

    if options.mode == "device":
        return run_device(
            options.file, options.rate, options.callbacks, not options.unmuted, options.chain
        )
    return run_offline(
        options.file, options.rate, options.callbacks, options.frames, options.chain
    )


if __name__ == "__main__":
    raise SystemExit(main())
