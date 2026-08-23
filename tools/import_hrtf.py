"""把 HRTF 資料集的 WAV 轉成 AURORA 用的 ``hrtf.npz``。

## 為什麼是 WAV 而不是 SOFA

SOFA 是 HDF5，要讀它得引進 ``h5py``。那是**執行期**相依，會被打進 EXE ——
為了一個多數使用者不會用到的功能撐大 bundle 並不划算。SADIE II 這類資料集
同時提供 WAV 版的 HRIR，而 WAV 用標準函式庫就讀得了。

## 為什麼不把資料放進版控

資料集各有授權（SADIE II 是 Apache-2.0，但不是每一套都能再散布），而且
動輒數百 MB。所以流程是：使用者自己下載 → 用這支工具轉出幾 KB 的 npz →
放進使用者資料目錄。檔案不在時 renderer 自動退回合成頭模型。

## 用法

方位角能從檔名解析出來時（多數資料集的格點命名都可以）::

    uv run python tools/import_hrtf.py --dir <資料夾>

解析不出來就直接指定要哪幾個檔案 —— 這條路一定行得通::

    uv run python tools/import_hrtf.py \
        --at 0 azi_0.wav --at 30 azi_30.wav --at 110 azi_110.wav

WAV 必須是**立體聲**：一軌左耳、一軌右耳。

## 兩件不能靠文件、只能靠量測的事

**哪一軌是近耳。** 資料集的方位角正方向不一定一致 —— SADIE II 是逆時針，
所以 +30° 在**左**邊；換一套資料集可能相反。猜錯的話整個音場左右顛倒，
而那用聽的很難確定是哪一邊錯。所以這裡不看慣例，直接量：**近耳一定先
收到聲音**。量不出來（兩耳同時）時左右其實等價，隨便挑；兩個方位角互相
矛盾時就停下來，要求用 ``--near-ear`` 明講。

**共模傳播延遲。** 量測的 HRIR 前面有一段空白（H13 是 102 個取樣 ≈ 2.1 ms），
那是聲音從喇叭走到頭的時間，兩耳都有。renderer 會把濕訊號與乾訊號交叉
淡入，濕的被延後而乾的沒有 → 兩者相加就是梳狀濾波（102 個取樣在 48 kHz
下每 471 Hz 一個凹陷，聽起來很空）。所以匯入時把這段共模延遲切掉，
**所有位置切掉同樣的量**：兩耳之間的 ITD 與各虛擬喇叭之間的相對時序
都因此原封不動，只有共同的那一段消失。

轉出來的內容是**近耳／遠耳**而不是左右耳。座標慣例只在這裡處理一次，
``core/hrtf.py`` 就不必知道任何資料集的細節。
"""

from __future__ import annotations

import argparse
import re
import sys
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurora.core.constants import (
    HRTF_FRONT_AZIMUTH_DEG,
    HRTF_SURROUND_AZIMUTH_DEG,
)
from aurora.core.paths import hrtf_dir, hrtf_file

FloatArray = npt.NDArray[np.float64]

#: 要匯出的方位角。場景左右對稱，所以只取正的一半（見 core/hrtf.py 的推導）。
TARGETS = (0.0, HRTF_FRONT_AZIMUTH_DEG, HRTF_SURROUND_AZIMUTH_DEG)
#: 檔名裡的方位角／仰角。逗號當小數點是資料集常見的寫法（``azi_30,0``）。
_AZIMUTH_RE = re.compile(r"azi[_\-]?(-?\d+(?:[.,]\d+)?)", re.IGNORECASE)
_ELEVATION_RE = re.compile(r"ele[_\-]?(-?\d+(?:[.,]\d+)?)", re.IGNORECASE)
#: 量測格點與目標最多差幾度。與 core/hrtf.py 的容差一致。
_TOLERANCE_DEG = 7.5
#: 起音判定：包絡首次超過峰值的這個比例。用包絡而不是 argmax —— HRIR 的
#: 最大值不一定在第一個波前上，尤其耳廓造成的反射會讓後面出現更高的峰。
_ONSET_THRESHOLD = 0.2
#: 判定「哪耳先」所需的最小取樣差。小於這個值視為兩耳同時，此時左右等價。
_LEAD_TOLERANCE = 2
#: 切掉共模延遲時在最早的起音前面保留幾個取樣，避免削掉波前本身。
_ONSET_GUARD = 8


def read_stereo_wav(path: Path) -> tuple[int, FloatArray, FloatArray]:
    """讀立體聲 WAV，回傳 ``(取樣率, 左, 右)``，正規化到 −1..1。"""
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 2:
            raise ValueError(f"{path.name} 不是立體聲（左耳／右耳各一軌）")
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        # 32-bit 的 HRIR 幾乎都是 float；整數版的話下面的正規化會偏掉，
        # 但 HRTF 只在乎相對關係，整體增益不影響方向線索。
        samples = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    elif width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        value = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        samples = np.where(value & 0x800000, value - 0x1000000, value) / 8388608.0
    else:
        raise ValueError(f"{path.name} 的位元深度不支援（{width * 8}-bit）")

    frames = samples.reshape(-1, 2)
    return rate, frames[:, 0], frames[:, 1]


def _parse_angle(text: str) -> float:
    return float(text.replace(",", "."))


def scan_directory(directory: Path) -> dict[float, Path]:
    """掃描資料夾，回傳 ``{方位角: 檔案}``，只收仰角 0 的量測。

    檔名解析不出來的檔案直接跳過 —— 猜錯方位角比找不到檔案糟得多。
    """
    found: dict[float, Path] = {}
    for path in sorted(directory.rglob("*.wav")):
        azimuth = _AZIMUTH_RE.search(path.stem)
        if azimuth is None:
            continue
        elevation = _ELEVATION_RE.search(path.stem)
        if elevation is not None and abs(_parse_angle(elevation.group(1))) > 1e-6:
            continue
        found.setdefault(_parse_angle(azimuth.group(1)), path)
    return found


def pick(available: dict[float, Path], target: float) -> Path:
    """挑最接近目標方位角的量測。左右對稱，所以 −30° 也可以拿來當 +30°。"""
    if not available:
        raise ValueError("沒有可用的量測")
    best = min(available, key=lambda angle: abs(abs(angle) - target))
    if abs(abs(best) - target) > _TOLERANCE_DEG:
        raise ValueError(
            f"找不到接近 {target:g}° 的量測（最接近的是 {best:g}°，差太多）"
        )
    return available[best]


def onset(response: FloatArray) -> int:
    """波前抵達的取樣位置。

    用**包絡首次超過峰值比例**而不是 ``argmax`` —— HRIR 的最大值不一定落在
    第一個波前上，耳廓造成的反射常常讓後面出現更高的峰。
    """
    envelope = np.abs(response)
    peak = float(envelope.max())
    if peak <= 0.0:
        return 0
    return int(np.argmax(envelope > peak * _ONSET_THRESHOLD))


def detect_near_ear(measured: dict[float, tuple[FloatArray, FloatArray]]) -> str:
    """從資料量出哪一軌是近耳。**近耳一定先收到聲音。**

    只看非 0° 的方位角：正前方兩耳同時抵達，沒有資訊。回傳 ``"left"`` 或
    ``"right"``；兩個方位角互相矛盾時拋例外，要求呼叫端明講。
    """
    leads: list[int] = []
    for azimuth, (left, right) in measured.items():
        if abs(azimuth) < 1e-6:
            continue
        leads.append(onset(right) - onset(left))

    if all(lead > _LEAD_TOLERANCE for lead in leads):
        return "left"
    if all(lead < -_LEAD_TOLERANCE for lead in leads):
        return "right"
    if all(abs(lead) <= _LEAD_TOLERANCE for lead in leads):
        # 兩耳同時 ⇒ 左右等價，挑哪邊都不影響結果。
        return "right"
    raise ValueError(
        f"各方位角量到的近耳不一致（右耳減左耳的起音差：{leads}）。"
        "請用 --near-ear left|right 明確指定。"
    )


def build(sources: dict[float, Path], near_ear: str | None = None) -> dict[str, object]:
    """讀出每個方位角的近耳／遠耳 HRIR，組成 npz 的內容。"""
    rates: set[int] = set()
    lengths: set[int] = set()
    measured: dict[float, tuple[FloatArray, FloatArray]] = {}

    for target in TARGETS:
        rate, left, right = read_stereo_wav(sources[target])
        rates.add(rate)
        lengths.add(left.size)
        measured[target] = (left, right)

    if len(rates) != 1:
        raise ValueError(f"各檔案的取樣率不一致：{sorted(rates)}")
    if len(lengths) != 1:
        raise ValueError(f"各檔案的長度不一致：{sorted(lengths)}")

    near = near_ear or detect_near_ear(measured)
    if near not in ("left", "right"):
        raise ValueError(f"--near-ear 只能是 left 或 right，收到 {near!r}")

    ipsi = [measured[t][0 if near == "left" else 1] for t in TARGETS]
    contra = [measured[t][1 if near == "left" else 0] for t in TARGETS]

    # 切掉共模傳播延遲。**所有位置切掉同樣的量**，所以兩耳的 ITD 與各虛擬
    # 喇叭之間的相對時序都不變，消失的只有共同的那一段（見模組 docstring）。
    earliest = min(onset(response) for response in (*ipsi, *contra))
    trim = max(0, earliest - _ONSET_GUARD)
    ipsi = [response[trim:] for response in ipsi]
    contra = [response[trim:] for response in contra]

    return {
        "sample_rate": np.int32(rates.pop()),
        "azimuths": np.asarray(TARGETS, dtype=np.float64),
        "ipsi": np.asarray(ipsi, dtype=np.float64),
        "contra": np.asarray(contra, dtype=np.float64),
        "near_ear": near,
        "trimmed": np.int32(trim),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, help="HRIR WAV 所在的資料夾（依檔名解析方位角）")
    parser.add_argument(
        "--at",
        nargs=2,
        action="append",
        metavar=("方位角", "WAV"),
        help="直接指定某個方位角要用哪個檔案。可重複；解析不出檔名時用這個。",
    )
    parser.add_argument(
        "--near-ear",
        choices=("left", "right"),
        help=(
            "正方位角那一側對應哪一軌。預設從 ITD 自己量出來（近耳一定先收到"
            "聲音），只有量不出來或互相矛盾時才需要指定。"
        ),
    )
    parser.add_argument(
        "--name",
        help=(
            "存成具名的 profile（放進 HRTF 資料夾）。匯入多組耳朵做 A/B 時用這個，"
            "例如 --name ku100。不給的話寫到舊版的單檔位置。"
        ),
    )
    parser.add_argument("--out", type=Path, help="輸出路徑。指定了就蓋過 --name。")
    options = parser.parse_args(argv)

    sources: dict[float, Path] = {}
    try:
        if options.dir is not None:
            available = scan_directory(options.dir)
            if not available:
                print(
                    f"{options.dir} 裡找不到能解析方位角的 WAV。改用 --at 指定。",
                    file=sys.stderr,
                )
                return 2
            sources = {target: pick(available, target) for target in TARGETS}
        for angle, name in options.at or []:
            sources[float(angle)] = Path(name)

        missing = [target for target in TARGETS if target not in sources]
        if missing:
            print(f"缺少這些方位角的量測：{missing}", file=sys.stderr)
            return 2

        payload = build(sources, options.near_ear)
    except (OSError, ValueError, wave.Error) as error:
        print(f"轉換失敗：{error}", file=sys.stderr)
        return 1

    if options.out is not None:
        out = options.out
    elif options.name:
        out = hrtf_dir() / f"{options.name}.npz"
    else:
        out = hrtf_file()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, **payload)

    taps = int(payload["ipsi"].shape[1])  # type: ignore[union-attr]
    print(f"寫入 {out}")
    print(f"  取樣率 {int(payload['sample_rate'])} Hz、{taps} 抽頭、方位角 {list(TARGETS)}")
    how = "量測判定" if options.near_ear is None else "手動指定"
    print(f"  近耳 = {payload['near_ear']} 軌（{how}）")
    print(f"  切掉共模延遲 {int(payload['trimmed'])} 個取樣")
    for target in TARGETS:
        print(f"  {target:6.1f}° ← {sources[target].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
