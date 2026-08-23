"""方向性聽測訊號的守門測試。

這支工具產生的是**量尺**，所以它自己必須先是對的。最要命的失敗是
**左右顛倒**：那會讓整場聽測的結論反過來，而且聽的人不會察覺 ——
他只會說「這個播放器的定位是反的」，卻不知道錯的是尺。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import make_direction_test as tool

RATE = 48000


def _read(path: Path) -> tuple[int, np.ndarray, np.ndarray]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    frames = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 2)
    return rate, frames[:, 0], frames[:, 1]


def _energy_lead(left: np.ndarray, right: np.ndarray) -> str:
    """哪一耳比較大聲。方位角在哪一側，那一側就該比較大聲。"""
    return "left" if np.sum(left**2) > np.sum(right**2) else "right"


def test_positive_azimuth_is_louder_on_the_right(tmp_path: Path) -> None:
    """正的方位角＝右側。這條抓的是最要命的失敗：整份測試左右顛倒。"""
    out = tmp_path / "right.wav"
    assert tool.main(["--out", str(out), "--azimuths", "90"]) == 0
    _, left, right = _read(out)
    assert _energy_lead(left, right) == "right"


def test_negative_azimuth_is_louder_on_the_left(tmp_path: Path) -> None:
    out = tmp_path / "left.wav"
    assert tool.main(["--out", str(out), "--azimuths", "-90"]) == 0
    _, left, right = _read(out)
    assert _energy_lead(left, right) == "left"


def test_centre_is_symmetric(tmp_path: Path) -> None:
    """正前方兩耳應該幾乎一樣 —— 不對稱代表模型或聲道指派歪了。"""
    out = tmp_path / "centre.wav"
    assert tool.main(["--out", str(out), "--azimuths", "0"]) == 0
    _, left, right = _read(out)
    ratio = np.sum(left**2) / max(np.sum(right**2), 1.0)
    assert 0.9 < ratio < 1.1


def test_shuffle_writes_an_answer_key(tmp_path: Path) -> None:
    """盲測的前提是答案不在耳朵旁邊 —— 但事後要對得了。"""
    out = tmp_path / "blind.wav"
    assert tool.main(["--out", str(out), "--azimuths", "0,30,90", "--shuffle"]) == 0
    key = out.with_suffix(out.suffix + ".key.txt")
    assert key.is_file()
    angles = sorted(line.split()[-1] for line in key.read_text(encoding="utf-8").splitlines())
    assert angles == sorted(["+0°", "+30°", "+90°"])


def test_each_azimuth_gets_its_own_segment(tmp_path: Path) -> None:
    out = tmp_path / "many.wav"
    assert tool.main(["--out", str(out), "--azimuths", "0,90,180"]) == 0
    rate, left, _ = _read(out)
    expected = 3 * (tool.BURST_SEC + tool.GAP_SEC)
    assert abs(left.size / rate - expected) < 0.2


def test_burst_is_broadband(tmp_path: Path) -> None:
    """窄頻訊號聽不出前後 —— 耳廓線索在高頻，沒有寬頻就沒有東西可判斷。"""
    signal = tool.burst(RATE)
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(signal.size, 1.0 / RATE)
    for low, high in ((300.0, 1000.0), (2000.0, 6000.0), (8000.0, 14000.0)):
        band = (freqs >= low) & (freqs < high)
        assert spectrum[band].mean() > spectrum.max() * 0.01, f"{low}–{high} Hz 幾乎是空的"
