from aurora.core.lrc import active_line_index, active_word_index, parse_lrc


def test_parses_basic_lines_in_time_order() -> None:
    lyrics = parse_lrc("[00:12.50]第二句\n[00:03.20]第一句\n")
    assert [line.text for line in lyrics.lines] == ["第一句", "第二句"]
    assert lyrics.lines[0].time_sec == 3.2
    assert lyrics.lines[1].time_sec == 12.5


def test_single_line_with_multiple_time_tags_expands() -> None:
    """副歌重複時常見的寫法，同一句掛多個時間。"""
    lyrics = parse_lrc("[00:10.00][01:20.00][02:30.00]副歌")
    assert len(lyrics.lines) == 3
    assert {line.text for line in lyrics.lines} == {"副歌"}
    assert [line.time_sec for line in lyrics.lines] == [10.0, 80.0, 150.0]


def test_fraction_digits_scale_correctly() -> None:
    assert parse_lrc("[00:01.5]甲").lines[0].time_sec == 1.5
    assert parse_lrc("[00:01.50]乙").lines[0].time_sec == 1.5
    assert parse_lrc("[00:01.500]丙").lines[0].time_sec == 1.5
    # 有些工具用冒號當小數分隔
    assert parse_lrc("[00:01:25]丁").lines[0].time_sec == 1.25


def test_metadata_and_offset() -> None:
    lyrics = parse_lrc("[ti:歌名]\n[ar:歌手]\n[offset:-500]\n[00:05.00]句子")
    assert lyrics.title == "歌名"
    assert lyrics.artist == "歌手"
    assert lyrics.offset_ms == -500


def test_malformed_lines_are_skipped_without_raising() -> None:
    text = "\n".join(
        [
            "這行沒有任何標籤",
            "[99:99.99]秒數不合法所以整行不算時間標籤",
            "[offset:不是數字]",
            "[]",
            "[00:04.00]",  # 有時間但沒內文
            "[00:08.00]唯一有效的一行",
        ]
    )
    lyrics = parse_lrc(text)
    assert [line.text for line in lyrics.lines] == ["唯一有效的一行"]
    assert lyrics.offset_ms == 0


def test_word_level_timing() -> None:
    lyrics = parse_lrc("[00:10.00]<00:10.00>逐<00:10.40>字<00:11.00>高亮")
    line = lyrics.lines[0]
    assert line.text == "逐字高亮"
    assert lyrics.has_word_timing
    assert [word.text for word in line.words] == ["逐", "字", "高亮"]
    assert [word.time_sec for word in line.words] == [10.0, 10.4, 11.0]


def test_active_line_index_tracks_position() -> None:
    lyrics = parse_lrc("[00:00.00]甲\n[00:10.00]乙\n[00:20.00]丙")
    assert active_line_index(lyrics, -1.0) == -1
    assert active_line_index(lyrics, 0.0) == 0
    assert active_line_index(lyrics, 9.99) == 0
    assert active_line_index(lyrics, 10.0) == 1
    assert active_line_index(lyrics, 999.0) == 2


def test_active_line_index_honours_offset() -> None:
    """offset 為正代表歌詞應提早出現，所以同一個播放位置會落到更後面的行。"""
    body = "[00:00.00]甲\n[00:10.00]乙"
    assert active_line_index(parse_lrc(body), 9.5) == 0
    assert active_line_index(parse_lrc(f"[offset:1000]\n{body}"), 9.5) == 1
    assert active_line_index(parse_lrc(f"[offset:-1000]\n{body}"), 10.5) == 0


def test_active_word_index() -> None:
    line = parse_lrc("[00:10.00]<00:10.00>一<00:10.50>二").lines[0]
    assert active_word_index(line, 9.0) == -1
    assert active_word_index(line, 10.2) == 0
    assert active_word_index(line, 10.6) == 1


def test_empty_input() -> None:
    lyrics = parse_lrc("")
    assert lyrics.is_empty
    assert active_line_index(lyrics, 5.0) == -1
