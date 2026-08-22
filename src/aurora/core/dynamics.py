"""前瞻限幅器與輸出電表。

這兩個是 EQ 那一包裡不可分割的部分。理由在 ``PROJECT_PLAN.md`` §5：
目前音量 clamp 在 ``[0, 1]`` 是**唯一**的削波保護，EQ 一旦能提供正增益
它就失效了。只交 EQ 而不交這兩個，等於直接製造削波回歸（章程風險 R6）。

## 限幅器是保險，不是響度工具

章程 §7.1 寫得很明確：「只作 safety net，不當 loudness maximizer」。
實務上這代表：

* 門檻留 0.5 dB 餘裕，不追求把訊號頂到滿刻度。
* 回復慢（40 dB/s），寧可讓增益慢慢爬回來，也不要製造抽吸感。
* 正常情況下它**不應該工作**。EQ 的自動餘裕已經保證等化後不會比輸入大，
  所以限幅器真的動起來時，代表上游有東西沒守規矩 ——
  :attr:`Limiter.engaged_frames` 就是拿來看這件事的。

## 為什麼前瞻版可以向量化

前瞻限幅的兩個步驟看起來都是遞迴的，其實都有向量化解法：

**增益要在峰值抵達前就降下來** —— 對每個樣本算出目標增益，再對前瞻視窗
取滑動最小值。``sliding_window_view`` 一次做完。

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
    LIMITER_LOOKAHEAD_FRAMES,
    LIMITER_RELEASE_DB_PER_SEC,
)

FloatArray = npt.NDArray[np.float32]

_EPS = 1e-12


class Limiter:
    """前瞻峰值限幅器，滿足 ``AudioProcessor``。

    保證輸出峰值不超過 :attr:`ceiling`，代價是 :attr:`latency_frames` 框的延遲。
    """

    def __init__(
        self,
        ceiling: float = LIMITER_CEILING,
        lookahead: int = LIMITER_LOOKAHEAD_FRAMES,
        release_db_per_sec: float = LIMITER_RELEASE_DB_PER_SEC,
    ) -> None:
        self._ceiling = ceiling
        self._lookahead = lookahead
        self._release = release_db_per_sec
        self._channels = 0
        self._sample_rate = 0
        self._step_db = 0.0
        self._delay: npt.NDArray[np.float64] | None = None
        self._gain = 1.0
        self._engaged = 0

    @property
    def ceiling(self) -> float:
        return self._ceiling

    @property
    def engaged_frames(self) -> int:
        """限幅器實際在減少增益的框數累計。

        正常情況下這個值應該幾乎不動。它一直在增加代表上游有東西沒有守住
        自己的餘裕 —— 這是診斷資訊，不是效能指標。
        """
        return self._engaged

    def reset_statistics(self) -> None:
        self._engaged = 0

    # ------------------------------------------------------------ AudioProcessor

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._step_db = self._release / sample_rate
        # 前瞻等同延遲線：輸出落後輸入 lookahead 框。
        self._delay = np.zeros((channels, self._lookahead), dtype=np.float64)
        self._gain = 1.0

    def reset(self) -> None:
        if self._delay is not None:
            self._delay.fill(0.0)
        self._gain = 1.0

    @property
    def latency_frames(self) -> int:
        return self._lookahead

    def process(self, buf: FloatArray) -> None:
        if self._delay is None or self._channels == 0:
            return
        frames = buf.size // self._channels
        if frames == 0:
            return

        view = buf.reshape(frames, self._channels)

        # 1. 把延遲線接在前面，得到「含前瞻的」完整序列。
        padded = np.concatenate([self._delay.T, view.astype(np.float64)], axis=0)

        # 2. 目標增益：以任一聲道的最大絕對值為準（連動處理，不然會歪像場）。
        peak = np.abs(padded).max(axis=1)
        target = np.minimum(1.0, self._ceiling / np.maximum(peak, _EPS))

        # 3. 前瞻：對每個輸出位置取「未來 lookahead+1 個目標」的最小值，
        #    讓增益在峰值抵達之前就降到位。
        windows = np.lib.stride_tricks.sliding_window_view(target, self._lookahead + 1)
        attacked = windows.min(axis=1)[:frames]

        # 4. 回復速率限制。遞迴形式等價於下面的累積最小值，見模組 docstring。
        ramp = np.arange(1, attacked.size + 1, dtype=np.float64) * self._step_db
        prior_db = 20.0 * np.log10(max(self._gain, _EPS))
        target_db = 20.0 * np.log10(np.maximum(attacked, _EPS))
        limited_db = ramp + np.minimum.accumulate(
            np.concatenate([[prior_db], target_db - ramp])[1:]
        )
        limited_db = np.minimum(limited_db, target_db)
        gain = np.power(10.0, limited_db / 20.0)

        # 5. 套到**延遲後**的訊號上，而不是眼前這一塊 —— 前瞻的意義就在這裡。
        delayed = padded[:frames]
        view[:] = (delayed * gain[:, None]).astype(np.float32)

        self._engaged += int(np.count_nonzero(gain < 0.999))
        self._gain = float(gain[-1])
        self._delay[:] = padded[frames:].T


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
