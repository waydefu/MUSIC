"""把同一段音樂用不同的「反射 renderer」各渲染一次，產出盲測用的 WAV。

## 這支工具要回答什麼

早期反射有兩條 renderer：立體聲交叉餵送（P1）與雙耳 HRTF（見
``core/reflections.py``）。哪一條聽起來比較好、後方聲源有沒有從「腦裡」
跑到「腦外」——**只有耳朵能回答**，量測只能證明它們數學上不同。

問題是 A/B 很容易做假：知道哪個是哪個之後，人會「聽到」自己預期的東西。
所以預設就打亂順序，答案另外寫一個檔（與 ``make_direction_test.py`` 同一
個理由，PROJECT_PLAN §9.10）。

## 每一臂只差一個變數

三個關鍵都刻意固定：

* **直達聲的 renderer 每一臂都相同**（耳機空間化開著）。只換反射那一級，
  否則比到的是兩個變數。
* **音量對齊**：每一臂都用 ``core/abcompare`` 把 RMS 對到第一臂。
  0.5 dB 的差距就足以讓盲測失去意義（章程 §15）——而兩條 renderer 的
  總響度本來就會差一點（反射在雙耳那條路上是去相關的，與直達聲相加的
  方式不同）。不對齊的話比到的會是那個差異。
* **走的是真正的級聯**，不是另一份離線重算。渲染路徑就是
  ``AudioEngine`` 加 ``DspGraph``，跟播放時逐位元相同。

## 用法

    uv run python tools/make_reflection_test.py --in "D:/…/song.flac" --out ab

想順便比另一個反射方位角時，先用 ``import_hrtf.py`` 做一組**只給這個實驗
用**的 profile —— ``--dir`` 先填好 0°／30°／110°，再用 ``--at`` 把 110°
那一格換成想試的角度::

    uv run python tools/import_hrtf.py \\
        --dir "D:/…/H13_HRIR_WAV/48K_24bit" \\
        --at 110 "D:/…/azi_60,0_ele_0,0.wav" --name h13-reflect60

    uv run python tools/make_reflection_test.py --in song.flac --out ab \\
        --reflect-profile h13-reflect60

那組 profile 的 110° 格子裡放的其實是 60° 的量測，**只有這支工具會讀到
那一格**。實驗做完就把它從 HRTF 資料夾刪掉，別留在 UI 的下拉選單裡。
"""

from __future__ import annotations

import argparse
import random
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurora.audio.engine import AudioEngine
from aurora.core.abcompare import match_gain_db
from aurora.core.dynamics import Limiter, OutputMeter
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix

FloatArray = npt.NDArray[np.float32]

#: 一次推進多少框。與 bench_callback 的參考值相同，沒有特別的理由要一致，
#: 但用同一個數字比較好對照。
CHUNK = 2880
#: 正規化之後的峰值。留一點餘裕，避免寫進 16-bit 時撞到滿刻度。
PEAK = 0.89


class CapturingEngine(AudioEngine):
    """在 ``_process`` 外面接一條線，把送出去的樣本留下來。

    用繼承而不是改 :mod:`aurora.audio.engine`——渲染工具不該在生產路徑上
    留下任何東西（與 ``bench_callback.TimedEngine`` 同一個做法）。
    """

    def __init__(self, sample_rate: int) -> None:
        super().__init__(sample_rate)
        self._captured: list[bytes] = []

    def _process(self, frame: Any) -> bytes:
        data = super()._process(frame)
        self._captured.append(data)
        return data

    def collected(self) -> FloatArray:
        joined = b"".join(self._captured)
        return np.frombuffer(joined, dtype=np.float32).reshape(-1, 2)


def render(
    source: Path,
    rate: int,
    seconds: float,
    amount: float,
    profile: str,
    binaural_reflections: bool,
    reflect_profile: str | None,
) -> FloatArray:
    """把 ``source`` 跑過一次完整級聯，回傳交錯的立體聲樣本。

    EQ 不掛：它與反射無關，掛上去只是多一個變數。限幅器與電表留著，
    因為那是真正送到耳朵的最後一段。
    """
    engine = CapturingEngine(rate)
    upmix = SpatialUpmix()
    reflections = EarlyReflections()

    upmix.hrtf_profile = profile
    upmix.binaural = True
    reflections.hrtf_profile = reflect_profile if reflect_profile is not None else profile
    reflections.binaural = binaural_reflections

    engine.graph.set_stages((upmix, reflections, Limiter(), OutputMeter()))
    upmix.amount = amount
    reflections.amount = amount

    if not engine.load(str(source)):
        raise ValueError(f"載入失敗：{source}")

    wanted = int(rate * seconds)
    produced = 0
    while produced < wanted:
        advanced = engine.pump(CHUNK)
        if advanced == 0:
            break
        produced += advanced
    engine.close()

    samples = engine.collected()
    return samples[:wanted]


def write_wav(path: Path, rate: int, samples: FloatArray) -> None:
    """寫 16-bit 立體聲 WAV。"""
    clipped = np.clip(samples, -1.0, 1.0)
    data = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


def _rms_db(samples: FloatArray) -> float:
    value = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * np.log10(max(value, 1e-12))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--in", dest="source", type=Path, required=True, help="音樂檔")
    parser.add_argument("--out", type=Path, required=True, help="輸出資料夾")
    parser.add_argument("--rate", type=int, default=48000)
    parser.add_argument("--seconds", type=float, default=25.0, help="每一臂渲染多長")
    parser.add_argument(
        "--amount", type=float, default=1.0, help="空間音效的量（0–1）"
    )
    parser.add_argument(
        "--profile",
        default="",
        help="直達聲用的 HRTF profile。空字串是「自動」，與播放器的預設一致。",
    )
    parser.add_argument(
        "--reflect-profile",
        action="append",
        metavar="名稱",
        help="額外加一臂，反射改用這個 profile。可重複（見模組 docstring）。",
    )
    parser.add_argument(
        "--labelled",
        action="store_true",
        help="不打亂順序、直接用臂的名字當檔名。除錯用，**不要拿來聽測**。",
    )
    options = parser.parse_args(argv)

    arms: list[tuple[str, bool, str | None]] = [
        ("stereo-reflections", False, None),
        ("binaural-reflections", True, None),
    ]
    for name in options.reflect_profile or []:
        arms.append((f"binaural-reflections@{name}", True, name))

    try:
        rendered = [
            (
                label,
                render(
                    options.source,
                    options.rate,
                    options.seconds,
                    options.amount,
                    options.profile,
                    binaural,
                    reflect_profile,
                ),
            )
            for label, binaural, reflect_profile in arms
        ]
    except (OSError, ValueError) as error:
        print(f"渲染失敗：{error}", file=sys.stderr)
        return 1

    if any(samples.size == 0 for _, samples in rendered):
        print("沒有渲染出任何樣本，素材可能太短或載入失敗。", file=sys.stderr)
        return 2

    # 音量對齊到第一臂。用 ``abcompare`` 而不是自己算，理由是它已經定義好
    # 「音量匹配」在這個倉庫裡是什麼意思（章程 §15 的 0.5 dB 判準）。
    reference = rendered[0][1].reshape(-1)
    matched = [
        (label, samples * float(10.0 ** (match_gain_db(reference, samples.reshape(-1)) / 20.0)))
        for label, samples in rendered
    ]

    # 再套一個**共同的**峰值餘裕，避免對齊後撞到滿刻度。共同倍率不會擾動
    # 剛剛對齊好的比例。
    peak = max(float(np.max(np.abs(samples))) for _, samples in matched)
    scale = min(1.0, PEAK / peak) if peak > 0.0 else 1.0

    options.out.mkdir(parents=True, exist_ok=True)
    order = list(range(len(rendered)))
    if not options.labelled:
        random.shuffle(order)

    lines = []
    for position, index in enumerate(order, start=1):
        label, samples = matched[index]
        scaled = (samples * scale).astype(np.float32)
        name = f"{label}.wav" if options.labelled else f"{position}.wav"
        write_wav(options.out / name, options.rate, scaled)
        lines.append(f"{name}\t{label}\t{_rms_db(scaled):+.2f} dBFS RMS")
        print(f"  {name:28s} {label:28s} {_rms_db(scaled):+.2f} dBFS RMS")

    if not options.labelled:
        key = options.out / "key.txt"
        key.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n答案寫在 {key}——**聽完再打開**。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
