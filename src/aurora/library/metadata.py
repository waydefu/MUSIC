"""用 mutagen 讀標籤與內嵌封面。

封面在三種容器裡的存法完全不同，所以有三條獨立路徑：

MP3
    ID3 的 ``APIC`` 影格，圖檔位元組直接放在 ``frame.data``。
FLAC
    原生的 Picture metadata block，``FLAC.pictures`` 直接給你物件清單。
OGG Vorbis
    Vorbis comment 只能存文字，所以圖是「FLAC Picture block 再做 base64」
    塞進 ``metadata_block_picture`` 欄位，得先解碼再解析。

時長一律取自標籤（``info.length``），不解碼音訊 —— 掃描一萬首歌時
這個差別是幾秒與幾分鐘。
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from aurora.core.constants import LYRICS_EXTENSION
from aurora.core.models import AudioFormat, Track
from aurora.core.paths import covers_dir

#: 這些容器本身不做有損壓縮。
_LOSSLESS_SUFFIXES = frozenset({".flac", ".wav"})

#: Vorbis comment 與 ID3 easy 模式共用的鍵名。
_TITLE_KEYS = ("title", "TIT2")
_ARTIST_KEYS = ("artist", "TPE1")
_ALBUM_KEYS = ("album", "TALB")

#: 內嵌歌詞可能出現的標籤名。
_LYRICS_KEYS = ("lyrics", "unsyncedlyrics", "USLT")


def _first_text(tags: object, keys: tuple[str, ...]) -> str:
    """從 mutagen 的標籤容器取第一個字串值。各容器的介面不一致，統一在這裡吸收。"""
    if tags is None:
        return ""
    for key in keys:
        try:
            value = tags[key]  # type: ignore[index]
        except (KeyError, TypeError):
            continue
        if value is None:
            continue
        if isinstance(value, str):
            return value.strip()
        with contextlib.suppress(TypeError, IndexError, AttributeError):
            first = value[0] if not isinstance(value, str) else value
            return str(first).strip()
    return ""


def _cover_bytes(audio: mutagen.FileType, suffix: str) -> bytes:
    """依容器型別取出封面位元組。找不到回傳空 bytes。"""
    with contextlib.suppress(Exception):
        if suffix == ".mp3" and isinstance(audio.tags, ID3):
            frames = audio.tags.getall("APIC")
            if frames:
                # type 3 是正面封面；沒有就退而求其次用第一張
                front = next((item for item in frames if item.type == 3), frames[0])
                return bytes(front.data)

        if isinstance(audio, FLAC) and audio.pictures:
            front = next((item for item in audio.pictures if item.type == 3), audio.pictures[0])
            return bytes(front.data)

        if isinstance(audio, OggVorbis):
            encoded = audio.get("metadata_block_picture")  # type: ignore[no-untyped-call]
            if encoded:
                picture = Picture(base64.b64decode(encoded[0]))  # type: ignore[no-untyped-call]
                return bytes(picture.data)
    return b""


#: 影像格式的魔術位元組。內嵌封面的 MIME 標記常常是錯的或缺的，
#: 而 QML 的 Image 需要正確副檔名才認得出格式，所以自己嗅探。
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF8", ".gif"),
    (b"BM", ".bmp"),
    (b"RIFF", ".webp"),
)


def _image_suffix(data: bytes) -> str:
    for signature, suffix in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return suffix
    return ".jpg"


def _cache_cover(data: bytes) -> str | None:
    """把封面寫進快取目錄，回傳路徑。內容相同的圖只會存一份。"""
    if not data:
        return None
    digest = hashlib.sha1(data, usedforsecurity=False).hexdigest()[:20]
    target = covers_dir() / f"{digest}{_image_suffix(data)}"
    if not target.exists():
        try:
            target.write_bytes(data)
        except OSError:
            return None
    return str(target)


def _audio_format(info: object, suffix: str) -> AudioFormat | None:
    rate = int(getattr(info, "sample_rate", 0) or 0)
    if rate <= 0:
        return None
    channels = int(getattr(info, "channels", 2) or 2)
    # 有損容器沒有「位元深度」可言，一律以 16 表示解碼後的常見寬度
    bits = int(getattr(info, "bits_per_sample", 0) or 16)
    return AudioFormat(rate, channels, bits)


def read_track_stub(path: str | Path) -> Track | None:
    """只讀檔案系統資訊，建立可立即顯示的輕量曲目。

    完整的 :func:`read_track` 會開啟容器、解析標籤並抽出內嵌封面；一次讀幾百首時
    這些工作不適合放在 Qt 主執行緒。播放清單先用這個版本顯示檔名，背景讀取完成
    後再以完整 ``Track`` 原地替換，使用者不必等整張清單解析完才能播放。
    """
    target = Path(path)
    try:
        stat = target.stat()
    except OSError:
        return None

    suffix = target.suffix.lower()
    return Track(
        path=str(target),
        title=target.stem,
        codec=suffix.lstrip("."),
        lossless=suffix in _LOSSLESS_SUFFIXES,
        mtime=stat.st_mtime,
        size=stat.st_size,
    )


def read_track(path: str | Path) -> Track | None:
    """讀出一首曲目的完整中繼資料。任何解析失敗都回傳 ``None``，不拋例外。"""
    target = Path(path)
    try:
        stat = target.stat()
    except OSError:
        return None

    suffix = target.suffix.lower()
    try:
        audio = mutagen.File(target)
    except Exception:
        audio = None

    if audio is None:
        # 讀不到標籤仍然當成可播的曲目，只是資訊少一點
        return Track(
            path=str(target),
            title=target.stem,
            codec=suffix.lstrip("."),
            lossless=suffix in _LOSSLESS_SUFFIXES,
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    info = getattr(audio, "info", None)
    duration = float(getattr(info, "length", 0.0) or 0.0)
    bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000

    # 無損容器的 mutagen 不一定給 bitrate，用檔案大小自己算
    if bitrate <= 0 and duration > 0:
        bitrate = int(stat.st_size * 8 / duration / 1000)

    return Track(
        path=str(target),
        title=_first_text(audio.tags, _TITLE_KEYS) or target.stem,
        artist=_first_text(audio.tags, _ARTIST_KEYS),
        album=_first_text(audio.tags, _ALBUM_KEYS),
        duration_sec=duration,
        fmt=_audio_format(info, suffix),
        bitrate_kbps=bitrate or None,
        codec=_codec_name(audio, suffix),
        lossless=suffix in _LOSSLESS_SUFFIXES,
        cover_path=_cache_cover(_cover_bytes(audio, suffix)),
        year=_first_text(audio.tags, ("date", "TDRC", "year")),
        mtime=stat.st_mtime,
        size=stat.st_size,
    )


def _codec_name(audio: mutagen.FileType, suffix: str) -> str:
    if isinstance(audio, MP3):
        return "mp3"
    if isinstance(audio, FLAC):
        return "flac"
    if isinstance(audio, OggVorbis):
        return "vorbis"
    if isinstance(audio, WAVE):
        return "wav"
    return suffix.lstrip(".")


def read_lyrics_text(path: str | Path) -> str:
    """取得歌詞原文：先找同名 ``.lrc``，再退回內嵌標籤。都沒有回空字串。"""
    target = Path(path)
    sidecar = target.with_suffix(LYRICS_EXTENSION)
    if sidecar.is_file():
        for encoding in ("utf-8-sig", "utf-8", "cp950", "gbk", "latin-1"):
            try:
                return sidecar.read_text(encoding=encoding)
            except (UnicodeDecodeError, OSError):
                continue

    try:
        audio = mutagen.File(target)
    except Exception:
        return ""
    if audio is None or audio.tags is None:
        return ""

    # ID3 的 USLT 影格鍵名帶語言與描述後綴，得用前綴比對
    with contextlib.suppress(Exception):
        if isinstance(audio.tags, ID3):
            frames = audio.tags.getall("USLT")  # type: ignore[no-untyped-call]
            if frames:
                return str(frames[0].text)

    return _first_text(audio.tags, _LYRICS_KEYS)
