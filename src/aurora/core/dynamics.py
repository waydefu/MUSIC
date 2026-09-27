"""前瞻限幅器與輸出電表。

這兩個是 EQ 那一包裡不可分割的部分。理由在 ``PROJECT_PLAN.md`` §5：
目前音量 clamp 在 ``[0, 1]`` 是**唯一**的削波保護，EQ 一旦能提供正增益
它就失效了。只交 EQ 而不交這兩個，等於直接製造削波回歸（章程風險 R6）。

## 限幅器是保險，不是響度工具

章程 §7.1 寫得很明確：「只作 safety net，不當 loudness maximizer」。
實務上這代表：

* 門檻留 0.5 dB 餘裕，不追求把訊號頂到滿刻度。
* 回復慢（40 dB/s），寧可讓增益慢慢爬回來，也不要製造抽吸感。
* 攻擊是**斜坡**不是階梯：增益在前瞻視窗內線性降到位（見下）。

它**會**工作，而且不代表上游出錯。以前這裡寫「EQ 的自動餘裕保證等化後不會
比輸入大，所以限幅器動起來就代表上游沒守規矩」，兩個前提都不成立：

* 自動餘裕只保證**振幅響應** ≤ 0 dB，不保證樣本峰值：相位改變與振鈴照樣會
  讓峰值上升（實測只有衰減的 EQ 把削波過的母帶從 0.950 推到 0.971）。
* 現代母帶的樣本峰值本來就常在 −0.5 dBFS 以上；只要開了任何音效、級聯
  掛上去，這類歌曲一進來限幅器就會壓那零點幾 dB。

所以 :attr:`Limiter.engaged_frames` 是「曾經動作過」的事實紀錄，不是故障指標。

## 為什麼前瞻版可以向量化

前瞻限幅的兩個步驟看起來都是遞迴的，其實都有向量化解法：

**增益要在峰值抵達前就降下來** —— 對每個樣本算出目標增益，再對前瞻視窗
取滑動最小值。``sliding_window_view`` 一次做完。

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
        #: 上一個回呼最後 ``lookahead`` 個滑動最小值，給後向平均接續用。
        self._attack_history = np.ones(lookahead, dtype=np.float64)
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
        self._attack_history.fill(1.0)
        self._gain = 1.0

    def reset(self) -> None:
        if self._delay is not None:
            self._delay.fill(0.0)
        self._attack_history.fill(1.0)
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
        span = self._lookahead + 1
        windows = np.lib.stride_tricks.sliding_window_view(target, span)
        held = windows.min(axis=1)[:frames]

        # 4. 斜坡：對滑動最小值取長度 lookahead+1 的後向平均。峰值位置往回數
        #    的每一個滑動最小值都不大於峰值的目標，平均也就不大於它。
        extended = np.concatenate([self._attack_history, held])
        summed = np.concatenate([[0.0], np.cumsum(extended)])
        attacked = (summed[span:] - summed[:-span]) / span
        self._attack_history[:] = extended[-self._lookahead :]

        # 5. 回復速率限制。遞迴形式等價於下面的累積最小值，見模組 docstring。
        #
        #    ``[1:]`` 要切在 accumulate **之後**：先把上一個回呼的增益放在最前面
        #    一起累積，再丟掉它自己那一格。以前切在 accumulate 之前，prior 根本
        #    沒參與 —— 每個回呼的開頭增益都直接跳回目標值，40 dB/s 的回復只在
        #    單一回呼內成立，被壓過的峰值之後每 60 ms 就有一次增益階梯。
        ramp = np.arange(1, attacked.size + 1, dtype=np.float64) * self._step_db
        prior_db = 20.0 * np.log10(max(self._gain, _EPS))
        target_db = 20.0 * np.log10(np.maximum(attacked, _EPS))
        limited_db = ramp + np.minimum.accumulate(
            np.concatenate([[prior_db], target_db - ramp])
        )[1:]
        limited_db = np.minimum(limited_db, target_db)
        # 最後再對「這個樣本自己的目標」夾一次：累積和的捨入誤差不能讓
        # 峰值越過門檻，哪怕只是 1e-13。
        gain = np.minimum(np.power(10.0, limited_db / 20.0), target[:frames])

        # 6. 套到**延遲後**的訊號上，而不是眼前這一塊 —— 前瞻的意義就在這裡。
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
