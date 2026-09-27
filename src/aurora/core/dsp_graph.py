"""音訊回呼上的 DSP 級聯，以及它的安全網。

這個模組本身不做任何訊號處理。它只回答一個問題：
**要在音訊回呼裡串接一連串處理器，需要哪些規則才不會把播放器弄壞？**

EQ、Spatial、Limiter 之後都掛在這裡。先把契約定死，是因為回呼執行緒的
錯誤代價特別高：一個沒接住的例外會讓 miniaudio 的產生器結束，播放停在
那裡，而 UI 完全不知道發生什麼事 —— 使用者只看到「播放器不動了」。

## 五條規則

1. :meth:`AudioProcessor.process` 一律 **in-place**，不回傳新陣列。
2. ``process()`` **不得產生可避免的穩態配置**。工作 buffer 在
   :meth:`AudioProcessor.prepare` 配好。判定標準是「穩態下不成長」而不是
   「絕對為零」—— NumPy 的 ufunc 與 CPython 內部本來就會有小型配置，
   去追那些是浪費時間。真正要擋的是「每次回呼都新建一批 ndarray／
   FFT workspace／filter buffer」。
3. latency 由各處理器自行申報，:class:`DspGraph` 負責加總。
4. 任何例外 → 整個 graph **永久**降級為 bypass。不可每次回呼重試，
   否則每 60 ms 拋一次例外比原本的問題更糟。
5. bypass 時 samples **完全不被觸碰** —— Hard Bypass 必須 bit-identical。

## 執行緒

``process()`` 跑在音訊回呼執行緒；其餘方法都由主執行緒呼叫。

級聯本身用**不可變的 tuple 發佈**：主執行緒換掉整條 tuple，回呼執行緒
把它一次讀進區域變數再走訪。GIL 保證屬性讀寫是原子的，所以回呼永遠看到
某個完整版本的級聯，不會看到換到一半的狀態。這與倉庫既有的「背景執行緒
只產生不可變資料」是同一個原則。

**回呼裡不做 I/O，也不印任何東西。** 降級的原因只是記下來，由主執行緒
用 :meth:`DspGraph.take_degradation` 取走再決定怎麼呈現 —— 跟
``AudioEngine.take_finished`` 是同一個模式。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]


@runtime_checkable
class AudioProcessor(Protocol):
    """掛在回呼上的一級處理。

    實作時把上面那五條規則當硬性要求，不是建議 —— 違反其中任何一條，
    症狀都會是難以重現的爆音或斷續，而不是乾脆的錯誤。
    """

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        """在主執行緒上配置資源。取樣率或裝置變更時會再呼叫一次。

        ``max_frames`` 是**預期**的單次回呼上限，用來預先配置工作 buffer。
        它是提示不是保證：實際回呼可能更大（例如離線推進），處理器要嘛
        自己撐住，要嘛拋例外讓 graph 降級 —— 但不可以靜靜地算錯。
        """
        ...

    def process(self, buf: FloatArray) -> None:
        """在回呼執行緒上就地處理交錯的 float32 samples。"""
        ...

    def reset(self) -> None:
        """清掉與位置相關的狀態。換歌與 seek 時呼叫。"""
        ...

    @property
    def latency_frames(self) -> int:
        """這一級引入的演算法延遲（框）。沒有就回 0。"""
        ...


class DspGraph:
    """依序執行的處理器級聯，外加一張永久性的安全網。

    空的 graph（預設狀態）等同 bypass：``process`` 直接返回，
    samples 一個位元都不會變。
    """

    def __init__(self) -> None:
        self._stages: tuple[AudioProcessor, ...] = ()
        self._bypass = False
        self._degraded = False
        self._reason: str | None = None
        self._pending_reason: str | None = None
        self._config: tuple[int, int, int] | None = None
        # 每一級最後一次是用哪組參數 prepare 的。以 id 為鍵並同時留住物件本身，
        # 避免處理器被回收後 id 被別的物件重用而誤判成「已經 prepare 過」。
        # 不用 WeakKeyDictionary：dataclass 之類的處理器可能不可雜湊。
        self._prepared: dict[int, tuple[AudioProcessor, tuple[int, int, int]]] = {}

    # ------------------------------------------------------------ 狀態

    @property
    def stages(self) -> tuple[AudioProcessor, ...]:
        return self._stages

    @property
    def bypass(self) -> bool:
        """使用者要求的 Hard Bypass。"""
        return self._bypass

    @bypass.setter
    def bypass(self, value: bool) -> None:
        self._bypass = bool(value)

    @property
    def degraded(self) -> bool:
        """是否因為例外而被永久停用。"""
        return self._degraded

    @property
    def degradation_reason(self) -> str | None:
        """降級原因。取走之後仍然留著，供診斷用。"""
        return self._reason

    @property
    def active(self) -> bool:
        """這次回呼會不會真的做事。"""
        return bool(self._stages) and not self._bypass and not self._degraded

    @property
    def latency_frames(self) -> int:
        """整條級聯的演算法延遲。bypass 或降級時是 0。"""
        if not self.active:
            return 0
        return sum(stage.latency_frames for stage in self._stages)

    def take_degradation(self) -> str | None:
        """消費「剛剛降級了」這個事件。UI 輪詢一次，讀到就自動清除。

        跟 ``AudioEngine.take_finished`` 同一個模式：回呼執行緒只設旗標，
        要不要跳提示、怎麼跳，全部由主執行緒決定。
        """
        pending, self._pending_reason = self._pending_reason, None
        return pending

    # ------------------------------------------------------------ 主執行緒

    def set_stages(self, stages: tuple[AudioProcessor, ...]) -> None:
        """換掉整條級聯。

        新的處理器會立刻套用目前的 ``prepare`` 參數，這樣回呼拿到的一定是
        已經配置好的東西。整條 tuple 一次換掉，回呼不會看到中間狀態。

        **已經在跑的級絕對不再 prepare。** 以前這裡對每一級都無條件
        prepare，而 UI 每移動一格滑桿就會換一次 tuple（內容其實沒變）——
        結果每一格都把 Spatial 的輸出佇列清空、重新預填一個視窗的靜音，
        實測每次 2121 樣本（44 ms）的斷音。更糟的是 prepare 在主執行緒上
        重新配置 buffer，而回呼可能正走到一半，兩邊讀到不一致的長度就會拋
        broadcast 例外，整條 graph 永久降級。

        所以規則是：

        * 參數跟上次不同（或從沒 prepare 過）→ prepare。
        * 參數相同、但上一版 tuple 裡沒有它（被拿掉後又加回來）→ 只 reset，
          清掉它離開期間殘留的舊音訊。它不在回呼正在走的 tuple 裡，所以安全。
        * 參數相同、而且一直在 tuple 裡 → 什麼都不做。
        """
        if self._config is not None:
            live = {id(stage) for stage in self._stages}
            for stage in stages:
                record = self._prepared.get(id(stage))
                if record is None or record[0] is not stage or record[1] != self._config:
                    self._prepare_stage(stage, self._config)
                elif id(stage) not in live:
                    stage.reset()
        self._stages = tuple(stages)

    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None:
        """設定格式並讓每一級預先配置。裝置換取樣率時會再呼叫。

        呼叫端要保證這時回呼沒有在跑（引擎在換取樣率前會先拆掉裝置）——
        prepare 會重新配置工作 buffer，不能與 ``process`` 同時發生。
        """
        self._config = (sample_rate, channels, max_frames)
        for stage in self._stages:
            self._prepare_stage(stage, self._config)

    def _prepare_stage(self, stage: AudioProcessor, config: tuple[int, int, int]) -> None:
        stage.prepare(*config)
        self._prepared[id(stage)] = (stage, config)

    def reset(self) -> None:
        """換歌／seek 時清掉各級的位置相關狀態。

        **不會**解除降級。降級代表有處理器真的壞了，換一首歌不會把它修好；
        要解除必須明確呼叫 :meth:`clear_degradation`。
        """
        for stage in self._stages:
            stage.reset()

    def clear_degradation(self) -> None:
        """解除降級，讓級聯重新啟用。只有在真的修好之後才該呼叫。"""
        self._degraded = False
        self._reason = None
        self._pending_reason = None

    # ------------------------------------------------------------ 回呼執行緒

    def process(self, buf: FloatArray) -> None:
        """就地跑完整條級聯。**這個方法永遠不會拋例外。**

        任何一級出錯就整條永久停用並記下原因，這一次回呼的 samples 維持
        原樣送出去 —— 使用者會聽到未處理的音訊，而不是一片寂靜。
        """
        if self._bypass or self._degraded:
            return
        stages = self._stages  # 一次原子讀取，避免走訪到一半被換掉
        if not stages:
            return

        try:
            for stage in stages:
                stage.process(buf)
        # 這裡故意攔下所有 Exception。整個模組存在的理由就是「不讓任何東西
        # 逃到回呼外面」—— 逃出去的下場是產生器結束、播放靜靜停住。
        except Exception as exc:
            # 回呼執行緒不做 I/O，所以只記錄不列印。主執行緒會來取。
            self._degraded = True
            self._reason = f"{type(exc).__name__}: {exc}"
            self._pending_reason = self._reason
