"""LRC 歌詞解析。

支援：
* ``[mm:ss]`` / ``[mm:ss.xx]`` / ``[mm:ss.xxx]`` / ``[mm:ss:xx]`` 四種時間格式
* 單行多時間標籤（副歌重複時常見）：``[00:12.00][01:30.50]同一句歌詞``
* ``[offset:±ms]`` 全域時間偏移
* ``[ti:]`` ``[ar:]`` 等中繼標籤
* 增強型逐字標籤：``[00:12.00]<00:12.00>逐<00:12.30>字``

畸形的行一律略過，不拋例外 —— 網路上抓的 LRC 品質參差，播放器不該因此崩潰。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from contextlib import suppress

from aurora.core.models import LyricLine, Lyrics, LyricWord

#: ``[mm:ss.xx]``；小數部分可用 ``.`` 或 ``:`` 分隔，長度 1–3 位。
_TIME_TAG = re.compile(r"\[(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?\]")
#: 逐字標籤 ``<mm:ss.xx>``。
_WORD_TAG = re.compile(r"<(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?>")
#: ``[ti:標題]`` 這類中繼標籤。key 不能是純數字，否則會跟時間標籤搶。
_META_TAG = re.compile(r"\[([a-zA-Z_]+):(.*?)\]")


def _to_seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    total = int(minutes) * 60 + int(seconds)
    if fraction:
        # 1 位 = 十分之一秒、2 位 = 百分之一秒、3 位 = 毫秒
        total += int(fraction) / (10 ** len(fraction))
    return total


def _split_words(body: str) -> tuple[str, tuple[LyricWord, ...]]:
    """把含逐字標籤的內文拆成（純文字, 逐字序列）。"""
    matches = list(_WORD_TAG.finditer(body))
    if not matches:
        return body.strip(), ()

    words: list[LyricWord] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[start:end]
        if not text:
            continue
        words.append(LyricWord(_to_seconds(*match.groups()), text))

    plain = _WORD_TAG.sub("", body).strip()
    return plain, tuple(words)


def parse_lrc(text: str) -> Lyrics:
    """把 LRC 原文解析成 :class:`Lyrics`。永不拋例外。"""
    offset_ms = 0
    title = ""
    artist = ""
    collected: list[LyricLine] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        time_tags = list(_TIME_TAG.finditer(line))
        if not time_tags:
            # 沒有時間標籤 → 只可能是中繼標籤
            for key, value in _META_TAG.findall(line):
                lowered = key.lower()
                if lowered == "offset":
                    with suppress(ValueError):
                        offset_ms = int(value.strip())
                elif lowered == "ti":
                    title = value.strip()
                elif lowered == "ar":
                    artist = value.strip()
            continue

        # 內文 = 最後一個時間標籤之後的部分
        body = line[time_tags[-1].end() :]
        plain, words = _split_words(body)
        if not plain and not words:
            continue

        for tag in time_tags:
            collected.append(LyricLine(_to_seconds(*tag.groups()), plain, words))

    collected.sort(key=lambda item: item.time_sec)
    return Lyrics(tuple(collected), offset_ms, title, artist)


def active_line_index(lyrics: Lyrics, position_sec: float) -> int:
    """回傳當前應高亮的行索引；還沒到第一行時回傳 ``-1``。

    ``offset`` 的語意依 LRC 慣例是「正值表示歌詞應提早顯示」，
    所以是從播放位置**加上** offset 再去比對。
    """
    if lyrics.is_empty:
        return -1
    adjusted = position_sec + lyrics.offset_ms / 1000.0
    times = [line.time_sec for line in lyrics.lines]
    return bisect_right(times, adjusted) - 1


def active_word_index(line: LyricLine, position_sec: float, offset_ms: int = 0) -> int:
    """回傳該行中當前應高亮到第幾個字；沒有逐字資料或還沒開始唱回傳 ``-1``。"""
    if not line.words:
        return -1
    adjusted = position_sec + offset_ms / 1000.0
    times = [word.time_sec for word in line.words]
    return bisect_right(times, adjusted) - 1
