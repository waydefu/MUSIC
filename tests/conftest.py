"""共用 fixture。

測試素材由 ``tools/make_test_audio.py`` 產生到 ``tests/_generated``。
沒產生過就 skip，而不是讓整個測試套件紅掉 —— 那些檔案要 ffmpeg 才做得出來。
"""

from __future__ import annotations

from pathlib import Path

import pytest

GENERATED = Path(__file__).resolve().parent / "_generated"


@pytest.fixture(scope="session")
def generated_dir() -> Path:
    if not GENERATED.is_dir() or not any(GENERATED.glob("*.flac")):
        pytest.skip("尚未產生測試素材，請先跑 tools/make_test_audio.py")
    return GENERATED


@pytest.fixture(scope="session")
def flac_path(generated_dir: Path) -> Path:
    return generated_dir / "test.flac"


@pytest.fixture(scope="session")
def mp3_path(generated_dir: Path) -> Path:
    return generated_dir / "test_320k.mp3"


@pytest.fixture(scope="session")
def ogg_path(generated_dir: Path) -> Path:
    return generated_dir / "test.ogg"


@pytest.fixture(scope="session")
def wav_path(generated_dir: Path) -> Path:
    return generated_dir / "test.wav"


@pytest.fixture(scope="session")
def fake_lossless_path(generated_dir: Path) -> Path:
    return generated_dir / "fake_lossless.flac"
