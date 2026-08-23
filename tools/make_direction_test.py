"""產生方向性聽測訊號：把一段噪音放到已知的方位角，聽你能不能指對。

## 為什麼需要這支工具

播放器現在**沒有辦法驗證方向對不對**。聽音樂只聽得出音色，聽不出「這個
聲音是不是真的在我後面」—— 因為上混只會把內容放在 0°／±30°／±110°，
聽的人無從得知它「應該」在哪。

所以這支工具跳過整條上混鏈，直接拿 HRTF 把一段噪音擺到指定方位角。
它產生的是**量尺**，不是產品功能：使用者不會在 App 裡看到它。

## 為什麼要能盲測

知道答案之後人會「聽到」自己預期的東西。``--shuffle`` 會把順序打亂並把
答案另外寫成一個檔，聽完再對答案。這比「你覺得有沒有比較好」有判斷力得多。

## 用法

用內建合成模型（任意角度都算得出來）::

    uv run python tools/make_direction_test.py --out test.wav

用真人資料集（角度取最接近的量測格點）::

    uv run python tools/make_direction_test.py \
        --dataset "D:/…/H13_HRIR_WAV/48K_24bit" --shuffle --out test.wav

正的方位角＝右側。要測前後混淆就給對稱的一組，例如 ``--azimuths 30,150``：
兩者的 ITD 與 ILD 幾乎相同，能不能分辨完全靠耳廓的頻譜線索 —— 那正是
非個人化 HRTF 最弱的地方。
"""

from __future__ import annotations

import argparse
import random
import sys
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aurora.core.constants import SPATIAL_FFT_SIZE
from aurora.core.hrtf import ear_pair
from import_hrtf import onset, read_stereo_wav, scan_directory

FloatArray = npt.NDArray[np.float64]

#: 預設要測的方位角。含 30/150 與 −30/−150 兩組前後鏡像 —— 那是最難的一項。
DEFAULT_AZIMUTHS = (0.0, 30.0, 90.0, 150.0, 180.0, -30.0, -90.0, -150.0)
#: 每個方位角的噪音長度與後面的靜音（秒）。
BURST_SEC = 0.6
GAP_SEC = 0.8
#: 讓合成模型的脈衝變成因果的共同偏移。近耳的延遲是負的，不移的話會繞到
#: buffer 尾端。
CAUSAL_OFFSET = 64


def burst(rate: int, seconds: float = BURST_SEC) -> FloatArray:
    """帶通噪音。寬頻才有耳廓線索可用，純音是聽不出前後的。"""
    rng = np.random.default_rng(4242)
    count = int(rate * seconds)
    noise = rng.standard_normal(count)
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(count, 1.0 / rate)
    spectrum[(freqs < 200.0) | (freqs > 16000.0)] = 0.0
    shaped = np.fft.irfft(spectrum, count)
    # 淡入淡出，否則起訖的爆音本身就是個定位線索，會污染判斷。
    fade = int(rate * 0.02)
    envelope = np.ones(count)
    envelope[:fade] = np.linspace(0.0, 1.0, fade)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade)
    return np.asarray(shaped / np.max(np.abs(shaped)) * 0.5 * envelope, dtype=np.float64)


def synthetic_hrir(rate: int, azimuth: float) -> tuple[FloatArray, FloatArray]:
    """合成模型的（左耳, 右耳）脈衝響應。任意角度都算得出來。"""
    fft_size = SPATIAL_FFT_SIZE
    ipsi, contra = ear_pair(rate, fft_size, azimuth)
    freqs = np.fft.rfftfreq(fft_size, d=1.0 / rate)
    causal = np.exp(-2j * np.pi * freqs * CAUSAL_OFFSET / rate)
    near = np.fft.irfft(ipsi * causal, fft_size)
    far = np.fft.irfft(contra * causal, fft_size)
    return (near, far) if azimuth < 0 else (far, near)


def _wrapped(angle: float) -> float:
    """把角度收進 −180…180。資料集常以 0…359 標示，直接相減會差一整圈。"""
    return (angle + 180.0) % 360.0 - 180.0


def dataset_hrir(sources: dict[float, Path], azimuth: float) -> tuple[FloatArray, FloatArray]:
    """從資料集取最接近的量測。回傳（左耳, 右耳）。

    兩件事都不能靠慣例：

    * **角度要繞圈比。** 資料集常以 0…359 標示，``-30°`` 其實是 ``330°``。
    * **左右要從 ITD 判斷。** 資料集的正方向不一定是右邊（SADIE II 是逆時針，
      正值在左），猜錯的話整個測試就是左右顛倒的，而那正是它要測的東西。
      所以照 ``import_hrtf`` 的原則：近耳一定先收到聲音。
    """
    target = abs(_wrapped(azimuth))
    best = min(sources, key=lambda angle: abs(abs(_wrapped(angle)) - target))
    if abs(abs(_wrapped(best)) - target) > 15.0:
        raise ValueError(f"資料集裡找不到接近 {azimuth:g}° 的量測（最近的是 {best:g}°）")

    _, left, right = read_stereo_wav(sources[best])
    if abs(_wrapped(azimuth)) < 1e-6 or abs(abs(_wrapped(azimuth)) - 180.0) < 1e-6:
        return left, right  # 正前方與正後方沒有近遠耳之分

    left_leads = onset(left) < onset(right)
    wants_right = _wrapped(azimuth) > 0.0
    # 近耳在錯的一邊就對調。這一步讓工具不依賴任何資料集的座標慣例。
    return (right, left) if (left_leads == wants_right) else (left, right)


def render(signal: FloatArray, left_ir: FloatArray, right_ir: FloatArray) -> FloatArray:
    """把單聲道訊號擺到那個方向，回傳交錯的立體聲。"""
    left = np.convolve(signal, left_ir)
    right = np.convolve(signal, right_ir)
    return np.stack([left, right], axis=1).reshape(-1)


def write_wav(path: Path, rate: int, interleaved: FloatArray) -> None:
    peak = float(np.max(np.abs(interleaved)))
    scaled = interleaved / peak * 0.89 if peak > 0 else interleaved
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((scaled * 32767).astype("<i2").tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="輸出的 WAV")
    parser.add_argument("--rate", type=int, default=48000)
    parser.add_argument(
        "--azimuths",
        default=",".join(f"{a:g}" for a in DEFAULT_AZIMUTHS),
        help="要測的方位角，逗號分隔。正值＝右側。",
    )
    parser.add_argument("--dataset", type=Path, help="HRIR 資料夾。不給就用內建合成模型。")
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="打亂順序做盲測，答案另外寫成 <out>.key.txt。",
    )
    options = parser.parse_args(argv)

    try:
        azimuths = [float(item) for item in options.azimuths.split(",") if item.strip()]
    except ValueError:
        print("方位角必須是數字", file=sys.stderr)
        return 2
    if not azimuths:
        print("至少要一個方位角", file=sys.stderr)
        return 2

    sources: dict[float, Path] = {}
    if options.dataset is not None:
        sources = scan_directory(options.dataset)
        if not sources:
            print(f"{options.dataset} 裡找不到能解析方位角的 WAV", file=sys.stderr)
            return 2

    order = list(azimuths)
    if options.shuffle:
        random.shuffle(order)

    signal = burst(options.rate)
    gap = np.zeros(int(options.rate * GAP_SEC) * 2)
    pieces: list[FloatArray] = []
    try:
        for azimuth in order:
            if sources:
                left_ir, right_ir = dataset_hrir(sources, azimuth)
            else:
                left_ir, right_ir = synthetic_hrir(options.rate, azimuth)
            pieces.append(render(signal, left_ir, right_ir))
            pieces.append(gap)
    except (OSError, ValueError, wave.Error) as error:
        print(f"產生失敗：{error}", file=sys.stderr)
        return 1

    write_wav(options.out, options.rate, np.concatenate(pieces))

    lines = [f"{index + 1}. {azimuth:+.0f}°" for index, azimuth in enumerate(order)]
    if options.shuffle:
        key = options.out.with_suffix(options.out.suffix + ".key.txt")
        key.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"寫入 {options.out}（{len(order)} 段，順序已打亂）")
        print(f"答案在 {key} —— 聽完再看。")
    else:
        print(f"寫入 {options.out}（{len(order)} 段）")
        print("順序：")
        for line in lines:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
