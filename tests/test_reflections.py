"""早期反射的測試。

最重要的一條是「**不可以長出殘響尾巴**」。這一級只有兩個抽頭、沒有回授，
但那是設計意圖 —— 意圖要有測試守著，否則哪天有人「順手」加個回授讓它
更有空間感，就會直接變成浴室音效，而且沒有任何自動化檢查會反對。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    REFLECTION_CROSSFEED,
    REFLECTION_KERNEL_TAPS,
    REFLECTION_TAP_MS,
)
from aurora.core.reflections import EarlyReflections

FloatArray = npt.NDArray[np.float32]

RATE = 48000
CHANNELS = 2
BLOCK = 2880
TAPS = tuple(int(ms * RATE / 1000.0) for ms in REFLECTION_TAP_MS)


def _make(amount: float = 1.0) -> EarlyReflections:
    node = EarlyReflections()
    node.prepare(RATE, CHANNELS, BLOCK)
    node.amount = amount
    return node


def _run(node: EarlyReflections, signal: FloatArray, block: int = BLOCK) -> FloatArray:
    out = signal.copy()
    step = block * CHANNELS
    for start in range(0, out.size, step):
        node.process(out[start : start + step])
    return out


def _stereo(left: np.ndarray, right: np.ndarray) -> FloatArray:
    return np.stack([left, right], axis=1).astype(np.float32).reshape(-1)


def _impulse(frames: int = 1 << 15, channel: int | None = None) -> FloatArray:
    """位於開頭的單位脈衝。``channel`` 指定只放在哪一聲道。"""
    left = np.zeros(frames)
    right = np.zeros(frames)
    if channel in (None, 0):
        left[0] = 1.0
    if channel in (None, 1):
        right[0] = 1.0
    return _stereo(left, right)


def _channels_of(signal: FloatArray) -> tuple[np.ndarray, np.ndarray]:
    view = signal.reshape(-1, CHANNELS)
    return view[:, 0], view[:, 1]


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


# ------------------------------------------------------------------ 透明度


def test_amount_zero_is_completely_transparent() -> None:
    rng = np.random.default_rng(1)
    signal = _stereo(rng.standard_normal(8192) * 0.3, rng.standard_normal(8192) * 0.3)
    assert np.array_equal(_run(_make(0.0), signal), signal)


def test_adds_no_latency() -> None:
    """**這一級的賣點。** 直達聲原樣通過，反射是加在它後面的。

    STFT 類處理都要付延遲，這一級不用 —— 所以它可以白拿。
    """
    assert _make(1.0).latency_frames == 0


def test_direct_sound_passes_through_untouched() -> None:
    """脈衝的第一個樣本必須完全等於輸入。

    如果直達聲被改了，那就不是「反射」而是某種濾波器，
    ``latency_frames == 0`` 的宣稱也會變成謊話。
    """
    output = _run(_make(1.0), _impulse())
    left, _ = _channels_of(output)
    assert left[0] == 1.0


def test_non_stereo_is_left_alone() -> None:
    """交叉餵送需要左右兩聲道。單聲道沒有「側牆」可言。"""
    node = EarlyReflections()
    node.prepare(RATE, 1, BLOCK)
    node.amount = 1.0
    assert not node.active
    assert node.latency_frames == 0


# ------------------------------------------------------------------ 抽頭位置


def test_reflections_arrive_at_the_declared_times() -> None:
    """反射要出現在常數宣告的時間上。時間差就是空間尺度。"""
    output = _run(_make(1.0), _impulse())
    left, right = _channels_of(output)
    energy = np.abs(left) + np.abs(right)

    # 帶通 FIR 有群延遲，所以抽頭會落在一個窗口內而不是精確的樣本上。
    half = (REFLECTION_KERNEL_TAPS - 1) // 2
    for delay in TAPS:
        window = energy[delay : delay + half * 2 + 1]
        assert window.max() > 0.01, f"{delay} 框處沒有反射"


def test_later_reflection_is_weaker() -> None:
    """越晚的反射越弱，那是自然的能量衰減。反過來會聽起來像倒放。"""
    output = _run(_make(1.0), _impulse())
    left, right = _channels_of(output)
    energy = np.abs(left) + np.abs(right)

    half = 32
    first = energy[TAPS[0] : TAPS[0] + half].max()
    second = energy[TAPS[1] : TAPS[1] + half].max()
    assert second < first


# ------------------------------------------------------------------ 不可以有殘響尾巴


def test_no_reverb_tail() -> None:
    """**這是這一級最重要的約束。**

    只有兩個抽頭、沒有回授，所以最後一個反射之後必須是完全的靜音。
    一旦有人加了回授讓它「更有空間感」，尾巴就會長出來，
    「空間」立刻變成「浴室」—— 那是最容易搞砸的方式。
    """
    output = _run(_make(1.0), _impulse())
    left, right = _channels_of(output)

    # 最後一個抽頭加上 FIR 的群延遲之後，再往後應該什麼都沒有。
    quiet_from = TAPS[-1] + REFLECTION_KERNEL_TAPS + 16
    tail = np.abs(left[quiet_from:]) + np.abs(right[quiet_from:])
    assert tail.max() < 1e-6, f"最後一個反射之後還有能量：{tail.max():.2e}"


def test_energy_does_not_grow_over_time() -> None:
    """沒有回授的另一種驗法：連續訊號下輸出不會越來越大。

    有回授的系統餵入穩定訊號時能量會持續累積。
    """
    rng = np.random.default_rng(7)
    signal = _stereo(rng.standard_normal(1 << 17) * 0.2, rng.standard_normal(1 << 17) * 0.2)
    output = _run(_make(1.0), signal)
    left, _ = _channels_of(output)

    quarter = left.size // 4
    early = _rms(left[quarter : quarter * 2])
    late = _rms(left[quarter * 3 :])
    assert late < early * 1.15, "能量隨時間成長 —— 可能有回授"


# ------------------------------------------------------------------ 交叉餵送


def test_reflection_lands_mostly_on_the_opposite_channel() -> None:
    """左聲道的反射主要落在右聲道，模擬側牆路徑。

    同相疊回原聲道只會變成梳狀濾波，聽起來像相位問題而不是空間。
    """
    assert REFLECTION_CROSSFEED > 0.5, "這條測試假設交叉餵送佔多數"

    output = _run(_make(1.0), _impulse(channel=0))
    left, right = _channels_of(output)

    half = 32
    start = TAPS[0]
    same_side = np.abs(left[start : start + half]).max()
    other_side = np.abs(right[start : start + half]).max()
    assert other_side > same_side


# ------------------------------------------------------------------ 頻段與生命週期


def test_reflections_carry_no_low_frequency_content() -> None:
    """低頻反射只會讓聲音變糊，而且低頻的方向性線索本來就弱。

    與 ``spatial.py`` 的低頻護欄是同一個理由。
    """
    output = _run(_make(1.0), _impulse())
    left, right = _channels_of(output)
    # 只看反射區段，避開位於原點的直達脈衝。
    region = (left + right)[TAPS[0] - 16 :]

    spectrum = np.abs(np.fft.rfft(region))
    freqs = np.fft.rfftfreq(region.size, 1.0 / RATE)
    low = spectrum[freqs < 100.0].max()
    mid = spectrum[(freqs > 500.0) & (freqs < 4000.0)].max()
    assert low < mid * 0.2


def test_reset_clears_the_delay_line() -> None:
    """不清的話 seek 之後會聽到上一段的殘留反射。"""
    node = _make(1.0)
    _run(node, _impulse(1 << 14))
    node.reset()

    silence = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    assert np.abs(_run(node, silence)).max() == 0.0


def test_block_size_does_not_change_the_result() -> None:
    """回呼大小是裝置決定的，換一個緩衝設定不該改變聲音。"""
    signal = _impulse(1 << 14)
    big = _run(_make(1.0), signal, block=BLOCK)
    small = _run(_make(1.0), signal, block=137)  # 刻意用不整除的大小
    assert np.allclose(big, small, atol=1e-6)
