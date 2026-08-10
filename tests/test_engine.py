"""播放引擎測試。

全部用 :meth:`AudioEngine.pump` 手動推進，不開音訊裝置 ——
所以測試不會發出聲音，也能在沒有音效卡的機器上跑。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from aurora.audio.analyzer import Analyzer, RingBuffer
from aurora.audio.engine import AudioEngine, decode_all

RATE = 44100


# ------------------------------------------------------------------ 非 ASCII 路徑


def test_decodes_from_non_ascii_path(tmp_path: Path, flac_path: Path) -> None:
    """回歸測試：miniaudio 的 decode_file 在中文路徑上會回 MA_DOES_NOT_EXIST(-7)，
    所以引擎一律走 stream_file。這條測試就是守住這件事的。

    專案目錄本身叫「音樂撥放器」，中文使用者的音樂庫更是必然如此 ——
    這不是邊角情況，是日常。
    """
    chinese_dir = tmp_path / "音樂 資料夾 テスト"
    chinese_dir.mkdir()
    target = chinese_dir / "歌曲 名稱.flac"
    shutil.copy2(flac_path, target)

    samples = decode_all(str(target), RATE)
    assert samples.size > 0
    assert float(np.abs(samples).max()) > 0.01

    engine = AudioEngine(RATE)
    try:
        assert engine.load(str(target))
        assert engine.pump() > 0
    finally:
        engine.close()


def test_missing_file_fails_gracefully() -> None:
    engine = AudioEngine(RATE)
    try:
        assert not engine.load(r"D:\這個檔案不存在\nope.flac")
        assert engine.pump() == 0
    finally:
        engine.close()


# ------------------------------------------------------------------ 解碼


@pytest.mark.parametrize(
    "name", ["test.wav", "test.flac", "test_320k.mp3", "test_128k.mp3", "test.ogg"]
)
def test_all_supported_formats_decode(generated_dir: Path, name: str) -> None:
    samples = decode_all(str(generated_dir / name), RATE)
    # 12 秒 × 44100 × 2 聲道，容許編碼器在頭尾補靜音
    assert samples.size == pytest.approx(12 * RATE * 2, rel=0.05)


# ------------------------------------------------------------------ 播放位置


def test_position_advances_with_pumped_frames(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        assert engine.load(str(flac_path))
        assert engine.position == 0.0

        total = sum(engine.pump(1024) for _ in range(40))
        assert total > 0
        assert engine.position == pytest.approx(total / RATE, abs=1e-6)
    finally:
        engine.close()


def test_duration_comes_from_the_file(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        assert engine.duration == pytest.approx(12.0, abs=0.1)
    finally:
        engine.close()


def test_duration_hint_wins_over_probing(flac_path: Path) -> None:
    """音樂庫用 mutagen 讀標籤就知道時長，不必讓 miniaudio 再探一次。"""
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path), duration_sec=999.0)
        assert engine.duration == 999.0
    finally:
        engine.close()


# ------------------------------------------------------------------ 跳轉


def test_seek_moves_position(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        assert engine.seek(6.0)
        assert engine.position == pytest.approx(6.0, abs=0.01)
    finally:
        engine.close()


def test_seek_then_pump_continues_from_there(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        engine.seek(5.0)
        engine.pump(4410)
        assert engine.position == pytest.approx(5.1, abs=0.02)
    finally:
        engine.close()


def test_seek_is_clamped_to_the_track(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        engine.seek(-30.0)
        assert engine.position == 0.0
        engine.seek(9999.0)
        assert engine.position == pytest.approx(engine.duration, abs=0.01)
    finally:
        engine.close()


def test_seek_produces_different_audio_than_start(flac_path: Path) -> None:
    """真的有跳過去，不是只改了計數器。"""

    def sample_at(seconds: float) -> np.ndarray:
        engine = AudioEngine(RATE)
        try:
            engine.load(str(flac_path))
            engine.seek(seconds)
            for _ in range(10):
                engine.pump(1024)
            return engine.analyzer._ring.latest(2048).copy()
        finally:
            engine.close()

    assert not np.allclose(sample_at(0.0), sample_at(6.0))


# ------------------------------------------------------------------ 播畢


def test_finished_flag_is_raised_at_end_of_stream(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        for _ in range(2000):
            if engine.pump(8192) == 0:
                break
        assert engine.take_finished()
        # 旗標是一次性的，讀過就清掉，避免重複觸發換歌
        assert not engine.take_finished()
    finally:
        engine.close()


def test_seek_clears_a_pending_finished_flag(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        for _ in range(2000):
            if engine.pump(8192) == 0:
                break
        engine.seek(1.0)
        assert not engine.take_finished()
    finally:
        engine.close()


# ------------------------------------------------------------------ 音量


def test_volume_is_clamped() -> None:
    engine = AudioEngine(RATE)
    try:
        engine.volume = 5.0
        assert engine.volume == 1.0
        engine.volume = -1.0
        assert engine.volume == 0.0
    finally:
        engine.close()


def test_analyzer_sees_signal_even_when_muted(flac_path: Path) -> None:
    """音質量測看的是檔案本身，不該被音量旋鈕影響。"""
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        engine.muted = True
        for _ in range(20):
            engine.pump(2048)
        assert float(np.abs(engine.analyzer._ring.latest(2048)).max()) > 0.01
    finally:
        engine.close()


def test_output_format_reports_float32() -> None:
    engine = AudioEngine(48000)
    try:
        fmt = engine.output_format
        assert fmt.sample_rate == 48000
        assert fmt.is_float
    finally:
        engine.close()


# ------------------------------------------------------------------ 環形緩衝


def test_ring_buffer_returns_latest_samples_in_order() -> None:
    ring = RingBuffer(8)
    ring.write(np.arange(5, dtype=np.float32))
    assert ring.latest(3).tolist() == [2.0, 3.0, 4.0]


def test_ring_buffer_pads_when_underfilled() -> None:
    ring = RingBuffer(8)
    ring.write(np.array([1.0, 2.0], dtype=np.float32))
    assert ring.latest(4).tolist() == [0.0, 0.0, 1.0, 2.0]


def test_ring_buffer_wraps_correctly() -> None:
    ring = RingBuffer(4)
    ring.write(np.arange(6, dtype=np.float32))
    assert ring.latest(4).tolist() == [2.0, 3.0, 4.0, 5.0]


def test_ring_buffer_discards_oversized_write() -> None:
    """單次寫入超過容量時只保留最後一圈，不該爆掉。"""
    ring = RingBuffer(4)
    ring.write(np.arange(100, dtype=np.float32))
    assert ring.latest(4).tolist() == [96.0, 97.0, 98.0, 99.0]


def test_ring_buffer_read_since_tracks_cursor() -> None:
    ring = RingBuffer(16)
    fresh, cursor = ring.read_since(0)
    assert fresh.size == 0

    ring.write(np.arange(5, dtype=np.float32))
    fresh, cursor = ring.read_since(cursor)
    assert fresh.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]

    fresh, cursor = ring.read_since(cursor)
    assert fresh.size == 0


# ------------------------------------------------------------------ 分析器


def test_analyzer_produces_a_frame(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        for _ in range(30):
            engine.pump(2048)
            frame = engine.analyzer.tick(1 / 60)
        assert len(frame.bars) == 64
        assert max(frame.bars) > 0.0
        assert 0.0 <= frame.rms <= 1.0
    finally:
        engine.close()


def test_analyzer_measures_rolloff_on_real_audio(flac_path: Path) -> None:
    """真無損檔的頻譜應該一路延伸到 Nyquist 附近。"""
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        for _ in range(400):
            if engine.pump(4096) == 0:
                break
            engine.analyzer.tick(1 / 60)
        result = engine.analyzer.rolloff(lossless_container=True, source_sample_rate=RATE)
        assert result.enough_data
        assert result.cutoff_hz is not None and result.cutoff_hz > 20500
        assert not result.suspected_transcode
    finally:
        engine.close()


def test_analyzer_flags_fake_lossless(fake_lossless_path: Path) -> None:
    """副檔名是 FLAC，內容其實是 128 kbps MP3 —— 這是整個音質面板的招牌功能。"""
    engine = AudioEngine(RATE)
    try:
        engine.load(str(fake_lossless_path))
        for _ in range(400):
            if engine.pump(4096) == 0:
                break
            engine.analyzer.tick(1 / 60)
        result = engine.analyzer.rolloff(lossless_container=True, source_sample_rate=RATE)
        assert result.enough_data
        assert result.suspected_transcode
        assert result.cutoff_hz is not None and result.cutoff_hz < 18000
    finally:
        engine.close()


def test_analyzer_detects_onsets_in_real_audio(flac_path: Path) -> None:
    """測試素材每 0.5 秒放一個鼓點，12 秒共 23 個。"""
    analyzer = Analyzer(RATE)
    samples = decode_all(str(flac_path), RATE)
    hits = 0
    step = 4096
    for start in range(0, samples.size, step):
        analyzer.push_interleaved(samples[start : start + step])
        if analyzer.tick(1 / 60).onset:
            hits += 1
    assert hits >= 15


def test_reset_track_clears_quality_stats(flac_path: Path) -> None:
    engine = AudioEngine(RATE)
    try:
        engine.load(str(flac_path))
        for _ in range(200):
            engine.pump(4096)
            engine.analyzer.tick(1 / 60)
        assert engine.analyzer.analysed_frames > 0

        engine.analyzer.reset_track()
        assert engine.analyzer.analysed_frames == 0
        assert not engine.analyzer.rolloff(lossless_container=True).enough_data
    finally:
        engine.close()


def test_reconfigure_rebuilds_for_new_rate() -> None:
    analyzer = Analyzer(44100)
    analyzer.reconfigure(48000, 2)
    assert analyzer.sample_rate == 48000
    assert analyzer.analysed_frames == 0


# ------------------------------------------------------------------ 真實音訊裝置
#
# 這些會實際開啟音效卡，但音量固定為 0，所以不會發出聲音。
# 目的是驗證裝置建立、start/stop、以及回呼執行緒真的有在跑。


@pytest.mark.audio
def test_real_device_plays_and_advances(flac_path: Path) -> None:
    import time

    engine = AudioEngine(48000)
    try:
        engine.volume = 0.0
        assert engine.load(str(flac_path))
        if not engine.play():
            pytest.skip("這台機器沒有可用的輸出裝置")

        assert engine.is_playing
        time.sleep(0.6)
        engine.pause()

        assert not engine.is_playing
        assert engine.position > 0.1, "音訊回呼執行緒沒有推進播放位置"
    finally:
        engine.close()


@pytest.mark.audio
def test_pause_then_resume_continues_from_same_place(flac_path: Path) -> None:
    """暫停只是停掉裝置，產生器還活著，續播應該接續而不是從頭。"""
    import time

    engine = AudioEngine(48000)
    try:
        engine.volume = 0.0
        engine.load(str(flac_path))
        if not engine.play():
            pytest.skip("這台機器沒有可用的輸出裝置")

        time.sleep(0.4)
        engine.pause()
        paused_at = engine.position

        assert engine.play()
        time.sleep(0.4)
        engine.pause()

        assert engine.position > paused_at
    finally:
        engine.close()


@pytest.mark.audio
def test_configure_output_switches_rate_midstream(flac_path: Path) -> None:
    engine = AudioEngine(44100)
    try:
        engine.volume = 0.0
        engine.load(str(flac_path))
        engine.seek(3.0)

        assert engine.configure_output(48000)
        assert engine.sample_rate == 48000
        assert engine.analyzer.sample_rate == 48000
        # 換取樣率後應該從原本的位置附近接續，不是跳回開頭
        assert engine.position == pytest.approx(3.0, abs=0.2)
    finally:
        engine.close()
