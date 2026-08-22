"""Spatial P1 的測試。

章程 §6.3 點名四種失敗模式要有確定性測試：
**人聲跑到後面、低頻相位抵消、瞬態塗抹、單聲道塌陷**。
這個檔案就是照那份清單寫的 —— 空間音效最容易「聽起來很酷但其實壞了」，
而這四種壞法都可以用合成訊號抓出來，不必靠耳朵。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from aurora.core.abcompare import compare, estimate_latency_frames
from aurora.core.constants import SPATIAL_FFT_SIZE, SPATIAL_HOP
from aurora.core.dsp_graph import DspGraph
from aurora.core.spatial import SpatialUpmix

FloatArray = npt.NDArray[np.float32]

RATE = 48000
CHANNELS = 2
BLOCK = 2880
#: 延遲是一整個視窗，不是 fft − hop。理由見 SpatialUpmix.latency_frames。
LATENCY = SPATIAL_FFT_SIZE


def _stereo(left: np.ndarray, right: np.ndarray) -> FloatArray:
    return np.stack([left, right], axis=1).astype(np.float32).reshape(-1)


def _mono_content(frames: int = 65536, amplitude: float = 0.3) -> FloatArray:
    """完全置中的內容 —— 模擬人聲／貝斯。左右完全相同。"""
    rng = np.random.default_rng(11)
    mono = rng.standard_normal(frames) * amplitude
    return _stereo(mono, mono)


def _diffuse_content(frames: int = 65536, amplitude: float = 0.3) -> FloatArray:
    """完全不相關的內容 —— 模擬殘響／環境音。"""
    rng = np.random.default_rng(12)
    return _stereo(
        rng.standard_normal(frames) * amplitude,
        rng.standard_normal(frames) * amplitude,
    )


def _program(frames: int = 65536) -> FloatArray:
    """置中人聲 + 不相關殘響，接近真實混音。"""
    rng = np.random.default_rng(13)
    centre = rng.standard_normal(frames) * 0.25
    return _stereo(
        centre + rng.standard_normal(frames) * 0.12,
        centre + rng.standard_normal(frames) * 0.12,
    )


def _make(amount: float) -> SpatialUpmix:
    upmix = SpatialUpmix()
    upmix.prepare(RATE, CHANNELS, BLOCK)
    upmix.amount = amount
    return upmix


def _run(processor: SpatialUpmix, signal: FloatArray, block: int = BLOCK) -> FloatArray:
    out = signal.copy()
    step = block * CHANNELS
    for start in range(0, out.size, step):
        processor.process(out[start : start + step])
    return out


def _channels_of(signal: FloatArray) -> tuple[np.ndarray, np.ndarray]:
    view = signal.reshape(-1, CHANNELS)
    return view[:, 0], view[:, 1]


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    x, y = a - a.mean(), b - b.mean()
    denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
    return 0.0 if denominator == 0.0 else float(np.dot(x, y) / denominator)


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


# ------------------------------------------------------------------ 透明度


def test_amount_zero_is_completely_transparent() -> None:
    """沒開就要完全不動訊號，也不該宣稱有延遲。

    使用者沒開空間音效卻要付 21 ms 延遲是不能接受的。
    """
    upmix = _make(0.0)
    assert upmix.latency_frames == 0
    signal = _program(8192)
    assert np.array_equal(_run(upmix, signal), signal)


def test_perfect_reconstruction_when_the_renderer_is_neutral() -> None:
    """把環繞關掉、寬度設 1 時，整條鏈必須**逐位元**還原出原訊號。

    這條是所有其他測試的地基：如果 STFT 分析／合成本身就不準，
    後面量到的任何「差異」都分不清是演算法還是重建誤差。

    跳過開頭一個 hop：串流最前面那段只有一個視窗參與重疊相加（第二個還沒
    進來），所以會有一段淡入。這是 STFT 的固有起步現象，不是缺陷 ——
    實測誤差在第 512 框之後**恰好是 0.0**，所以這裡用零容差斷言。
    """
    upmix = _make(1.0)
    upmix.surround_level = 0.0
    upmix.width = 1.0

    signal = _program(32768)
    output = _run(upmix, signal)

    delay = LATENCY * CHANNELS
    warmup = SPATIAL_HOP * CHANNELS
    reconstructed = output[delay + warmup :]
    expected = signal[warmup : warmup + reconstructed.size]
    assert np.array_equal(reconstructed, expected)


def test_declared_latency_matches_measured() -> None:
    upmix = _make(1.0)
    signal = _program(131072)
    output = _run(upmix, signal)
    assert estimate_latency_frames(signal, output, CHANNELS) == upmix.latency_frames
    assert upmix.latency_frames == LATENCY


# ------------------------------------------------------------------ 章程 §6.3 的四種失敗


def test_centred_content_stays_centred() -> None:
    """**人聲不可以跑掉。** 這是最容易被聽出來的失敗。

    完全置中的內容相關性 ≈ 1，應該幾乎原封不動地留在中間。
    """
    upmix = _make(1.0)
    signal = _mono_content()
    output = _run(upmix, signal)

    left, right = _channels_of(output[LATENCY * CHANNELS :])
    assert _correlation(left, right) > 0.95


def test_diffuse_content_gets_wider() -> None:
    """不相關的內容才該被拿去做環繞 —— 否則這個處理器什麼也沒做。"""
    upmix = _make(1.0)
    signal = _diffuse_content()

    before_l, before_r = _channels_of(signal)
    after_l, after_r = _channels_of(_run(upmix, signal)[LATENCY * CHANNELS :])

    assert _correlation(after_l, after_r) < _correlation(before_l, before_r) + 0.05
    # side 能量應該變多，那就是「變寬」的定義。
    before_side = _rms((before_l - before_r) * 0.5)
    after_side = _rms((after_l - after_r) * 0.5)
    assert after_side > before_side


def test_realistic_material_is_meaningfully_widened() -> None:
    """**真實混音**（置中人聲 + 不相關殘響）要有可聽的展開。

    這條是補測試盲點補出來的。原本只有 :func:`test_diffuse_content_gets_wider`，
    用的是完全不相關的素材 —— 那種情況剛好繞過了問題，所以它一路是綠的，
    而真實音樂上效果幾乎是零。

    當時環繞路徑被乘了兩次閘門（``side × (1 − centre_weight)``），而 side
    本身就已經是不相關的成分。真實素材大多相關，閘門中位數只有 0.19，
    再加上隨機相位是以功率相加，最後只換到 0.7% 的側能量。

    所以這裡斷言的是**倍率**而不是「有變大」—— 只看方向的斷言抓不到
    「效果小到聽不出來」這種失敗。
    """
    signal = _program()
    before_l, before_r = _channels_of(signal)
    after_l, after_r = _channels_of(_run(_make(1.0), signal)[LATENCY * CHANNELS :])

    before_side = _rms((before_l - before_r) * 0.5)
    after_side = _rms((after_l - after_r) * 0.5)
    assert after_side / before_side > 1.15


def test_bass_survives_mono_collapse() -> None:
    """**低頻不可以相位抵消。**

    很多播放環境（藍牙喇叭、手機）會把訊號折成單聲道。如果 upmix 在低頻
    製造出反相成分，折疊之後低音就消失了 —— 這是實務上最嚴重的災難，
    因為它只在別人的裝置上發生。
    """
    t = np.arange(65536, dtype=np.float64) / RATE
    bass = np.sin(2 * np.pi * 80.0 * t) * 0.4
    signal = _stereo(bass, bass)

    upmix = _make(1.0)
    output = _run(upmix, signal)[LATENCY * CHANNELS :]

    left, right = _channels_of(output)
    folded = (left + right) * 0.5
    reference = bass[: folded.size]

    # 折成單聲道後的低頻能量不得低於原本的八成。
    assert _rms(folded) > _rms(reference) * 0.8


def test_mono_input_does_not_collapse_to_silence() -> None:
    """單聲道輸入（S 恆為 0）不可以變成無聲。

    這是 upmix 最經典的實作錯誤：整條路徑都建在 side 上，
    遇到 side=0 的素材就整個消失。
    """
    signal = _mono_content()
    upmix = _make(1.0)
    output = _run(upmix, signal)[LATENCY * CHANNELS :]
    assert _rms(output) > _rms(signal) * 0.7


def test_transients_are_not_smeared_badly() -> None:
    """**瞬態不可以被塗抹。** STFT 天生會把能量往時間軸兩側擴散。

    這裡不要求完全沒有擴散（那不可能），只要求脈衝的能量仍然集中在
    原本的位置附近。
    """
    frames = 65536
    impulse = np.zeros(frames)
    impulse[frames // 2] = 1.0
    signal = _stereo(impulse, impulse)

    upmix = _make(1.0)
    output = _run(upmix, signal)[LATENCY * CHANNELS :]
    left, _ = _channels_of(output)

    peak = int(np.argmax(np.abs(left)))
    near = np.abs(left[max(0, peak - 256) : peak + 256])
    total = np.abs(left)
    assert near.sum() > total.sum() * 0.8


# ------------------------------------------------------------------ 音量與 A/B


def test_level_stays_close_when_engaged() -> None:
    """開啟後音量不該明顯改變，否則 A/B 會被響度差主導。"""
    signal = _program()
    upmix = _make(1.0)
    output = _run(upmix, signal)

    result = compare(signal, output, latency_frames=LATENCY, channels=CHANNELS)
    assert abs(result.applied_gain_db) < 1.5


def test_amount_scales_the_effect_monotonically() -> None:
    """乾濕比要單調 —— 中間值的效果應該落在關與全開之間。"""
    signal = _diffuse_content()

    def side_energy(amount: float) -> float:
        left, right = _channels_of(_run(_make(amount), signal)[LATENCY * CHANNELS :])
        return _rms((left - right) * 0.5)

    off, half, full = side_energy(0.0), side_energy(0.5), side_energy(1.0)
    assert off < half < full


# ------------------------------------------------------------------ 生命週期與整合


def test_reset_clears_the_overlap_state() -> None:
    upmix = _make(1.0)
    _run(upmix, _program(BLOCK * 4))
    upmix.reset()
    silence = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    assert np.abs(_run(upmix, silence)).max() == 0.0


def test_rejects_unsupported_overlap() -> None:
    with pytest.raises(ValueError, match="50%"):
        SpatialUpmix(fft_size=2048, hop=512)


def test_non_stereo_is_left_alone() -> None:
    """單聲道沒有左右差可以分析，多聲道不在 P1 範圍。都不處理。"""
    upmix = SpatialUpmix()
    upmix.prepare(RATE, 1, BLOCK)
    upmix.amount = 1.0
    assert not upmix.active
    assert upmix.latency_frames == 0


def test_block_size_does_not_change_the_result() -> None:
    """回呼大小是裝置決定的，換一個緩衝設定不該改變聲音。"""
    signal = _program(32768)
    big = _run(_make(1.0), signal, block=BLOCK)
    small = _run(_make(1.0), signal, block=512)
    assert np.allclose(big, small, atol=2e-4)


def test_graph_sums_spatial_latency() -> None:
    upmix = _make(1.0)
    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, BLOCK)
    graph.set_stages((upmix,))
    assert graph.latency_frames == LATENCY
