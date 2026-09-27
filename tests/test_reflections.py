"""早期反射的測試。

最重要的一條是「**不可以長出殘響尾巴**」。這一級只有兩個抽頭、沒有回授，
但那是設計意圖 —— 意圖要有測試守著，否則哪天有人「順手」加個回授讓它
更有空間感，就會直接變成浴室音效，而且沒有任何自動化檢查會反對。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from aurora.core.constants import (
    HRTF_SURROUND_AZIMUTH_DEG,
    REFLECTION_AZIMUTH_DEG,
    REFLECTION_CROSSFEED,
    REFLECTION_HRTF_FFT_SIZE,
    REFLECTION_HRTF_TAPS,
    REFLECTION_KERNEL_TAPS,
    REFLECTION_TAP_MS,
)
from aurora.core.hrtf import SYNTHETIC_PROFILE, synthetic_filters
from aurora.core.reflections import EarlyReflections, _bandpass_kernel

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


@pytest.mark.parametrize("rate", [96000, 192000])
def test_high_sample_rates_keep_low_frequencies_out(rate: int) -> None:
    """帶通的長度是時間，不是樣本數。

    固定 257 抽頭的話，96k 下頻率解析度只剩一半，300 Hz 的高通在 100 Hz
    只抑制到約 0.3 —— 低頻反射在高取樣率端點上又回來了，而 Windows 共用
    混音器的預設格式本來就可以是 96k 或 192k。
    """
    node = EarlyReflections()
    node.prepare(rate, CHANNELS, rate * 60 // 1000)
    node.amount = 1.0
    output = _run(node, _impulse(1 << 16))
    left, right = _channels_of(output)
    first = int(REFLECTION_TAP_MS[0] * rate / 1000.0)
    region = (left + right)[first - 16 :]

    spectrum = np.abs(np.fft.rfft(region))
    freqs = np.fft.rfftfreq(region.size, 1.0 / rate)
    low = spectrum[freqs < 100.0].max()
    mid = spectrum[(freqs > 500.0) & (freqs < 4000.0)].max()
    assert low < mid * 0.2


def test_switching_back_on_does_not_replay_old_audio() -> None:
    """關著的時候延遲線不前進，裡面留的是上次開著時的東西。

    不清掉的話，從 0 拉回來的那一刻會聽到不知道多久以前的反射。
    """
    node = _make(1.0)
    # 脈衝只往前推 256 框就關掉 —— 它還在 11/23 ms 的延遲線裡。
    _run(node, _impulse(256))
    node.amount = 0.0
    node.amount = 1.0

    silence = np.zeros(BLOCK * CHANNELS, dtype=np.float32)
    assert np.abs(_run(node, silence)).max() == 0.0


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


# ------------------------------------------------------------------ 雙耳 renderer


def _binaural(amount: float = 1.0) -> EarlyReflections:
    """雙耳版本，**釘死合成模型**。

    不釘的話「自動」會去讀使用者資料目錄：有匯入過 HRTF 的開發機量到的是
    那組真人資料，CI 量到的是合成模型 —— 同一套測試驗的不是同一個東西。
    這與 ``tests/test_spatial.py`` 的處理一致（PROJECT_PLAN §9.10）。
    """
    node = EarlyReflections()
    node.hrtf_profile = SYNTHETIC_PROFILE
    node.binaural = True
    node.prepare(RATE, CHANNELS, BLOCK)
    node.amount = amount
    return node


def _program(seconds: float = 3.0, seed: int = 11) -> FloatArray:
    """類節目訊號：置中成分 + 兩側各自去相關的成分。

    合成訊號不能代表真實音樂（§10.5 的教訓），但這裡量的是兩條 renderer
    在**同一個**輸入下的相對差異，不是絕對聽感，所以合成訊號夠用。
    """
    rng = np.random.default_rng(seed)
    n = int(RATE * seconds)
    centre = rng.standard_normal(n) * 0.3
    return _stereo(
        centre + rng.standard_normal(n) * 0.2, centre + rng.standard_normal(n) * 0.2
    )


def _reflection_only(node: EarlyReflections, signal: FloatArray) -> np.ndarray:
    """輸出減輸入。直達聲原樣通過，所以差值就是反射本身。"""
    return (_run(node, signal) - signal).astype(np.float64).reshape(-1, CHANNELS)


def _lead_samples(near: np.ndarray, far: np.ndarray) -> int:
    """``far`` 比 ``near`` 晚幾個取樣。正值代表 ``near`` 先到。

    用互相關量，不用起音位置 —— 脈衝形狀會隨 magnitude 改變，量出來的起音
    會飄（§9.10 在 ITD 上被這件事騙過一次）。
    """
    correlation = np.correlate(far, near, mode="full")
    return int(np.argmax(correlation) - (near.size - 1))


def test_binaural_borrows_the_surround_pair() -> None:
    """反射的方位角與環繞喇叭相同 —— 程式碼直接沿用那一對耳朵響應。

    兩者分家的話 ``_build_binaural_kernels`` 會靜靜地拿錯方向的濾波器，
    而那正是「聽起來怪但說不出哪裡怪」的那類 bug。
    """
    assert REFLECTION_AZIMUTH_DEG == HRTF_SURROUND_AZIMUTH_DEG


def test_binaural_test_helper_really_uses_the_synthetic_model() -> None:
    """守著 ``_binaural`` 的釘選。開發機上有匯入資料時這條會先紅。"""
    assert _binaural().hrtf_is_measured is False


def test_binaural_adds_no_latency() -> None:
    """HRTF 的延遲全都落在反射上，直達聲那一路一個取樣都沒被碰。"""
    assert _binaural().latency_frames == 0


def test_binaural_direct_sound_passes_through_untouched() -> None:
    output = _run(_binaural(1.0), _impulse())
    left, right = _channels_of(output)
    assert left[0] == np.float32(1.0)
    assert right[0] == np.float32(1.0)


def test_binaural_has_no_reverb_tail() -> None:
    """**與立體聲那條路同等重要的約束。**

    多了 HRTF 卷積之後尾巴變長是自然的（核心本身有長度），但那是有限長的
    FIR，不是回授。最後一個抽頭之後再等一個核心長度就該安靜下來。
    """
    output = _run(_binaural(1.0), _impulse())
    left, right = _channels_of(output)
    energy = np.abs(left) + np.abs(right)
    quiet = energy[TAPS[-1] + REFLECTION_HRTF_TAPS + REFLECTION_KERNEL_TAPS :]
    assert quiet.max() < 1e-6


def test_binaural_reflections_arrive_at_the_declared_times() -> None:
    """時間差就是空間尺度 —— 換了 renderer 也不能把它挪走。"""
    output = _run(_binaural(1.0), _impulse())
    left, right = _channels_of(output)
    energy = np.abs(left) + np.abs(right)
    half = REFLECTION_HRTF_TAPS
    for delay in TAPS:
        assert energy[delay : delay + half].max() > 0.01, f"{delay} 框處沒有反射"


def test_binaural_reflection_reaches_the_near_ear_first() -> None:
    """**最要命的那個錯：左右顛倒。**

    偶數號抽頭是左牆，所以它的反射一定要**先**到左耳、而且左耳比較大聲。
    接反的話整個音場鏡射，而聽的人只會覺得「這播放器定位是反的」，
    不會知道錯的是哪一層（§9.10 在方向性聽測工具上踩過同一個坑）。

    ITD 用互相關量，不看資料集或常數宣稱的方向。
    """
    reflections = _reflection_only(_binaural(1.0), _impulse())
    window = slice(TAPS[0], TAPS[0] + REFLECTION_HRTF_TAPS)
    left = reflections[window, 0]
    right = reflections[window, 1]

    assert _lead_samples(left, right) > 0, "左牆的反射沒有先到左耳"
    assert _rms(left) > _rms(right), "左牆的反射在左耳沒有比較大聲"


def test_binaural_matches_the_stereo_renderer_in_loudness() -> None:
    """兩條 renderer 之間只准差「方向」，不准差音量。

    差一點音量就足以讓盲測得到相反的結論（章程 §15 的 0.5 dB 門檻），
    而這一級的音量正是 ``_build_binaural_kernels`` 裡那個推導出來的倍率
    在負責。倍率算錯時這條會紅。
    """
    signal = _program()
    stereo = _rms(_reflection_only(_make(1.0), signal))
    binaural = _rms(_reflection_only(_binaural(1.0), signal))
    assert abs(20.0 * np.log10(stereo / binaural)) < 0.5


def test_binaural_reflections_are_decorrelated_between_the_ears() -> None:
    """這就是頭外化的機制本身。

    交叉餵送給兩耳的差別只有振幅，所以反射在兩耳幾乎是同一個訊號
    （實測相關性 +0.94）—— 大腦收到的訊息是「同一個方向的兩份副本」。
    經過 HRTF 之後兩耳各自帶有自己的 ITD 與頻譜，相關性掉到 0 附近，
    那才是側向反射該有的樣子。

    **方向是不對稱的**：比立體聲更去相關沒問題，強烈反相才會傷人 ——
    負相關聽起來是「在頭裡面」，正好是頭外化的反面（§9.10）。
    """
    signal = _program()
    stereo = _reflection_only(_make(1.0), signal)
    binaural = _reflection_only(_binaural(1.0), signal)

    stereo_iacc = float(np.corrcoef(stereo[:, 0], stereo[:, 1])[0, 1])
    binaural_iacc = float(np.corrcoef(binaural[:, 0], binaural[:, 1])[0, 1])

    assert stereo_iacc > 0.5, "立體聲那條路本來就該是高度相關的"
    assert binaural_iacc < 0.3, "雙耳反射沒有去相關，頭外化的機制就沒生效"
    assert binaural_iacc > -0.3, "反射變成強烈反相，那聽起來會是在頭裡面"


def test_binaural_reflections_carry_no_low_frequency_content() -> None:
    """帶通合進核心裡之後，低頻護欄不能跟著消失。"""
    reflections = _reflection_only(_binaural(1.0), _impulse())
    region = reflections[TAPS[0] - 16 :, 0] + reflections[TAPS[0] - 16 :, 1]
    spectrum = np.abs(np.fft.rfft(region))
    freqs = np.fft.rfftfreq(region.size, 1.0 / RATE)
    assert spectrum[freqs < 100.0].max() < spectrum[(freqs > 500.0) & (freqs < 4000.0)].max() * 0.2


def test_binaural_kernel_is_long_enough_to_hold_its_own_energy() -> None:
    """**截斷長度是量出來的，這條守著那個量測。**

    合成模型的近耳響應是負延遲（波前比正前方早到），irfft 之後那一段會繞到
    緩衝區尾端；把它推回因果區的是帶通的群延遲。所以「核心夠長」與「帶通夠長」
    是同一件事 —— 縮短其中任何一個都會讓波前被切掉，而症狀只是「聽起來悶」，
    不會有任何錯誤。
    """
    size = REFLECTION_HRTF_FFT_SIZE
    filters = synthetic_filters(RATE, size)
    _, _, _, ipsi, contra = filters.ear_responses()
    band = np.fft.rfft(_bandpass_kernel(REFLECTION_KERNEL_TAPS, RATE, 300.0, 7000.0), n=size)

    for response in (ipsi + contra, ipsi - contra):
        full = np.fft.irfft(response * band, n=size)
        kept = float(np.sum(np.square(full[:REFLECTION_HRTF_TAPS])))
        assert kept / float(np.sum(np.square(full))) > 0.9999


def test_switching_binaural_off_returns_the_stereo_renderer_bit_exactly() -> None:
    """關掉之後要逐位元回到 P1 —— §9.9 的預算決定是建立在那條路上的。"""
    signal = _program(seconds=0.5)
    reference = _run(_make(1.0), signal)

    node = EarlyReflections()
    node.hrtf_profile = SYNTHETIC_PROFILE
    node.binaural = True
    node.prepare(RATE, CHANNELS, BLOCK)
    node.amount = 1.0
    node.binaural = False

    assert np.array_equal(_run(node, signal), reference)


def test_binaural_block_size_does_not_change_the_result() -> None:
    """回呼大小是裝置決定的，換一個緩衝設定不該改變聲音。

    切塊處理（比 max_frames 大的回呼）與 overlap-save 的尾巴都在這條裡。
    """
    signal = _program(seconds=0.5)
    small = _run(_binaural(1.0), signal, block=512)
    large = _run(_binaural(1.0), signal, block=BLOCK * 2)
    assert np.allclose(small, large, atol=1e-6)
