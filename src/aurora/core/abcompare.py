"""對齊且音量匹配的 A/B 比較。

**這個模組要回答的問題：「開了之後聽起來比較好」到底是不是真的？**

不做對齊與音量匹配的 A/B 沒有判斷力，因為人耳對這兩件事極度敏感：

* **延遲。** STFT、look-ahead limiter 都會把訊號往後推。沒對齊就直接比，
  量到的差異主要是相位，跟處理器好不好無關。
* **音量。** 大聲一點幾乎永遠「聽起來比較好」。0.5 dB 的差距就足以讓
  盲測失去意義，所以章程 §15 把「A/B RMS 差 ≤0.5 dB」列為 KPI。

跟 Hard Bypass 是**兩件不同的事**，章程 §1.2 特別分開講：
Hard Bypass 要求 bit-identical（完全不碰訊號），A/B 要求時間對齊與音量
匹配（碰了訊號，但比較是公平的）。拿其中一個當另一個用會得到錯誤結論。

## 為什麼要實測延遲

:func:`estimate_latency_frames` 用互相關量出**實際**延遲，再跟處理器
**申報**的 ``latency_frames`` 對照。章程 §1.2 要求「正式追蹤
processing_latency_frames，而不只看 frame count 是否相等」——
申報錯了不會有任何症狀，直到歌詞開始對不上、或 A/V 同步歪掉才發現，
而那時候已經很難回頭找是哪一級算錯了。

有了這個函式，「申報值 == 實測值」就變成一條可以自動跑的測試。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from aurora.core.dsp import mix_to_mono

FloatArray = npt.NDArray[np.float32]

#: 音量匹配與相關性計算的靜音門檻。低於此值視為沒有訊號，
#: 免得對著近乎無聲的段落算出天文數字般的增益。
_SILENCE_RMS = 1e-6

#: 互相關搜尋延遲時的預設上限（框）。8192 @48k 約 170 ms，
#: 足以涵蓋 STFT 與 look-ahead 的合理範圍，又不會讓搜尋變慢。
DEFAULT_MAX_LAG_FRAMES = 8192


@dataclass(frozen=True, slots=True)
class AbResult:
    """一次對齊後比較的結論。"""

    #: 對齊後實際參與比較的框數。
    frames: int
    #: 比較時使用的延遲補償（框）。
    latency_frames: int
    #: 為了匹配音量而套在 processed 上的增益（dB）。
    #: 這個值本身就是資訊：處理器讓訊號大聲了多少。
    applied_gain_db: float
    #: 音量匹配**之後**殘餘的 RMS 差（dB）。應該趨近 0。
    rms_delta_db: float
    #: 音量匹配後的峰值差（dB）。正值代表處理後動態峰值更高，
    #: 那是削波風險的早期警訊。
    peak_delta_db: float
    #: 對齊後的零延遲正規化相關係數（-1..1）。
    #: 接近 1 代表兩者本質相同；明顯偏低代表對齊錯了或處理很激烈。
    correlation: float

    @property
    def level_matched(self) -> bool:
        """是否滿足章程 §15 的「A/B 音量差 ≤0.5 dB」。"""
        return abs(self.rms_delta_db) <= 0.5


def _rms(samples: FloatArray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def _to_db(ratio: float) -> float:
    """線性比值轉 dB。0 與負值回 -inf 而不是拋例外。"""
    if ratio <= 0.0:
        return -math.inf
    return 20.0 * math.log10(ratio)


def align(
    reference: FloatArray,
    processed: FloatArray,
    latency_frames: int,
    channels: int,
) -> tuple[FloatArray, FloatArray]:
    """把兩段交錯訊號在時間上對齊。

    處理器把訊號往後推了 ``latency_frames`` 框，所以要丟掉 processed 的
    開頭與 reference 的結尾，剩下的部分才是同一段時間。

    兩者長度不同時取較短的，不補零 —— 補零會在結尾製造假的差異。
    """
    if latency_frames < 0:
        raise ValueError("latency_frames 不可為負")
    offset = latency_frames * channels
    shifted = processed[offset:] if offset else processed
    usable = min(reference.size, shifted.size)
    usable -= usable % channels  # 不留半框
    return reference[:usable], shifted[:usable]


def estimate_latency_frames(
    reference: FloatArray,
    processed: FloatArray,
    channels: int,
    max_lag_frames: int = DEFAULT_MAX_LAG_FRAMES,
) -> int | None:
    """用互相關量出 processed 相對 reference 落後幾框。

    回傳 ``None`` 代表量不出來，有三種情況：

    * 訊號太安靜或太短。
    * 處理後與原訊號已經沒有足夠相關性（例如整段被換成噪音）。
    * **結果有歧義。** 週期性強的訊號（純音、穩態合成器音色）在每個週期
      都有一個同樣高的相關峰，延遲在數學上就無法唯一決定。這時挑一個
      峰值交差會給出看起來很精確、實際上是隨機的答案。

    最後一條是刻意的：**量不出來就誠實回 None，不要猜。**
    猜錯的延遲比沒有延遲更難除錯 —— 它會讓所有下游的對齊都歪掉，
    而且沒有任何症狀指向這裡。真實音樂夠不規則，正常都量得出來。

    只在單聲道混音上做（延遲是所有聲道共同的），並用 FFT 做互相關 ——
    直接迴圈是 O(n × lag)，在 8192 的搜尋範圍下慢到不能放進測試。
    """
    ref_mono = mix_to_mono(reference, channels)
    proc_mono = mix_to_mono(processed, channels)
    length = min(ref_mono.size, proc_mono.size)
    if length == 0:
        return None

    ref_mono = ref_mono[:length].astype(np.float64)
    proc_mono = proc_mono[:length].astype(np.float64)
    if _rms(ref_mono.astype(np.float32)) < _SILENCE_RMS:
        return None
    if _rms(proc_mono.astype(np.float32)) < _SILENCE_RMS:
        return None

    max_lag = min(max_lag_frames, length - 1)
    if max_lag <= 0:
        return None

    ref_centred = ref_mono - ref_mono.mean()
    proc_centred = proc_mono - proc_mono.mean()

    # 補零到兩倍長度以上，避免 FFT 的循環卷積把尾巴繞回開頭變成假峰值。
    size = 1 << (2 * length - 1).bit_length()
    spectrum = np.conj(np.fft.rfft(ref_centred, size)) * np.fft.rfft(proc_centred, size)
    correlation = np.fft.irfft(spectrum, size)[: max_lag + 1]

    best_lag = int(np.argmax(correlation))
    best = float(correlation[best_lag])
    if best <= 0.0:
        return None

    # 歧義偵測：best_lag 附近以外還有幾乎一樣高的峰，就代表訊號是週期性的，
    # 這個答案只是眾多等價解之一。鄰域寬度取 8 框，足以蓋住峰值本身的寬度
    # 而不會誤殺真正的第二個延遲。
    neighbourhood = correlation.copy()
    low = max(0, best_lag - 8)
    neighbourhood[low : best_lag + 9] = -np.inf
    if neighbourhood.size and float(neighbourhood.max()) > best * 0.99:
        return None

    # 在勝出的 lag 上算一次精確的正規化相關，作為誠實的信心指標。
    # FFT 的峰值高度受補零與長度影響，不能直接當相關係數用。
    span = length - best_lag
    if span < length // 2:
        return None
    score = _correlation(
        ref_mono[:span].astype(np.float32),
        proc_mono[best_lag : best_lag + span].astype(np.float32),
    )
    if score < 0.5:
        return None
    return best_lag


def match_gain_db(reference: FloatArray, processed: FloatArray) -> float:
    """算出要讓 processed 的 RMS 對上 reference 需要多少 dB。

    兩者都靜音時回 0.0 —— 沒有訊號就沒有音量差可言。
    """
    ref_rms = _rms(reference)
    proc_rms = _rms(processed)
    if ref_rms < _SILENCE_RMS or proc_rms < _SILENCE_RMS:
        return 0.0
    return _to_db(ref_rms / proc_rms)


def compare(
    reference: FloatArray,
    processed: FloatArray,
    *,
    latency_frames: int,
    channels: int,
) -> AbResult:
    """對齊、匹配音量，然後量出剩下的差異。

    ``latency_frames`` 應該用處理器**申報**的值。想確認申報是否正確，
    用 :func:`estimate_latency_frames` 量一次再比對 —— 兩者不一致本身
    就是一個缺陷。
    """
    ref, proc = align(reference, processed, latency_frames, channels)
    frames = ref.size // channels
    if frames == 0:
        return AbResult(0, latency_frames, 0.0, 0.0, 0.0, 0.0)

    gain_db = match_gain_db(ref, proc)
    matched = proc * (10.0 ** (gain_db / 20.0))

    ref_rms, matched_rms = _rms(ref), _rms(matched)
    rms_delta = (
        0.0
        if ref_rms < _SILENCE_RMS or matched_rms < _SILENCE_RMS
        else _to_db(matched_rms / ref_rms)
    )

    ref_peak = float(np.abs(ref).max()) if ref.size else 0.0
    proc_peak = float(np.abs(matched).max()) if matched.size else 0.0
    peak_delta = (
        0.0 if ref_peak <= 0.0 or proc_peak <= 0.0 else _to_db(proc_peak / ref_peak)
    )

    return AbResult(
        frames=frames,
        latency_frames=latency_frames,
        applied_gain_db=gain_db,
        rms_delta_db=rms_delta,
        peak_delta_db=peak_delta,
        correlation=_correlation(ref, matched),
    )


def _correlation(a: FloatArray, b: FloatArray) -> float:
    """零延遲的正規化相關係數。兩邊都靜音時回 0.0。"""
    if a.size == 0 or b.size == 0:
        return 0.0
    x = a.astype(np.float64)
    y = b.astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
    if denominator <= 0.0:
        return 0.0
    return float(np.dot(x, y) / denominator)
