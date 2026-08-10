"""產生測試音檔語料庫。

刻意設計成能驗證幾件難驗證的事：

* **全頻譜內容** —— 白噪音鋪底，這樣無損檔的頻譜會一路到 Nyquist，
  而 128 kbps 的 MP3 會在 16 kHz 附近出現磚牆，頻譜截止偵測才有東西可量。
* **明確的鼓點** —— 每 0.5 秒一次的瞬態，用來驗證 onset 偵測。
* **假無損** —— 先壓成 128 kbps MP3 再轉回 FLAC，用來驗證「疑似轉檔」的判定。
* **三種容器的封面** —— MP3 的 APIC、FLAC 的 Picture block、OGG 的
  base64 ``metadata_block_picture``，三條路徑各不相同，都要能讀出來。

基礎波形由 numpy 產生（確定性、不依賴外部工具），只有格式轉換用 ffmpeg。

用法::

    .venv\\Scripts\\python.exe tools\\make_test_audio.py
"""

from __future__ import annotations

import struct
import subprocess
import sys
import wave
import zlib
from pathlib import Path

import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "_generated"
SAMPLE_RATE = 44100
DURATION_SEC = 12.0
BEAT_INTERVAL_SEC = 0.5


# ---------------------------------------------------------------- 波形


def build_signal() -> np.ndarray:
    """白噪音鋪底 + 低音 + 規律鼓點，回傳 (N, 2) 的 float32。"""
    rng = np.random.default_rng(20260810)
    count = int(SAMPLE_RATE * DURATION_SEC)
    time = np.arange(count, dtype=np.float64) / SAMPLE_RATE

    # 全頻譜鋪底：有損編碼會把高頻砍掉，這正是我們要量的
    noise = rng.standard_normal(count) * 0.06
    bass = np.sin(2 * np.pi * 110.0 * time) * 0.20
    pad = np.sin(2 * np.pi * 440.0 * time) * 0.08

    # 瞬態鼓點：短促、寬頻、指數衰減
    hits = np.zeros(count)
    burst = int(SAMPLE_RATE * 0.035)
    envelope = np.exp(-np.linspace(0.0, 8.0, burst))
    for index in range(1, int(DURATION_SEC / BEAT_INTERVAL_SEC)):
        start = int(index * BEAT_INTERVAL_SEC * SAMPLE_RATE)
        if start + burst > count:
            break
        hits[start : start + burst] += rng.standard_normal(burst) * envelope * 0.55

    mono = noise + bass + pad + hits
    mono /= np.max(np.abs(mono)) * 1.08  # 留一點餘裕，避免無意產生削波

    # 左右聲道給一點差異，才驗得出混音是否正確
    left = mono
    right = np.roll(mono, 64) * 0.94
    return np.stack([left, right], axis=1).astype(np.float32)


def write_wav(path: Path, signal: np.ndarray) -> None:
    pcm = np.clip(signal, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(data.tobytes())


# ---------------------------------------------------------------- 封面


def write_png(path: Path, size: int = 500) -> None:
    """畫一張紫→橙的對角漸層 PNG。自己寫編碼器，免得為了這個引入 Pillow。"""
    axis = np.linspace(0.0, 1.0, size, dtype=np.float32)
    gradient = (axis[None, :] + axis[:, None]) / 2.0

    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[..., 0] = np.clip(123 + gradient * 132, 0, 255)  # R: 123 → 255
    image[..., 1] = np.clip(47 + gradient * 120, 0, 255)  # G:  47 → 167
    image[..., 2] = np.clip(247 - gradient * 200, 0, 255)  # B: 247 → 47

    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(size))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------- 轉檔


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
    )


def has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


# ---------------------------------------------------------------- 標籤


def tag_files(cover: bytes) -> None:
    """把標題／演出者／專輯與封面寫進三種容器，各走各的路徑。"""
    import base64

    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
    from mutagen.oggvorbis import OggVorbis

    def picture() -> Picture:
        item = Picture()
        item.type = 3  # front cover
        item.mime = "image/png"
        item.desc = "Cover"
        item.data = cover
        return item

    for name in ("test_128k.mp3", "test_320k.mp3"):
        path = OUTPUT_DIR / name
        tags = ID3()
        tags.add(TIT2(encoding=3, text="測試曲目"))
        tags.add(TPE1(encoding=3, text="AURORA 測試"))
        tags.add(TALB(encoding=3, text="語料庫"))
        tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=cover))
        tags.save(path)

    for name in ("test.flac", "fake_lossless.flac"):
        audio = FLAC(OUTPUT_DIR / name)
        audio["title"] = "測試曲目"
        audio["artist"] = "AURORA 測試"
        audio["album"] = "語料庫"
        audio.add_picture(picture())
        audio.save()

    ogg = OggVorbis(OUTPUT_DIR / "test.ogg")
    ogg["title"] = "測試曲目"
    ogg["artist"] = "AURORA 測試"
    ogg["album"] = "語料庫"
    # OGG 的封面是 base64 過的 FLAC Picture block，跟前兩者完全不同
    ogg["metadata_block_picture"] = [base64.b64encode(picture().write()).decode("ascii")]
    ogg.save()


LRC = """[ti:測試曲目]
[ar:AURORA 測試]
[offset:0]
[00:00.00]第一句歌詞
[00:02.50]第二句歌詞
[00:05.00]<00:05.00>逐<00:05.40>字<00:06.00>高亮測試
[00:08.00]第四句歌詞
[00:11.00]最後一句
"""


# ---------------------------------------------------------------- 主流程


def main() -> int:
    if not has_ffmpeg():
        print("找不到 ffmpeg。這個工具只用來產生測試素材，播放器本身不需要它。")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"輸出目錄：{OUTPUT_DIR}")

    signal = build_signal()
    source = OUTPUT_DIR / "test.wav"
    write_wav(source, signal)
    print(f"  test.wav              {source.stat().st_size / 1024:.0f} KB")

    cover_path = OUTPUT_DIR / "cover.png"
    write_png(cover_path)
    cover = cover_path.read_bytes()
    print(f"  cover.png             {len(cover) / 1024:.0f} KB")

    ffmpeg("-i", str(source), "-b:a", "128k", str(OUTPUT_DIR / "test_128k.mp3"))
    ffmpeg("-i", str(source), "-b:a", "320k", str(OUTPUT_DIR / "test_320k.mp3"))
    ffmpeg("-i", str(source), str(OUTPUT_DIR / "test.flac"))
    ffmpeg("-i", str(source), "-q:a", "6", str(OUTPUT_DIR / "test.ogg"))
    # 假無損：128k MP3 再包成 FLAC，容器是無損但內容早就被砍過高頻了
    ffmpeg("-i", str(OUTPUT_DIR / "test_128k.mp3"), str(OUTPUT_DIR / "fake_lossless.flac"))

    tag_files(cover)
    (OUTPUT_DIR / "test.lrc").write_text(LRC, encoding="utf-8")
    (OUTPUT_DIR / "test_320k.lrc").write_text(LRC, encoding="utf-8")

    print("\n產生完成：")
    for path in sorted(OUTPUT_DIR.iterdir()):
        print(f"  {path.name:<24} {path.stat().st_size / 1024:8.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
