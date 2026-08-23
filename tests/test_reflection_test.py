"""反射盲測工具的守門測試。

這支工具產生的是**量尺**，所以它自己要先是對的。它有兩個承諾，兩個都
可以機器判定：**每一臂等響度**（不然比到的是音量，不是 renderer），
以及**每一臂真的不一樣**（不然整場聽測是在跟自己比）。

答案檔的存在也守著 —— 沒有它，聽完之後沒有辦法知道自己選了哪一個。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import make_reflection_test as tool

#: 釘死合成模型。不釘的話有匯入 HRTF 的開發機與 CI 驗的不是同一個東西
#: （與 ``tests/test_reflections.py`` 的 ``_binaural`` 同一個理由）。
PROFILE = "synthetic"
SECONDS = 2.0


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, 2)


def _rms_db(samples: np.ndarray) -> float:
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(samples**2))), 1e-12))


def _run(out: Path, source: Path, *extra: str) -> int:
    return tool.main(
        [
            "--in",
            str(source),
            "--out",
            str(out),
            "--seconds",
            str(SECONDS),
            "--profile",
            PROFILE,
            *extra,
        ]
    )


def test_arms_are_level_matched(tmp_path: Path, flac_path: Path) -> None:
    """**這支工具的核心承諾。**

    章程 §15 的門檻是 0.5 dB，這裡收得更緊 —— 工具自己做的對齊應該是
    精確的，鬆掉就代表對齊那一步壞了，而不是素材的問題。
    """
    assert _run(tmp_path, flac_path, "--labelled") == 0
    levels = [_rms_db(_read(path)) for path in sorted(tmp_path.glob("*.wav"))]
    assert len(levels) == 2
    assert max(levels) - min(levels) < 0.1


def test_the_arms_are_actually_different(tmp_path: Path, flac_path: Path) -> None:
    """兩臂一樣的話整場聽測是在跟自己比，而且不會有任何徵兆。"""
    assert _run(tmp_path, flac_path, "--labelled") == 0
    stereo = _read(tmp_path / "stereo-reflections.wav")
    binaural = _read(tmp_path / "binaural-reflections.wav")
    assert stereo.shape == binaural.shape
    assert not np.array_equal(stereo, binaural)


def test_shuffle_writes_an_answer_key(tmp_path: Path, flac_path: Path) -> None:
    """預設就盲測。知道答案之後人會「聽到」自己預期的東西（§9.10）。"""
    assert _run(tmp_path, flac_path) == 0
    key = tmp_path / "key.txt"
    assert key.is_file()

    text = key.read_text(encoding="utf-8")
    assert "stereo-reflections" in text
    assert "binaural-reflections" in text
    # 檔名不能洩漏答案。
    assert {path.name for path in tmp_path.glob("*.wav")} == {"1.wav", "2.wav"}


def test_missing_source_fails_loudly(tmp_path: Path) -> None:
    """素材載入不了要回非零，不要寫出一組空檔讓人拿去聽。"""
    assert _run(tmp_path, tmp_path / "沒有這個檔.flac") != 0


@pytest.mark.parametrize("labelled", [True, False])
def test_output_is_the_requested_length(
    tmp_path: Path, flac_path: Path, labelled: bool
) -> None:
    """每一臂長度相同，否則 A/B 會在不同的段落上比較。"""
    extra = ["--labelled"] if labelled else []
    assert _run(tmp_path, flac_path, *extra) == 0
    lengths = {_read(path).shape[0] for path in tmp_path.glob("*.wav")}
    assert len(lengths) == 1
    assert lengths.pop() == int(48000 * SECONDS)
