"""前瞻限幅器與輸出電表。

這兩個是 EQ 那一包裡不可分割的部分。理由在 ``PROJECT_PLAN.md`` §5：
目前音量 clamp 在 ``[0, 1]`` 是**唯一**的削波保護，EQ 一旦能提供正增益
它就失效了。只交 EQ 而不交這兩個，等於直接製造削波回歸（章程風險 R6）。

## 限幅器是保險，不是響度工具

章程 §7.1 寫得很明確：「只作 safety net，不當 loudness maximizer」。
實務上這代表：

* 門檻為 −1 dBTP，用 4× 插值偵測取樣間峰值，不追求滿刻度。
* 回復慢（40 dB/s），寧可讓增益慢慢爬回來，也不要製造抽吸感。
* 攻擊是**斜坡**不是階梯：增益在前瞻視窗內線性降到位（見下）。

它**會**工作，而且不代表上游出錯。以前這裡寫「EQ 的自動餘裕保證等化後不會
比輸入大，所以限幅器動起來就代表上游沒守規矩」，兩個前提都不成立：

* 自動餘裕只保證**振幅響應** ≤ 0 dB，不保證樣本峰值：相位改變與振鈴照樣會
  讓峰值上升（實測只有衰減的 EQ 把削波過的母帶從 0.950 推到 0.971）。
* 現代母帶的重建峰值本來就常在 −1 dBTP 以上；只要開了任何音效、級聯
  掛上去，這類歌曲一進來限幅器就會壓那零點幾 dB。

所以 :attr:`Limiter.engaged_frames` 是「曾經動作過」的事實紀錄，不是故障指標。

## 為什麼前瞻版可以向量化

前瞻限幅的兩個步驟看起來都是遞迴的，其實都有向量化解法：

**增益要在峰值抵達前就降下來** —— 對每個樣本算出目標增益，再對前瞻視窗
取滑動最小值。``sliding_window_view`` 一次做完。

True-peak 偵測先以 513 抽頭的三個分數相位加原樣本取得 4× 峰值，再把峰值
往兩側各延展 256 框，涵蓋插值支撐區間；區間最大值採 block prefix/suffix。
完整延遲為 256 框偵測未來 + 256 框保護未來 + 64 框攻擊，共 576 框 @48k
（12 ms）。有限插值的餘裕為 0.4 dB；輸出另以獨立的 4×／8× FFT oracle 驗證。

**而且要用斜坡降下來** —— 只取滑動最小值的話，增益會在峰值前 64 框**一個
樣本內**從 1 跳到目標值（實測 1.000 → 0.787），那是乘在訊號上的階梯，
等於在頻譜上灑一片寬頻的喀聲。所以再取一次長度 ``lookahead + 1`` 的
**後向**滑動平均：峰值位置往回數 ``lookahead + 1`` 個滑動最小值全都不大於
峰值的目標增益，平均也就不會大於它 —— 保證仍然成立，而下降變成線性的
1.3 ms 斜坡。滑動平均用累積和一次算完，跨回呼的那一段歷史存在
``_attack_history``。

**回復要有速率上限** —— 這看起來是 ``g[i] = min(target[i], g[i-1] + step)``
的遞迴，但它等價於::

    g[i] = i·step + min over j≤i of (target[j] − j·step)

而 ``min over j≤i`` 就是 :func:`numpy.minimum.accumulate`。整段一次算完，
不需要 Python 迴圈 —— 這與 ``core/eq.py`` 選 FIR 的理由是同一個。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    CLIP_THRESHOLD,
    LIMITER_CEILING,
    LIMITER_FFT_SIZE,
    LIMITER_LOOKAHEAD_FRAMES,
    LIMITER_RELEASE_DB_PER_SEC,
    LIMITER_TRUE_PEAK_FACTOR,
    LIMITER_TRUE_PEAK_MARGIN_DB,
    LIMITER_TRUE_PEAK_TAPS,
)

FloatArray = npt.NDArray[np.float32]


class Limiter:
    """4× true-peak 前瞻限幅器，滿足 ``AudioProcessor``。

    偵測器是有限長度的 sinc 插值，不是連續時間峰值的數學上界。輸出用獨立
    FFT 插值做回歸驗證；DAC 重建與有損編碼之後的峰值不在此保證範圍內。
    原樣本不經過升／降頻，只施加左右連動的增益，安靜訊號保持精確透明。
    """

    def __init__(
        self,
        ceiling: float = LIMITER_CEILING,
        lookahead: int = LIMITER_LOOKAHEAD_FRAMES,
        release_db_per_sec: float = LIMITER_RELEASE_DB_PER_SEC,
    ) -> None:
        if not np.isfinite(ceiling) or not 0.0 < ceiling <= 1.0:
            raise ValueError("限幅門檻必須在 (0, 1] 內")
        if not isinstance(lookahead, int) or lookahead < 0:
            raise ValueError("前瞻必須是非負整數")
        if not np.isfinite(release_db_per_sec) or release_db_per_sec < 0.0:
            raise ValueError("回復速率必須是有限的非負值")
        self._ceiling = ceiling
        self._lookahead = lookahead
        self._release = release_db_per_sec
        self._radius = LIMITER_TRUE_PEAK_TAPS // 2
        self._history_frames = lookahead + 4 * self._radius
        self._margin = 10.0 ** (LIMITER_TRUE_PEAK_MARGIN_DB / 20.0)
        self._channels = 0
        self._max_frames = 0
        self._step_db = 0.0
        self._gain = 1.0
        self._engaged = 0

    @property
    def ceiling(self) -> float:
        return self._ceiling

    @property
    def engaged_frames(self) -> int:
        """實際減少增益的框數累計；是動作紀錄，不是上游故障指標。"""
        return self._engaged

    def reset_statistics(self) -> None:
        self._engaged = 0

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        if sample_rate <= 0 or channels <= 0 or max_frames <= 0:
            raise ValueError("取樣率、聲道與最大框數必須為正值")
        self._channels = channels
        # max_frames 是容量提示，不能讓常見的小回呼為大提示付出 FFT 成本。
        max_frames = min(max_frames, max(1, LIMITER_FFT_SIZE - self._history_frames))
        self._max_frames = max_frames
        self._step_db = self._release / sample_rate
        history = self._history_frames
        count = max_frames + self._lookahead + 2 * self._radius
        self._history = np.zeros((history, channels), dtype=np.float64)
        self._work = np.zeros((history + max_frames, channels), dtype=np.float64)
        self._phase = np.empty((channels, count), dtype=np.float64)
        self._peak = np.empty(count, dtype=np.float64)
        self._candidate = np.empty(count, dtype=np.float64)
        self._target = np.empty(max_frames + self._lookahead, dtype=np.float64)
        self._extended = np.empty(max_frames + self._lookahead, dtype=np.float64)
        self._summed = np.empty(max_frames + self._lookahead + 1, dtype=np.float64)
        self._gain_work = np.empty(max_frames, dtype=np.float64)
        self._db_work = np.empty(max_frames + 1, dtype=np.float64)
        self._ramp = np.arange(1, max_frames + 1, dtype=np.float64) * self._step_db
        self._attack_history = np.ones(self._lookahead, dtype=np.float64)
        self._finite = np.empty((max_frames, channels), dtype=np.bool_)
        # Overlap-save：捨棄前 taps−1 格，循環卷積的繞回不會進入有效區間。
        # FFT 不必再補 taps−1 個零；這讓 2880 框回呼只需 4096 點 FFT。
        self._nfft = 1 << (history + max_frames - 1).bit_length()
        # 聲道各自連續存放，FFT 與跨聲道最大值都避免大量短、跨步的 reduction。
        self._fft_work = np.zeros((channels, self._nfft), dtype=np.float64)
        self._spectrum = np.empty((channels, self._nfft // 2 + 1), dtype=np.complex128)
        self._filtered = np.empty_like(self._spectrum)
        self._inverse = np.empty_like(self._fft_work)
        # 各分數相位有相同支撐區間。係數和正規化為 1，DC 不因相位改變。
        offsets = np.arange(-self._radius, self._radius + 1, dtype=np.float64)
        self._kernels = tuple(
            np.sinc(offsets - phase / LIMITER_TRUE_PEAK_FACTOR)
            for phase in range(1, LIMITER_TRUE_PEAK_FACTOR)
        )
        for kernel in self._kernels:
            kernel /= kernel.sum()
        self._kernel_spectra = tuple(np.fft.rfft(k[::-1], n=self._nfft) for k in self._kernels)
        # 長區間的滑動最大值用 block prefix/suffix，O(n)，不做 O(n·taps) 掃描。
        self._peak_span = 2 * self._radius + 1
        blocks = (count + self._peak_span - 1) // self._peak_span
        self._peak_blocks = np.empty((blocks, self._peak_span), dtype=np.float64)
        self._prefix = np.empty_like(self._peak_blocks)
        self._suffix = np.empty_like(self._peak_blocks)
        self.reset()

    def reset(self) -> None:
        if self._channels:
            self._history.fill(0.0)
            self._attack_history.fill(1.0)
        self._gain = 1.0

    @property
    def latency_frames(self) -> int:
        # FIR 需 radius 框未來樣本；峰值再往左右各延展 radius，讓整個插值
        # 支撐區間上的增益都被保護。兩者另外申報，保留完整的攻擊前瞻。
        return self._lookahead + 2 * self._radius

    def process(self, buf: FloatArray) -> None:
        if not self._channels or buf.size == 0:
            return
        if buf.size % self._channels:
            raise ValueError("交錯樣本數與聲道數不相容")
        view = buf.reshape(-1, self._channels)
        # max_frames 是提示：大區塊分段重用工作區，不在回呼上重新配置。
        for start in range(0, view.shape[0], self._max_frames):
            self._process_chunk(view[start : start + self._max_frames])

    def _process_chunk(self, view: FloatArray) -> None:
        frames = view.shape[0]
        history, radius, lookahead = self._history_frames, self._radius, self._lookahead
        work = self._work[: history + frames]
        work[:history] = self._history
        work[history:] = view
        # 壞樣本不准汙染濾波器歷史；極端但有限的 float32 在 float64 計算不溢位。
        finite = self._finite[:frames]
        np.isfinite(view, out=finite)
        np.logical_not(finite, out=finite)
        np.copyto(work[history:], 0.0, where=finite)

        count = frames + lookahead + 2 * radius
        phase = self._phase[:, :count]
        peak = self._peak[:count]
        candidate = self._candidate[:count]
        target = self._target[: frames + lookahead]
        # 整數相位直接讀原樣本，任何情況都不能漏掉樣本峰值。
        np.abs(work[radius : radius + count].T, out=phase)
        np.max(phase, axis=0, out=peak)
        self._fft_work.fill(0.0)
        self._fft_work[:, : work.shape[0]] = work.T
        np.fft.rfft(self._fft_work, axis=1, out=self._spectrum)
        valid_start = LIMITER_TRUE_PEAK_TAPS - 1
        for kernel_spectrum in self._kernel_spectra:
            np.multiply(self._spectrum, kernel_spectrum[None, :], out=self._filtered)
            np.fft.irfft(self._filtered, n=self._nfft, axis=1, out=self._inverse)
            phase[:] = self._inverse[:, valid_start : valid_start + count]
            np.abs(phase, out=phase)
            np.max(phase, axis=0, out=candidate)
            np.maximum(peak, candidate, out=peak)
        self._peak_blocks.fill(-np.inf)
        self._peak_blocks.ravel()[:count] = peak
        np.maximum.accumulate(self._peak_blocks, axis=1, out=self._prefix)
        np.maximum.accumulate(self._peak_blocks[:, ::-1], axis=1, out=self._suffix[:, ::-1])
        np.maximum(
            self._suffix.ravel()[: target.size],
            self._prefix.ravel()[2 * radius : 2 * radius + target.size],
            out=target,
        )
        np.multiply(target, self._margin, out=target)
        np.maximum(target, np.finfo(np.float64).tiny, out=target)
        np.divide(self._ceiling, target, out=target)
        np.minimum(target, 1.0, out=target)

        span = lookahead + 1
        held = np.lib.stride_tricks.sliding_window_view(target, span)
        extended = self._extended[: frames + lookahead]
        extended[:lookahead] = self._attack_history
        np.min(held, axis=1, out=extended[lookahead:])
        summed = self._summed[: frames + lookahead + 1]
        summed[0] = 0.0
        np.cumsum(extended, out=summed[1:])
        gain = self._gain_work[:frames]
        np.subtract(summed[span:], summed[:-span], out=gain)
        np.divide(gain, span, out=gain)
        if lookahead:
            self._attack_history[:] = extended[-lookahead:]

        db = self._db_work[: frames + 1]
        db[0] = 20.0 * np.log10(max(self._gain, np.finfo(np.float64).tiny))
        np.maximum(gain, np.finfo(np.float64).tiny, out=gain)
        np.log10(gain, out=db[1:])
        np.multiply(db[1:], 20.0, out=db[1:])
        np.subtract(db[1:], self._ramp[:frames], out=db[1:])
        np.minimum.accumulate(db, out=db)
        np.add(db[1:], self._ramp[:frames], out=gain)
        np.divide(gain, 20.0, out=gain)
        np.power(10.0, gain, out=gain)
        np.minimum(gain, target[:frames], out=gain)

        # frames 很小時即將輸出的區間會與歷史尾段重疊，必須先保留原樣本。
        self._history[:] = work[frames:]
        delayed = work[2 * radius : 2 * radius + frames]
        np.multiply(delayed, gain[:, None], out=delayed)
        view[:] = delayed
        engaged = self._finite.ravel()[:frames]
        np.less(gain, 0.999, out=engaged)
        self._engaged += int(np.count_nonzero(engaged))
        self._gain = float(gain[-1])


class OutputMeter:
    """量測**送出去的**訊號。滿足 ``AudioProcessor`` 但不修改任何樣本。

    為什麼需要它：現有的 :class:`~aurora.core.dsp.LevelMeter` 吃的是
    pre-gain 訊號，代表的是**來源**。章程 §1.2 說得很清楚，Source Analyzer
    與 Output Meter 的語意不可混用 —— 一個回答「這個檔案本身如何」，
    另一個回答「使用者實際聽到什麼」。在 EQ 進來之前這兩者幾乎一樣，
    所以沒人注意到只有前者；EQ 一旦能改變訊號，把來源電表當輸出電表用
    就是在說謊。
    """

    def __init__(self) -> None:
        self._peak = 0.0
        self._sum_squares = 0.0
        self._samples = 0
        self._clipped = 0

    @property
    def peak(self) -> float:
        return self._peak

    @property
    def rms(self) -> float:
        if self._samples == 0:
            return 0.0
        return float(np.sqrt(self._sum_squares / self._samples))

    @property
    def clipped_samples(self) -> int:
        return self._clipped

    def reset_statistics(self) -> None:
        self._peak = 0.0
        self._sum_squares = 0.0
        self._samples = 0
        self._clipped = 0

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        pass

    def reset(self) -> None:
        self.reset_statistics()

    @property
    def latency_frames(self) -> int:
        return 0

    def process(self, buf: FloatArray) -> None:
        if buf.size == 0:
            return
        magnitude = np.abs(buf)
        self._peak = max(self._peak, float(magnitude.max()))
        self._sum_squares += float(np.dot(buf, buf))
        self._samples += buf.size
        self._clipped += int(np.count_nonzero(magnitude >= CLIP_THRESHOLD))
