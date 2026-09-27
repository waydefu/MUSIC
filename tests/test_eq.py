"""等化器、限幅器、輸出電表的測試。

這三個是一包（``PROJECT_PLAN.md`` §5），所以放同一個檔案 —— 它們真正要
守的是**整條增益鏈不會削波**，而那條斷言必須跨越三者才寫得出來。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from aurora.core.abcompare import estimate_latency_frames
from aurora.core.constants import EQ_BAND_HZ, EQ_GAIN_LIMIT_DB, LIMITER_CEILING
from aurora.core.dsp_graph import DspGraph
from aurora.core.dynamics import Limiter, OutputMeter
from aurora.core.eq import GraphicEqualizer, band_label, design_kernel

FloatArray = npt.NDArray[np.float32]

RATE = 48000
CHANNELS = 2
BANDS = len(EQ_BAND_HZ)
BLOCK = 2880


def _flat() -> list[float]:
    return [0.0] * BANDS


def _tone(freq: float, frames: int = 32768, amplitude: float = 0.25) -> FloatArray:
    t = np.arange(frames, dtype=np.float64) / RATE
    mono = np.sin(2 * np.pi * freq * t) * amplitude
    return np.stack([mono, mono], axis=1).astype(np.float32).reshape(-1)


def _program(frames: int = 32768, amplitude: float = 0.3) -> FloatArray:
    rng = np.random.default_rng(99)
    mono = rng.standard_normal(frames) * amplitude
    right = np.roll(mono, 16) * 0.9
    return np.stack([mono, right], axis=1).astype(np.float32).reshape(-1)


def _run(processor: object, signal: FloatArray, block: int = BLOCK) -> FloatArray:
    """分塊餵過處理器，模擬回呼。"""
    out = signal.copy()
    step = block * CHANNELS
    for start in range(0, out.size, step):
        processor.process(out[start : start + step])  # type: ignore[attr-defined]
    return out


def _rms(samples: FloatArray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def _band_energy(signal: FloatArray, freq: float) -> float:
    """單一頻率附近的能量。用來驗證某一段真的被拉高或壓低。"""
    mono = signal.reshape(-1, CHANNELS).mean(axis=1)
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / RATE)
    window = (freqs > freq * 0.8) & (freqs < freq * 1.25)
    return float(spectrum[window].sum())


# ------------------------------------------------------------------ 核心設計


def test_flat_gains_give_a_transparent_kernel() -> None:
    """全平時核心應該接近單位脈衝 —— 過了等於沒過。"""
    kernel = design_kernel(_flat(), RATE)
    peak = int(np.argmax(np.abs(kernel)))
    assert peak == kernel.size // 2  # 對稱中心
    assert abs(kernel[peak] - 1.0) < 0.05
    assert np.abs(np.delete(kernel, peak)).max() < 0.05


def test_kernel_requires_odd_taps() -> None:
    """偶數抽頭的群延遲是半框，線性相位就不成立了。"""
    with pytest.raises(ValueError, match="奇數"):
        design_kernel(_flat(), RATE, taps=1024)


def test_kernel_rejects_wrong_band_count() -> None:
    with pytest.raises(ValueError, match="段增益"):
        design_kernel([0.0, 0.0], RATE)


def test_auto_headroom_keeps_the_curve_at_or_below_unity() -> None:
    """任何正增益都要靠 preamp 壓回來，否則 EQ 本身就會削波。

    這是章程風險 R6 的核心防線：不是「之後用限幅器救」，
    而是先讓它不可能超過。
    """
    gains = _flat()
    gains[4] = EQ_GAIN_LIMIT_DB
    kernel = design_kernel(gains, RATE)
    response = np.abs(np.fft.rfft(kernel, 8192))
    assert response.max() <= 1.02  # 只留窗函數造成的極小漣波


def _response_db(kernel: np.ndarray, rate: int, hz: float) -> float:
    spectrum = np.fft.rfft(kernel, 1 << 18)
    freqs = np.fft.rfftfreq(1 << 18, 1.0 / rate)
    return float(20.0 * np.log10(np.abs(spectrum[np.argmin(np.abs(freqs - hz))])))


@pytest.mark.parametrize("rate", [48000, 96000, 192000])
@pytest.mark.parametrize("band", [0, 1, 2])
def test_low_bands_reach_their_setting_at_any_rate(rate: int, band: int) -> None:
    """拉到 +12 dB 的低頻段，實際就要是 +12 dB（相對於不動的 1 kHz）。

    修正前 48k 下 31／62／125 Hz 只得到 +7.9／+5.4／+8.2 dB：設計格點與核心
    一樣長（0、47、94 Hz…），62 Hz 根本不在格點上，加窗又把剩下的起伏抹掉
    一截。而抽頭數固定成樣本數，192k 下 62 Hz 那段 +12 dB 只剩 +0.0 dB。
    """
    gains = _flat()
    gains[band] = EQ_GAIN_LIMIT_DB
    kernel = design_kernel(gains, rate)
    boost = _response_db(kernel, rate, EQ_BAND_HZ[band]) - _response_db(kernel, rate, 1000.0)
    assert boost == pytest.approx(EQ_GAIN_LIMIT_DB, abs=1.0)


@pytest.mark.parametrize(
    "curve",
    [[9, 6, 3, 0, 0, 0, 0, 0, 0, 0], [6, 4, 2, 0, -2, -2, 0, 2, 4, 6], [4, 6, 4, 0, -1, 0, 2, 4, 4, 2]],
    ids=["bass-shelf", "v-shape", "loudness"],
)
def test_everyday_curves_land_on_every_band_centre(curve: list[float]) -> None:
    """實務上的曲線每個頻段中心都要到位，不只是被拉最多的那一段。

    修正前低音棚架差 1.3 dB、V 形差 0.9 dB，而且誤差全集中在最低的幾段。

    形狀與 preamp 分開斷言：低頻棚架從 DC 一路平到 31 Hz 再往下掉，在這個
    解析度下平滑的曲線頂端一定略高於 31 Hz 的值，保證「處處 ≤ 0 dB」的正規化
    因此會多壓一點點。那只會讓整體略小聲，不會改變形狀，也不會削波。
    """
    kernel = design_kernel(curve, RATE)
    desired = np.asarray(curve, dtype=np.float64) - max(0.0, max(curve))
    realized = np.array([_response_db(kernel, RATE, hz) for hz in EQ_BAND_HZ])
    offset = float(np.median(realized - desired))
    assert np.abs(realized - desired - offset).max() < 0.3
    assert -1.5 < offset <= 0.05


@pytest.mark.parametrize("rate", [44100, 96000, 192000])
def test_latency_in_milliseconds_does_not_depend_on_the_rate(rate: int) -> None:
    """抽頭數跟著取樣率換算，延遲的**秒數**因此不變（約 10.6 ms）。"""
    eq = GraphicEqualizer()
    eq.prepare(rate, CHANNELS, rate * 60 // 1000)
    gains = _flat()
    gains[5] = 6.0
    eq.set_gains(gains)
    assert eq.latency_frames / rate == pytest.approx(511 / 48000, rel=0.01)


def test_turning_back_on_does_not_replay_old_audio() -> None:
    """全平時 EQ 不運算，尾巴停在上次開著時的狀態 —— 重新打開要先清掉。"""
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    gains = _flat()
    gains[5] = 12.0
    eq.set_gains(gains)
    _run(eq, _program(BLOCK))

    eq.set_gains(_flat())
    eq.set_gains(gains)
    silence = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    assert np.abs(_run(eq, silence)).max() == 0.0


# ------------------------------------------------------------------ 等化器行為


def test_flat_equalizer_is_disabled_and_free() -> None:
    """全平時不做任何運算，也不宣稱有延遲。

    使用者沒動 EQ 卻要付 10 ms 延遲是不能接受的。
    """
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    eq.set_gains(_flat())

    assert eq.is_flat
    assert eq.latency_frames == 0

    signal = _program()
    assert np.array_equal(_run(eq, signal), signal)


def test_boosting_a_band_raises_it_relative_to_the_others() -> None:
    """自動餘裕讓「提升」的意義是**相對的**，這一點值得寫成測試記下來。

    拉高 1 kHz 九分貝的同時，preamp 會把整條曲線壓低九分貝，所以 1 kHz 的
    **絕對**能量幾乎不變 —— 變的是它與其他頻段的比例。

    這正是播放器要的行為：調 EQ 不會突然變大聲，也不可能削波。
    代價是使用者把單一頻段拉到底時，聽到的是「其他頻段變小」而不是
    「這一段變大」。這是刻意的取捨，不是缺陷。
    """
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    gains = _flat()
    gains[5] = 9.0  # 1 kHz
    eq.set_gains(gains)

    signal = _program()
    processed = _run(eq, signal)

    # 拿距離夠遠的頻段當基準，避免被內插的裙邊影響。
    before = _band_energy(signal, 1000.0) / _band_energy(signal, 8000.0)
    after = _band_energy(processed, 1000.0) / _band_energy(processed, 8000.0)
    assert after > before * 1.5

    # 絕對值則不該變大 —— 這就是自動餘裕在做的事。
    assert _band_energy(processed, 1000.0) <= _band_energy(signal, 1000.0) * 1.05


def test_cutting_a_band_lowers_that_band_much_more_than_its_neighbours() -> None:
    """壓低某一段時，相鄰段落只能被輕微影響，否則等於是在動整條曲線。"""
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    gains = _flat()
    gains[7] = -EQ_GAIN_LIMIT_DB  # 4 kHz
    eq.set_gains(gains)

    signal = _program()
    processed = _run(eq, signal)

    target_ratio = _band_energy(processed, 4000.0) / _band_energy(signal, 4000.0)
    far_ratio = _band_energy(processed, 250.0) / _band_energy(signal, 250.0)
    assert target_ratio < 0.5
    assert far_ratio > target_ratio * 2


def test_gains_are_clamped_to_the_charter_limit() -> None:
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    eq.set_gains([99.0] * BANDS)
    assert all(value == EQ_GAIN_LIMIT_DB for value in eq.gains_db)


def test_headroom_reports_the_applied_preamp() -> None:
    eq = GraphicEqualizer()
    gains = _flat()
    gains[2] = 6.0
    eq.set_gains(gains)
    assert eq.headroom_db == pytest.approx(-6.0)


def test_declared_latency_matches_measured_latency() -> None:
    """A1 的實測對上 EQ 的申報值。

    申報錯了不會有症狀，直到歌詞開始對不上 —— 這條把它變成會紅的測試。
    """
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    gains = _flat()
    gains[5] = 6.0
    eq.set_gains(gains)

    signal = _program(65536)
    processed = _run(eq, signal)
    assert estimate_latency_frames(signal, processed, CHANNELS) == eq.latency_frames


def test_blocks_larger_than_prepared_are_handled_not_reallocated() -> None:
    """離線推進可以送任意大小。分批處理，不可以在回呼裡重配置。"""
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, 512)
    gains = _flat()
    gains[3] = 6.0
    eq.set_gains(gains)

    signal = _program(8192)
    chunked = _run(eq, signal, block=512)
    eq.reset()
    single = _run(eq, signal, block=8192)
    assert np.allclose(chunked, single, atol=1e-5)


def test_reset_clears_the_overlap_tail() -> None:
    """不清尾巴的話，seek 之後會聽到上一段的殘響。"""
    eq = GraphicEqualizer()
    eq.prepare(RATE, CHANNELS, BLOCK)
    gains = _flat()
    gains[5] = 12.0
    eq.set_gains(gains)

    loud = _program(BLOCK)
    _run(eq, loud)
    eq.reset()

    silence = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    assert np.abs(_run(eq, silence)).max() == 0.0


def test_band_labels_are_readable() -> None:
    assert band_label(0) == "31"
    assert band_label(BANDS - 1) == "16k"


# ------------------------------------------------------------------ 限幅器


def test_limiter_never_exceeds_its_ceiling() -> None:
    limiter = Limiter()
    limiter.prepare(RATE, CHANNELS, BLOCK)

    hot = _program(32768, amplitude=1.5)
    output = _run(limiter, hot)
    assert np.abs(output).max() <= LIMITER_CEILING + 1e-4


def test_limiter_is_transparent_below_the_ceiling() -> None:
    """安靜的訊號只該被延遲，不該被改變振幅。

    限幅器是保險不是響度工具 —— 平常它必須完全不作用。
    """
    limiter = Limiter()
    limiter.prepare(RATE, CHANNELS, BLOCK)

    quiet = _program(16384, amplitude=0.1)
    output = _run(limiter, quiet)

    delay = limiter.latency_frames * CHANNELS
    assert np.allclose(output[delay:], quiet[: output.size - delay], atol=1e-6)
    assert limiter.engaged_frames == 0


def test_limiter_catches_a_peak_before_it_arrives() -> None:
    """前瞻的意義：增益要在峰值抵達**之前**就降下來，不是之後才補救。"""
    limiter = Limiter()
    limiter.prepare(RATE, CHANNELS, BLOCK)

    signal = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    spike_frame = 1000
    signal[spike_frame * CHANNELS : spike_frame * CHANNELS + CHANNELS] = 4.0

    output = _run(limiter, signal)
    assert np.abs(output).max() <= LIMITER_CEILING + 1e-4
    assert limiter.engaged_frames > 0


def _limiter_gain(block: int) -> np.ndarray:
    """60 Hz 的大正弦加一個尖峰，回傳限幅器實際施加的逐樣本增益。"""
    limiter = Limiter()
    limiter.prepare(RATE, CHANNELS, BLOCK)
    t = np.arange(8192) / RATE
    mono = 0.9 * np.sin(2 * np.pi * 60.0 * t)
    mono[3000] = 1.2
    signal = np.stack([mono, mono], axis=1).astype(np.float32).reshape(-1)
    output = _run(limiter, signal, block=block).reshape(-1, CHANNELS)[:, 0]
    delayed = np.concatenate([np.zeros(limiter.latency_frames), mono])[: mono.size]
    usable = np.abs(delayed) > 1e-2
    return np.divide(output, delayed, out=np.ones_like(delayed), where=usable)[usable]


def test_limiter_ramps_down_instead_of_stepping() -> None:
    """增益要在前瞻視窗內用斜坡降下來，不可以一個樣本就跳到位。

    修正前只取滑動最小值，增益在峰值前 64 框的**一個樣本內**從 1.000 跳到
    0.787 —— 乘在 60 Hz 大正弦上就是一聲喀。斜坡長度是 lookahead + 1 框，
    所以每個樣本最多只能降 (1 − 0.787) / 65 ≈ 0.0033。
    """
    gain = _limiter_gain(BLOCK)
    assert gain.min() < 0.8, "尖峰沒有被壓下來，這條測試量不到東西"
    assert np.abs(np.diff(gain)).max() < 0.01


def test_limiter_ramp_does_not_depend_on_block_size() -> None:
    """斜坡與回復都要跨回呼接續，切塊方式不該改變結果。

    這條順帶抓到一個既有的錯：回復速率的累積最小值把 ``[1:]`` 切在
    accumulate **之前**，上一個回呼的增益根本沒參與 —— 每個回呼的開頭增益
    都直接跳回目標值。峰值被壓過之後，40 dB/s 的回復只在單一回呼內成立，
    跨過回呼邊界（每 60 ms）就是一次增益階梯。
    """
    assert np.allclose(_limiter_gain(137), _limiter_gain(BLOCK), atol=1e-9)


def test_limiter_declared_latency_matches_measured() -> None:
    limiter = Limiter()
    limiter.prepare(RATE, CHANNELS, BLOCK)
    signal = _program(65536, amplitude=0.1)
    output = _run(limiter, signal)
    assert estimate_latency_frames(signal, output, CHANNELS) == limiter.latency_frames


# ------------------------------------------------------------------ 輸出電表


def test_output_meter_does_not_touch_the_signal() -> None:
    meter = OutputMeter()
    meter.prepare(RATE, CHANNELS, BLOCK)
    signal = _program()
    assert np.array_equal(_run(meter, signal), signal)
    assert meter.latency_frames == 0


def test_output_meter_measures_what_it_sees() -> None:
    meter = OutputMeter()
    meter.prepare(RATE, CHANNELS, BLOCK)
    signal = _program(16384, amplitude=0.3)
    _run(meter, signal)

    assert meter.peak == pytest.approx(float(np.abs(signal).max()), rel=1e-6)
    assert meter.rms == pytest.approx(_rms(signal), rel=1e-6)


def test_output_meter_counts_clipping() -> None:
    meter = OutputMeter()
    meter.prepare(RATE, CHANNELS, BLOCK)
    signal = np.ones(1024, dtype=np.float32)
    _run(meter, signal)
    assert meter.clipped_samples == 1024


# ------------------------------------------------------------------ 整條增益鏈


def test_full_chain_cannot_clip_even_at_maximum_boost() -> None:
    """**這是這一包存在的理由。**

    十段全部拉到 +12 dB，餵進接近滿刻度的訊號，輸出仍然不得超過門檻。
    自動餘裕先壓下來、限幅器兜底，兩者缺一都會削波 —— 章程風險 R6。
    """
    eq = GraphicEqualizer()
    limiter = Limiter()
    meter = OutputMeter()

    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, BLOCK)
    graph.set_stages((eq, limiter, meter))
    eq.set_gains([EQ_GAIN_LIMIT_DB] * BANDS)

    hot = _program(32768, amplitude=0.95)
    output = _run(graph, hot)

    assert np.abs(output).max() <= LIMITER_CEILING + 1e-4
    assert meter.clipped_samples == 0
    assert not graph.degraded


def test_full_chain_latency_is_the_sum_of_its_parts() -> None:
    eq = GraphicEqualizer()
    limiter = Limiter()
    meter = OutputMeter()

    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, BLOCK)
    graph.set_stages((eq, limiter, meter))
    gains = _flat()
    gains[5] = 6.0
    eq.set_gains(gains)

    expected = eq.latency_frames + limiter.latency_frames + meter.latency_frames
    assert graph.latency_frames == expected

    signal = _program(131072, amplitude=0.2)
    output = _run(graph, signal)
    assert estimate_latency_frames(signal, output, CHANNELS) == expected


def test_full_chain_is_transparent_when_flat() -> None:
    """EQ 全平時，整條鏈只剩限幅器的延遲，訊號本身不該被改變。"""
    eq = GraphicEqualizer()
    limiter = Limiter()
    graph = DspGraph()
    graph.prepare(RATE, CHANNELS, BLOCK)
    graph.set_stages((eq, limiter, OutputMeter()))
    eq.set_gains(_flat())

    signal = _program(16384, amplitude=0.1)
    output = _run(graph, signal)

    delay = graph.latency_frames * CHANNELS
    assert graph.latency_frames == limiter.latency_frames
    assert np.allclose(output[delay:], signal[: output.size - delay], atol=1e-6)
