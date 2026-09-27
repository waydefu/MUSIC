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


def _dataset(
    directory: Path,
    rate: int = RATE,
    itd_samples: int = 12,
    lead: int = 8,
    near: str = "right",
) -> Path:
    """造出一個「格點命名」的資料集：0°／30°／110° 各一個檔。

    0° 兩耳相同（沒有 ITD），另外兩個方位角讓遠耳晚 ``itd_samples``。
    ``near`` 決定正方位角在哪一側 —— 真實資料集兩種都有（SADIE II 是左）。
    ``lead`` 是共模傳播延遲，兩耳都有，匯入時應該被切掉。
    """
    far = lead + itd_samples
    left, right = (lead, far) if near == "left" else (far, lead)
    _write_pair(directory / "azi_0,0_ele_0,0.wav", rate, lead, lead)
    _write_pair(directory / "azi_30,0_ele_0,0.wav", rate, left, right)
    _write_pair(directory / "azi_110,0_ele_0,0.wav", rate, left, right)
    # 仰角不是 0 的量測必須被跳過，否則會蓋掉正確的那一筆。
    _write_pair(directory / "azi_30,0_ele_45,0.wav", rate, lead, lead)
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
    # 濾波器是環形的：置中路徑被對齊到零點之後，比它早到的近耳落在負時間
    # （緩衝區尾端），與合成模型的慣例一樣。所以差值要以環形距離計。
    lag = int(np.argmax(np.abs(far))) - int(np.argmax(np.abs(near)))
    return (lag + FFT // 2) % FFT - FFT // 2


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


def _decaying_responses(path: Path, rate: int, taps: int) -> Path:
    """每個方位角都放同一條衰減中的隨機脈衝響應 —— 只用來測長度檢查。"""
    rng = np.random.default_rng(31)
    response = np.exp(-np.arange(taps) / (taps / 8.0)) * rng.standard_normal(taps)
    np.savez(
        path,
        sample_rate=np.int32(rate),
        azimuths=np.asarray([0.0, 30.0, 110.0]),
        ipsi=np.asarray([response] * 3),
        contra=np.asarray([response] * 3),
    )
    return path


def test_length_limit_applies_after_resampling(tmp_path: Path) -> None:
    """上限是 STFT 視窗的比例，而視窗是以**引擎**取樣率計的。

    以前拿原始長度比：44.1 kHz 的 512 抽頭到了 48 kHz 是 557 抽頭，
    超過上限 512 卻照收。反過來，96 kHz 的長響應降到 48 kHz 之後其實夠短，
    卻會被誤拒。
    """
    limit = int(FFT * 0.25)
    upsampled = _decaying_responses(tmp_path / "up.npz", 44100, limit)
    assert load_filters(RATE, FFT, upsampled) is None

    downsampled = _decaying_responses(tmp_path / "down.npz", 96000, int(limit * 1.8))
    assert load_filters(RATE, FFT, downsampled) is not None


def test_centre_path_is_aligned_with_the_dry_signal(tmp_path: Path) -> None:
    """置中路徑的延遲必須是 0，否則乾濕交叉淡入就是梳狀濾波。

    匯入工具切掉共模延遲之後，置中 HRIR 仍比最早到的近耳晚約半個 ITD
    加護欄。以 110° 近耳領先 16 個取樣、護欄 8 個取樣來說，置中落在第 24 個
    取樣（0.5 ms）—— 實測 amount=0.5 時置中內容有 −9.4～+2.7 dB 的起伏。
    """

    def spike(position: int) -> np.ndarray:
        response = np.zeros(TAPS)
        response[position] = 1.0
        return response

    path = tmp_path / "late_centre.npz"
    np.savez(
        path,
        sample_rate=np.int32(RATE),
        azimuths=np.asarray([0.0, 30.0, 110.0]),
        ipsi=np.asarray([spike(24), spike(18), spike(8)]),
        contra=np.asarray([spike(24), spike(30), spike(40)]),
    )
    filters = load_filters(RATE, FFT, path)
    assert filters is not None
    assert int(np.argmax(np.abs(np.fft.irfft(filters.centre, n=FFT)))) == 0
    # 方向線索（兩耳之間的相對時序）不可以被對齊動到。
    assert _ear_delay_samples(filters) == 12


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
    # 兩個位置都要隔離，否則會抓到開發者自己匯入的 profile。
    monkeypatch.setattr(hrtf_module, "hrtf_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: out)

    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert upmix.hrtf_is_measured


def test_renderer_falls_back_to_synthetic_without_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(hrtf_module, "hrtf_dir", lambda: tmp_path / "absent")
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: tmp_path / "absent.npz")

    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert not upmix.hrtf_is_measured
    # 合成模型仍然可用，binaural 不會因為缺資料而失效。
    assert upmix.binaural


# ------------------------------------------------------------------ 座標與對齊


def test_both_ear_conventions_produce_identical_filters(tmp_path: Path) -> None:
    """資料集的方位角正方向朝左或朝右，轉出來的濾波器必須一模一樣。

    這是近耳偵測的核心不變量。猜錯側別的話音場會左右顛倒，而那用聽的很難
    確定是哪一邊錯 —— 所以工具不看慣例，直接量「哪耳先收到聲音」。
    實例：SADIE II 是逆時針，+30° 在左邊；別套資料集可能相反。
    """
    right_dir, left_dir = tmp_path / "r", tmp_path / "l"
    right_dir.mkdir()
    left_dir.mkdir()
    _dataset(right_dir, near="right")
    _dataset(left_dir, near="left")

    out_right, out_left = tmp_path / "r.npz", tmp_path / "l.npz"
    assert _convert(right_dir, out_right) == 0
    assert _convert(left_dir, out_left) == 0

    from_right = load_filters(RATE, FFT, out_right)
    from_left = load_filters(RATE, FFT, out_left)
    assert from_right is not None and from_left is not None
    assert np.allclose(from_right.front_sum, from_left.front_sum)
    assert np.allclose(from_right.front_diff, from_left.front_diff)
    assert np.allclose(from_right.surround_diff, from_left.surround_diff)


def test_conflicting_near_ear_is_refused(tmp_path: Path) -> None:
    """兩個方位角量到相反的近耳 ⇒ 資料有問題，停下來要求人明講。

    默默挑一邊會產生一個左右顛倒但完全不報錯的音場。
    """
    _write_pair(tmp_path / "azi_0,0_ele_0,0.wav", RATE, 8, 8)
    _write_pair(tmp_path / "azi_30,0_ele_0,0.wav", RATE, 20, 8)
    _write_pair(tmp_path / "azi_110,0_ele_0,0.wav", RATE, 8, 20)
    assert _convert(tmp_path, tmp_path / "hrtf.npz") != 0


def test_common_propagation_delay_is_removed(tmp_path: Path) -> None:
    """量測 HRIR 前面那段共模空白必須切掉，否則濕訊號會比乾訊號晚。

    H13 的實測值是 102 個取樣（2.1 ms）。renderer 會把濕與乾交叉淡入，
    差 102 個取樣相加就是梳狀濾波 —— 48 kHz 下每 471 Hz 一個凹陷，很空。
    """
    lead, itd = 100, 12
    out = tmp_path / "hrtf.npz"
    assert _convert(_dataset(tmp_path, lead=lead, itd_samples=itd), out) == 0

    with np.load(out) as data:
        assert int(data["trimmed"]) == lead - 8, "應該切到只剩護欄的那幾個取樣"
        near = np.asarray(data["ipsi"])[0]
    assert int(np.argmax(np.abs(near))) <= 8

    # 切掉的是**共模**的部分，兩耳之間的 ITD 必須原封不動。
    filters = load_filters(RATE, FFT, out)
    assert filters is not None
    assert _ear_delay_samples(filters) == itd


# ------------------------------------------------------------------ Profile


def _install(directory: Path, name: str, monkeypatch) -> Path:
    """把一組合成的 HRTF 裝成具名 profile。"""
    root = directory / "profiles"
    root.mkdir(exist_ok=True)
    monkeypatch.setattr(hrtf_module, "hrtf_dir", lambda: root)
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: directory / "legacy.npz")
    source = directory / name
    source.mkdir()
    out = root / f"{name}.npz"
    assert _convert(_dataset(source), out) == 0
    return out


def test_profiles_are_listed_by_name(tmp_path: Path, monkeypatch) -> None:
    _install(tmp_path, "ku100", monkeypatch)
    _install(tmp_path, "kemar", monkeypatch)
    assert hrtf_module.available_profiles() == ("kemar", "ku100")


def test_legacy_single_file_still_shows_up(tmp_path: Path, monkeypatch) -> None:
    """已經匯入過的人升級之後不該突然找不到自己的資料。"""
    legacy = tmp_path / "legacy.npz"
    monkeypatch.setattr(hrtf_module, "hrtf_dir", lambda: tmp_path / "nonexistent")
    monkeypatch.setattr(hrtf_module, "hrtf_file", lambda: legacy)
    assert _convert(_dataset(tmp_path), legacy) == 0
    assert hrtf_module.available_profiles() == ("imported",)
    assert hrtf_module.profile_path("imported") == legacy


def test_empty_profile_name_means_automatic(tmp_path: Path, monkeypatch) -> None:
    """空字串＝自動：有匯入就用第一組。

    這條讓已經匯入過的使用者升級後行為不變，而不是突然掉回合成模型。
    """
    _install(tmp_path, "ku100", monkeypatch)
    assert hrtf_module.resolve_profile("") is not None


def test_synthetic_is_selectable(tmp_path: Path, monkeypatch) -> None:
    """必須能明確選內建模型 —— 不然「真人資料有沒有比較好」就無從 A/B。"""
    _install(tmp_path, "ku100", monkeypatch)
    assert hrtf_module.resolve_profile(hrtf_module.SYNTHETIC_PROFILE) is None


def test_missing_profile_falls_back_instead_of_crashing(tmp_path: Path, monkeypatch) -> None:
    """使用者刪掉檔案之後播放器不該就此打不開。"""
    _install(tmp_path, "ku100", monkeypatch)
    assert hrtf_module.resolve_profile("deleted") is None

    upmix = SpatialUpmix()
    upmix.hrtf_profile = "deleted"
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert not upmix.hrtf_is_measured
    assert upmix.binaural


def test_switching_profile_reloads_the_filters(tmp_path: Path, monkeypatch) -> None:
    _install(tmp_path, "ku100", monkeypatch)

    upmix = SpatialUpmix()
    upmix.binaural = True
    upmix.prepare(RATE, 2, 2880)
    assert upmix.hrtf_is_measured, "自動應該挑到 ku100"

    upmix.hrtf_profile = hrtf_module.SYNTHETIC_PROFILE
    assert not upmix.hrtf_is_measured

    upmix.hrtf_profile = "ku100"
    assert upmix.hrtf_is_measured
