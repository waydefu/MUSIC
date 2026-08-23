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


def _widen_only(amount: float) -> SpatialUpmix:
    """只開加寬、關掉距離機制。

    ``side/mid`` 比值同時被兩個機制影響：加寬把 side 拉高，距離把 mid 壓低。
    一個指標量兩個軸，測出來的東西就沒有意義 —— 加入距離機制時三條測試
    同時紅燈，成因就是這個。所以驗加寬時把距離關掉，反之亦然。
    """
    upmix = _make(amount)
    upmix.depth_db = 0.0
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
    upmix.depth_db = 0.0  # 距離機制也要關掉才叫「中性」

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
    # 用 side/mid 比值而不是絕對 side 能量：距離機制帶了一個全域補償增益，
    # 絕對量測會被它污染。比值對補償不變。距離本身則另外關掉，見 _widen_only。
    assert _side_over_mid(_run(_widen_only(1.0), signal)[LATENCY * CHANNELS :])         / _side_over_mid(signal) > 1.15


def test_amount_drives_a_real_depth_axis() -> None:
    """**乾濕比必須改變 direct/reverberant 比，那才是「距離」。**

    加這條之前，``centre + front_mid`` 恆等於 ``mid``，於是
    ``dry_mid*(1-a) + wet_mid*a`` 也恆等於 ``mid`` —— 直達聲在任何 amount
    下都一動也沒動。那條數學恆等式就是「有變寬但沒真的拉遠」的成因：
    實測 D/R 從 0 到 100% 只變 −0.62 dB，而人耳判斷距離需要數 dB。

    所以這裡斷言的是 **D/R 隨 amount 單調下降，且全開時足以察覺**。
    只驗「聽起來有變」抓不到「機制根本不存在」。
    """
    signal = _program()
    base_left, base_right = _channels_of(signal)
    base = _rms((base_left + base_right) * 0.5) / _rms((base_left - base_right) * 0.5)

    def depth_db(amount: float) -> float:
        left, right = _channels_of(_run(_make(amount), signal)[LATENCY * CHANNELS :])
        ratio = _rms((left + right) * 0.5) / _rms((left - right) * 0.5)
        return 20.0 * float(np.log10(ratio / base))

    steps = [depth_db(a) for a in (0.25, 0.5, 0.75, 1.0)]
    assert steps == sorted(steps, reverse=True), f"D/R 沒有單調下降：{steps}"
    assert steps[-1] < -3.0, f"全開的 D/R 變化只有 {steps[-1]:.2f} dB，察覺不到"


def test_depth_does_not_hollow_out_the_centre() -> None:
    """壓低直達是為了拉遠，不是為了把人聲挖掉。

    距離機制只壓「置中」的成分，所以它天生就會動到人聲 —— 這條守住
    分寸：人聲要留得住，而且不可以因此跑掉位置。
    """
    signal = _mono_content()
    output = _run(_make(1.0), signal)[LATENCY * CHANNELS :]
    left, right = _channels_of(output)

    assert _correlation(left, right) > 0.95
    assert _rms(output) > _rms(signal[: output.size]) * 0.85


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


def test_hard_panned_source_keeps_its_position() -> None:
    """**硬左偏的樂器不可以漏到右聲道。**

    這條是讀文獻後補的。只用 coherence 分不出「硬左偏的乾樂器」與「真正的
    環境音」—— 兩者的 coherence 都是 0（實測 0.000 對 0.006）。把前者當成
    後者去相關，它就會漏到另一個聲道，定位被抹散。修正前實測有 39.5% 的
    能量跑到原本靜音的右聲道。

    Avendaño 與 Jot 的 upmix 框架同時使用 inter-channel coherence 與
    panning index，兩者缺一不可；章程 §1.3 從 Sennheiser 學到的
    「mix intent preservation」講的是同一件事 —— 混音師把樂器擺在左邊
    是有意圖的，處理器不該把它搬走。
    """
    rng = np.random.default_rng(5)
    source = rng.standard_normal(65536) * 0.35
    signal = _stereo(source, np.zeros_like(source))

    output = _run(_make(1.0), signal)[LATENCY * CHANNELS :]
    left, right = _channels_of(output)

    # 右聲道原本是靜音，處理後洩漏不得超過左聲道的一成。
    assert _rms(right) < _rms(left) * 0.1


def test_bass_image_is_not_smeared_by_decorrelation() -> None:
    """低頻不可以被隨機相位推散。

    去相關器對低頻套隨機相位會讓低音聲像散掉 —— 內部研究文件稱之為
    「low-frequency phase chaos」，並建議在去相關網路後做適度 high-pass。
    實測未加護欄時 <200 Hz 的 side 能量被推高 1.09 倍。

    注意這**不是**單聲道相容性問題：折單聲道拿到的是 mid，而環繞只動
    side，所以 M/S 結構本身就保證了折疊安全。這條守的是立體聲下的
    低音聚焦度。
    """
    t = np.arange(1 << 17, dtype=np.float64) / RATE
    bass = np.sin(2 * np.pi * 80.0 * t) * 0.4
    rng = np.random.default_rng(3)
    signal = _stereo(
        bass + rng.standard_normal(t.size) * 0.05,
        bass * 0.85 + rng.standard_normal(t.size) * 0.05,
    )

    output = _run(_widen_only(1.0), signal)[LATENCY * CHANNELS :]

    def low_side_over_mid(samples: FloatArray) -> float:
        """低頻的 side/mid 比值。同樣要對全域補償增益不變。"""
        left, right = _channels_of(samples)
        freqs = np.fft.rfftfreq(left.size, 1.0 / RATE)
        band = freqs < 200.0
        side = np.abs(np.fft.rfft((left - right) * 0.5)[band]).sum()
        mid = np.abs(np.fft.rfft((left + right) * 0.5)[band]).sum()
        return float(side / max(mid, 1e-12))

    # 跳過開頭一個 hop。串流最前面只有一個視窗參與重疊相加，那段的淡入會
    # 讓比值偏高 —— 實測含暖機 1.049x、跳過後 0.995x，差異全部來自暖機而
    # 不是去相關。這與 test_perfect_reconstruction 用同一個理由。
    warmup = SPATIAL_HOP * CHANNELS
    trimmed = output[warmup:]
    ratio = low_side_over_mid(trimmed) / low_side_over_mid(
        signal[warmup : warmup + trimmed.size]
    )
    assert ratio < 1.03, f"低頻 side 被推高 {ratio:.2f}x"


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


def test_amount_maps_linearly_to_perceived_widening() -> None:
    """乾濕比要**依聽感線性**，不只是單調遞增。

    這條是改強的。原本只斷言 ``off < half < full`` —— 而那個弱斷言讓一個
    真實的缺陷溜了過去：環繞副本是隨機相位、與原始 side 以功率相加，
    側能量是 √(1+g²)。直接讓增益等於 amount 的話，滑桿拉到 50% 只走完
    25.8% 的效果、25% 更只有 5.4%，前半段像壞掉一樣 —— 但它完全滿足
    「單調遞增」。

    **只看方向的斷言抓不到「刻度不成比例」。** 所以這裡量的是進度百分比。
    """
    signal = _program()
    base = _side_over_mid(signal)

    def progress(amount: float) -> float:
        out = _run(_widen_only(amount), signal)[LATENCY * CHANNELS :]
        return _side_over_mid(out) / base

    full = progress(1.0)
    assert full > 1.15  # 全開要有實質效果，否則下面的比例沒有意義

    for amount in (0.25, 0.5, 0.75):
        ratio = (progress(amount) - 1.0) / (full - 1.0)
        assert abs(ratio - amount) < 0.1, f"amount={amount} 只走完 {ratio:.1%}"


def _np_side(signal: FloatArray) -> np.ndarray:
    left, right = _channels_of(signal)
    return (left - right) * 0.5


def _side_over_mid(signal: FloatArray) -> float:
    """side/mid 比值。**對全域增益不變**，所以距離機制的補償不會污染它。

    直接量絕對 side 能量會被補償增益帶著跑 —— 那是加入距離機制時真的
    踩到的坑，三條測試同時紅燈。
    """
    left, right = _channels_of(signal)
    return _rms((left - right) * 0.5) / max(_rms((left + right) * 0.5), 1e-12)


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


# ------------------------------------------------------------------ P2 HRTF renderer


def _binaural(amount: float) -> SpatialUpmix:
    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, CHANNELS, BLOCK)
    upmix.amount = amount
    return upmix


def test_binaural_is_off_by_default() -> None:
    """預設關閉是 §9.9 預算決定的前提：關著時一格濾波器都不算。"""
    assert not SpatialUpmix().binaural


def test_binaural_does_not_change_latency() -> None:
    """HRTF 與 Spatial 共用同一個 STFT，所以延遲必須一模一樣。

    §9.4 的結論是「不能自己再開一組 STFT」。多開一組最先露餡的地方就是
    延遲 —— 這條測試把那個約束變成機器可判定的。
    """
    stereo, binaural = _make(1.0), _binaural(1.0)
    assert binaural.latency_frames == stereo.latency_frames == SPATIAL_FFT_SIZE


def test_binaural_fades_out_with_amount() -> None:
    """滑桿往下拉，HRTF 的染色必須跟著退掉。

    **不能用 ``amount=0`` 驗這件事** —— 那時 ``active`` 是 False，整個
    processor 直接旁通，測試根本進不到 renderer 就綠了。所以這裡用一個
    小但仍然啟用的 amount。

    守的是 binaural renderer 與 stereo renderer 的一個刻意差異：stereo
    是靠 ``width=1`` 天然透明的，可以把 width 直接乘在乾 side 上；但 HRTF
    會改變 side 的頻譜，所以這裡的 side 另外與乾訊號交叉淡入。少了那個
    淡入，滑桿拉到接近 0 仍然聽得到滿量的染色。
    """
    signal = _program()

    def deviation(amount: float) -> float:
        output = _run(_binaural(amount), signal)[LATENCY * CHANNELS :]
        reference = signal[: output.size]
        return _rms(output - reference) / _rms(reference)

    faint, full = deviation(0.05), deviation(1.0)
    assert faint < full * 0.25, f"amount=0.05 還留著 {faint / full:.0%} 的效果"
    assert faint < 0.12, f"amount=0.05 的偏離就有 {faint:.1%}"


def test_binaural_keeps_centred_content_centred() -> None:
    """置中的內容送到兩耳的路徑相同，所以左右必須維持相等。

    這條抓的是「左右接反」與「置中喇叭誤用了近耳響應」——
    兩者都會讓人聲從正中央跑掉，而且用聽的很難察覺是哪一邊。
    """
    output = _run(_binaural(1.0), _mono_content())[LATENCY * CHANNELS :]
    left, right = _channels_of(output)
    assert _correlation(left, right) > 0.999
    assert _rms(left) == pytest.approx(_rms(right), rel=1e-3)


def test_binaural_actually_changes_the_render() -> None:
    """開了 HRTF 就必須聽得出差別，否則濾波器等於沒接上。

    只驗「有變」不夠 —— 浮點雜訊也算有變。所以比的是與 stereo renderer
    的差異能量佔比，要達到可察覺的量級。
    """
    signal = _program()
    stereo = _run(_make(1.0), signal)[LATENCY * CHANNELS :]
    binaural = _run(_binaural(1.0), signal)[LATENCY * CHANNELS :]
    difference = _rms(binaural - stereo) / _rms(stereo)
    assert difference > 0.05, f"HRTF 只改變了 {difference:.1%}，濾波器可能沒生效"


def test_binaural_does_not_blow_up_the_level() -> None:
    """HRTF 的和路徑在某些頻率會相加、某些會抵消。響度補償要照樣接得住。"""
    signal = _program()
    output = _run(_binaural(1.0), signal)[LATENCY * CHANNELS :]
    ratio = _rms(output) / _rms(signal[: output.size])
    assert 0.7 < ratio < 1.4, f"binaural 的響度偏差到 {ratio:.2f}x"


def test_binaural_does_not_collapse_to_mono() -> None:
    """章程 §6.3 點名的四種失敗模式之一，HRTF renderer 一樣要守。"""
    signal = _program()
    output = _run(_binaural(1.0), signal)[LATENCY * CHANNELS :]
    left, right = _channels_of(output)
    assert _correlation(left, right) < 0.99


def _iacc(processor: SpatialUpmix, signal: FloatArray) -> float:
    """耳間相關性（IACC）。真實的雙耳渲染不會讓一般音樂變成反相。"""
    output = _run(processor, signal)[LATENCY * CHANNELS :]
    left, right = _channels_of(output)
    return _correlation(left, right)


def test_binaural_tracks_stereo_at_moderate_amount() -> None:
    """一半以下的設定，HRTF 不該把音場拉到與 stereo renderer 差很遠。

    這是目前**成立**的部分：0.5 以下兩個 renderer 的 IACC 幾乎重疊
    （實測 0.623 vs 0.632）。全開時才會分岔，那部分見下面那條 xfail。
    """
    signal = _program()
    assert _iacc(_binaural(0.5), signal) == pytest.approx(_iacc(_make(0.5), signal), abs=0.1)


def test_binaural_does_not_invert_the_soundstage() -> None:
    """雙耳渲染不得把一般音樂變成反相。

    這條是修出來的，不是一開始就綠的。環繞原本沿用 P1 折回立體聲的 ±u
    （完全反相）餵法：在立體聲下那只是加寬，但反相的一對在 M/S 推導裡
    「和」恆為 0，過了 HRTF 就只剩純反相的 side —— 實測 IACC 掉到 −0.45，
    聽起來是「在頭裡面」，正好是頭外化的反面。改成餵兩條互不相關的訊號
    之後回到 +0.00。

    門檻設在 −0.05 而不是 0：要守的物理性質是「不得反相」，不是「必須正到
    某個數字」。全開時本來就該是很寬的音場。
    """
    assert _iacc(_binaural(1.0), _program()) > -0.05


def test_binaural_stays_clearly_positive_below_full() -> None:
    """日常會用到的設定要維持明確的正相關。"""
    assert _iacc(_binaural(0.75), _program()) > 0.15


def test_binaural_puts_diffuse_content_near_zero() -> None:
    """擴散場的 IACC 本來就該接近 0，不是負的。

    這裡 binaural **比 P1 的 stereo fold 更接近物理**（實測 −0.07 vs −0.44）
    —— 因為 stereo fold 只有 ±u 這一條路可走。斷言比的是「誰比較接近 0」，
    這樣如果有人把環繞改回反相餵法，這條會紅。
    """
    signal = _diffuse_content()
    assert abs(_iacc(_binaural(1.0), signal)) < abs(_iacc(_make(1.0), signal))
