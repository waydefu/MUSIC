"""實測 HRTF 的載入與匯入工具。

沒有 SADIE II 也要能驗完整條路徑，所以這裡自己造 HRIR：**兩耳各一個
脈衝，位置差幾個取樣**。這種訊號的頻域長相有閉式解，可以精確斷言：

    ipsi  = δ(t − a)          contra = δ(t − b)
    H_sum  = e^{-jωa} + e^{-jωb}
    H_diff = e^{-jωa} − e^{-jωb}      ⇒ |H_diff| = 2|sin(ω(b−a)/2)|

也就是說「兩耳時間差」會變成 ``|H_diff|`` 上一個週期已知的起伏 ——
延遲有沒有活著走完「WAV → npz → 重取樣 → 濾波器」這條路，看第一個峰
落在哪個頻率就知道。真人資料集沒有這種可判定性。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from aurora.core import hrtf as hrtf_module
from aurora.core.constants import SPATIAL_FFT_SIZE
from aurora.core.hrtf import load_filters
from aurora.core.spatial import SpatialUpmix

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import import_hrtf

RATE = 48000
FFT = SPATIAL_FFT_SIZE
TAPS = 256


def _write_pair(path: Path, rate: int, left_delay: int, right_delay: int) -> None:
    """寫一個立體聲 WAV：左耳、右耳各一個脈衝，位置由參數決定。"""
    left = np.zeros(TAPS)
    right = np.zeros(TAPS)
    left[left_delay] = 0.5
    right[right_delay] = 0.5
    frames = np.stack([left, right], axis=1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((frames * 32767).astype("<i2").tobytes())


def _dataset(directory: Path, rate: int = RATE, itd_samples: int = 12) -> Path:
    """造出一個「格點命名」的資料集：0°／30°／110° 各一個檔。

    0° 兩耳相同（沒有 ITD），另外兩個方位角讓遠耳晚 ``itd_samples``。
    """
    _write_pair(directory / "azi_0,0_ele_0,0.wav", rate, 8, 8)
    _write_pair(directory / "azi_30,0_ele_0,0.wav", rate, 8 + itd_samples, 8)
    _write_pair(directory / "azi_110,0_ele_0,0.wav", rate, 8 + itd_samples, 8)
    # 仰角不是 0 的量測必須被跳過，否則會蓋掉正確的那一筆。
    _write_pair(directory / "azi_30,0_ele_45,0.wav", rate, 8, 8)
    return directory


def _convert(directory: Path, out: Path) -> int:
    return import_hrtf.main(["--dir", str(directory), "--out", str(out)])


def _ear_delay_samples(filters: object) -> int:
    """從 sum/diff 反算回兩耳的脈衝，量出遠耳比近耳晚幾個取樣。

    ``ipsi = (sum + diff)/2``、``contra = (sum − diff)/2`` —— 就是組成
    sum/diff 的那個變換反過來。直接量延遲，比去看 ``|H_diff|`` 的起伏可靠：
    ``2|sin(ωΔ/2)|`` 有無限多個**等高**的極大值，argmax 挑到哪一個純屬偶然。
    """
    near = np.fft.irfft((filters.front_sum + filters.front_diff) / 2.0, n=FFT)
    far = np.fft.irfft((filters.front_sum - filters.front_diff) / 2.0, n=FFT)
    return int(np.argmax(np.abs(far))) - int(np.argmax(np.abs(near)))


# ------------------------------------------------------------------ 匯入工具


def test_tool_round_trips_into_loadable_filters(tmp_path: Path) -> None:
    out = tmp_path / "hrtf.npz"
    assert _convert(_dataset(tmp_path), out) == 0
    assert load_filters(RATE, FFT, out) is not None


def test_tool_skips_measurements_off_the_horizontal_plane(tmp_path: Path) -> None:
    """仰角 45° 的那一筆不能被當成 30° 的水平量測。"""
    out = tmp_path / "hrtf.npz"
    _convert(_dataset(tmp_path), out)
    filters = load_filters(RATE, FFT, out)
    assert filters is not None
    # 水平的那一筆有 ITD，仰角 45° 的沒有 —— 選錯的話 diff 會是平的。
    # 用與 sum 的比值而不是絕對值：濾波器的絕對尺度是實作細節
    #（例如每支喇叭承擔一半），這條測試不該綁在上面。
    assert float(np.abs(filters.front_diff).max()) > 0.1 * float(np.abs(filters.front_sum).max())


def test_tool_refuses_a_directory_without_parsable_names(tmp_path: Path) -> None:
    _write_pair(tmp_path / "unnamed.wav", RATE, 8, 8)
    assert _convert(tmp_path, tmp_path / "hrtf.npz") == 2


def test_tool_rejects_mono_input(tmp_path: Path) -> None:
    path = tmp_path / "azi_0,0.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.zeros(TAPS, dtype="<i2").tobytes())
    assert import_hrtf.main(["--at", "0", str(path), "--out", str(tmp_path / "o.npz")]) != 0


# ------------------------------------------------------------------ 時間差


def test_interaural_delay_survives_the_round_trip(tmp_path: Path) -> None:
    """兩耳時間差要原封不動走完 WAV → npz → 濾波器。

    正負號也一起驗到了：遠耳必須**晚**於近耳。接反的話整個音場左右顛倒，
    而那用聽的很難確定是哪一邊錯。
    """
    itd = 12
    out = tmp_path / "hrtf.npz"
    _convert(_dataset(tmp_path, itd_samples=itd), out)
    filters = load_filters(RATE, FFT, out)
    assert filters is not None
    assert _ear_delay_samples(filters) == itd


def test_identical_ears_leave_no_difference(tmp_path: Path) -> None:
    """0° 的兩耳相同，所以 centre 那一條不該帶任何耳間差。"""
    out = tmp_path / "hrtf.npz"
    _write_pair(tmp_path / "azi_0,0.wav", RATE, 8, 8)
    _write_pair(tmp_path / "azi_30,0.wav", RATE, 8, 8)
    _write_pair(tmp_path / "azi_110,0.wav", RATE, 8, 8)
    _convert(tmp_path, out)
    filters = load_filters(RATE, FFT, out)
    assert filters is not None
    assert float(np.abs(filters.front_diff).max()) < 1e-9


def test_resampling_preserves_the_delay_in_seconds(tmp_path: Path) -> None:
    """資料集是 44.1 kHz、引擎跑 48 kHz 時，ITD 的**秒數**必須不變。

    重取樣寫錯（例如照抄取樣點數）的話，峰值頻率會跟著取樣率一起偏 8.8%，
    也就是整個音場的方向都會歪掉。
    """
    itd = 12
    out = tmp_path / "hrtf.npz"
    _convert(_dataset(tmp_path, rate=44100, itd_samples=itd), out)
    filters = load_filters(RATE, FFT, out)
    assert filters is not None
    # 12 個取樣 @44.1k = 272 µs；在 48k 下同樣的秒數是 13.06 個取樣。
    assert _ear_delay_samples(filters) == pytest.approx(itd * RATE / 44100, abs=1)


# ------------------------------------------------------------------ 降級


def test_missing_file_falls_back(tmp_path: Path) -> None:
    """沒有檔案是**正常狀態**，不是錯誤 —— 意思是「用合成模型」。"""
    assert load_filters(RATE, FFT, tmp_path / "nope.npz") is None


def test_corrupt_file_falls_back(tmp_path: Path) -> None:
    """壞掉的檔案只能讓功能降級，不能讓播放器炸掉（AGENTS.md 不變量 6）。"""
    path = tmp_path / "hrtf.npz"
    path.write_text("這不是 npz", encoding="utf-8")
    assert load_filters(RATE, FFT, path) is None


def test_missing_keys_fall_back(tmp_path: Path) -> None:
    path = tmp_path / "hrtf.npz"
    np.savez(path, sample_rate=np.int32(RATE))
    assert load_filters(RATE, FFT, path) is None


def test_overlong_impulse_responses_are_rejected(tmp_path: Path) -> None:
    """太長的濾波器在頻域相乘時會繞回框首，寧可退回合成模型。"""
    path = tmp_path / "hrtf.npz"
    taps = int(FFT * 0.5)
    np.savez(
        path,
        sample_rate=np.int32(RATE),
        azimuths=np.asarray([0.0, 30.0, 110.0]),
        ipsi=np.zeros((3, taps)),
        contra=np.zeros((3, taps)),
    )
    assert load_filters(RATE, FFT, path) is None


def test_azimuth_too_far_from_target_is_rejected(tmp_path: Path) -> None:
    """45° 不能拿來冒充 30° —— 那已經不是那個方向的響應了。"""
    path = tmp_path / "hrtf.npz"
    np.savez(
        path,
        sample_rate=np.int32(RATE),
        azimuths=np.asarray([0.0, 45.0, 110.0]),
        ipsi=np.zeros((3, TAPS)),
        contra=np.zeros((3, TAPS)),
    )
    assert load_filters(RATE, FFT, path) is None


# ------------------------------------------------------------------ 接線


def test_renderer_reports_which_source_it_uses(tmp_path: Path, monkeypatch) -> None:
    """UI 要照實說是實測還是合成，所以這件事必須查得到。"""
    out = tmp_path / "hrtf.npz"
    _convert(_dataset(tmp_path), out)
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: out)

    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert upmix.hrtf_is_measured


def test_renderer_falls_back_to_synthetic_without_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: tmp_path / "absent.npz")

    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert not upmix.hrtf_is_measured
    # 合成模型仍然可用，binaural 不會因為缺資料而失效。
    assert upmix.binaural
