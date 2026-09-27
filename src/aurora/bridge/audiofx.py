"""等化器與空間音效的 ViewModel。

把 ``core/eq.py``、``core/dynamics.py``、``core/spatial.py`` 三個純邏輯處理器
接到 QML，並負責設定持久化。DSP 本身一行都不在這裡 —— 這一層只做翻譯。

## 級聯只在需要時才掛上去

兩個處理器在關閉時都會直接返回（``is_flat`` / ``amount == 0``），但**限幅器
不是免費的**：它有延遲線、每次回呼都要算增益包絡，而且會引入 64 框延遲。

所以整條級聯是「有人開啟才掛」。都關掉時 graph 是空的，訊號逐位元原樣
通過，也不宣稱任何延遲 —— 使用者沒開音效就不該付任何代價。

## 順序

``EQ → Spatial → EarlyReflections → Limiter → OutputMeter``

早期反射在空間音效之後：它要對**已經被拉遠的**訊號加反射，順序反過來
就會對原始直達聲加反射，空間線索會互相矛盾。

同一個理由，耳機空間化的三個設定（開關、profile、空間精準度）要**同時**
轉發給空間音效與早期反射：直達聲走 HRTF 而反射走交叉餵送的話，兩者給的
方向線索會互相打架。

限幅器一定在最後（除了電表），因為它要兜住前面所有級加起來的峰值；
電表在限幅器之後，因為它要代表**真正送出去的**訊號。這與章程 §6.1 的
DSP graph 一致。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from aurora.audio.engine import AudioEngine
from aurora.core.config import Config
from aurora.core.constants import EQ_BAND_HZ, EQ_GAIN_LIMIT_DB
from aurora.core.dsp_graph import AudioProcessor
from aurora.core.dynamics import Limiter, OutputMeter
from aurora.core.eq import GraphicEqualizer, band_label
from aurora.core.hrtf import SYNTHETIC_PROFILE, available_profiles
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix


class AudioFxController(QObject):
    """等化器與空間音效的 UI 狀態。

    Signals
    -------
    ``eqChanged()``
        任一段增益、啟用狀態或自動餘裕有變動。
    ``spatialChanged()``
        空間音效的乾濕比有變動。
    ``latencyChanged()``
        整條級聯的延遲有變動。歌詞對齊之後要吃這個值。
    ``degraded(str)``
        某一級處理器出錯，整條已被停用。帶原因字串供 UI 跳提示。
    """

    eqChanged = Signal()
    spatialChanged = Signal()
    latencyChanged = Signal()
    degraded = Signal(str)

    def __init__(
        self, engine: AudioEngine, config: Config, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._config = config

        self._eq = GraphicEqualizer()
        self._spatial = SpatialUpmix()
        self._reflections = EarlyReflections()
        self._limiter = Limiter()
        self._meter = OutputMeter()

        # **設定檔是增益的唯一真相來源，處理器不是。** 停用時處理器會被填成
        # 全平（否則 graph 裡還是會跑 FFT），這時若從處理器讀值，UI 的滑桿
        # 就會歸零、使用者調好的曲線憑空消失。
        self._eq_enabled = config.eq_enabled
        self._spatial.amount = config.spatial_amount
        self._spatial.hrtf_profile = config.hrtf_profile
        self._spatial.cue_strength = config.hrtf_accuracy
        self._spatial.binaural = config.binaural
        self._reflections.amount = config.spatial_amount
        # 反射的 renderer 要與直達聲的一致，所以這三個設定要一起轉發。
        # 分家的話會出現「直達聲走 HRTF、反射走交叉餵送」的組合，
        # 兩者的空間線索互相矛盾，聽起來比兩邊都不開還糟。
        self._reflections.hrtf_profile = config.hrtf_profile
        self._reflections.cue_strength = config.hrtf_accuracy
        self._reflections.binaural = config.binaural

        self._rebuild()

    # ------------------------------------------------------------ 等化器

    @Property(list, constant=True)
    def bandLabels(self) -> list[str]:
        return [band_label(index) for index in range(len(EQ_BAND_HZ))]

    @Property(float, constant=True)
    def gainLimit(self) -> float:
        return EQ_GAIN_LIMIT_DB

    @Property(list, notify=eqChanged)
    def bandGains(self) -> list[float]:
        """使用者設定的曲線。停用時仍然回傳它，滑桿才不會歸零。"""
        return list(self._config.eq_gains)

    @Property(bool, notify=eqChanged)
    def eqEnabled(self) -> bool:
        return self._eq_enabled

    @Property(float, notify=eqChanged)
    def headroomDb(self) -> float:
        """自動套用的 preamp。永遠 ≤ 0，UI 顯示給使用者知道為什麼沒變大聲。"""
        if not self._eq_enabled:
            return 0.0
        return -max(0.0, max(self._config.eq_gains))

    @Slot(bool)
    def setEqEnabled(self, enabled: bool) -> None:
        if enabled == self._eq_enabled:
            return
        self._eq_enabled = bool(enabled)
        self._config.eq_enabled = self._eq_enabled
        self._rebuild()
        self.eqChanged.emit()

    @Slot(int, float)
    def setBandGain(self, index: int, gain_db: float) -> None:
        if not 0 <= index < len(EQ_BAND_HZ):
            return
        gains = list(self._config.eq_gains)
        gains[index] = gain_db
        self._apply_gains(gains)

    @Slot()
    def resetEq(self) -> None:
        self._apply_gains([0.0] * len(EQ_BAND_HZ))

    def _apply_gains(self, gains: list[float]) -> None:
        # 存夾過的值而不是使用者傳進來的，設定檔才不會累積超出範圍的數字。
        self._eq.set_gains(gains)
        self._config.eq_gains = list(self._eq.gains_db)
        self._rebuild()
        self.eqChanged.emit()

    # ------------------------------------------------------------ 空間音效

    @Property(bool, notify=spatialChanged)
    def binauralEnabled(self) -> bool:
        return self._spatial.binaural

    @Slot(bool)
    def setBinauralEnabled(self, enabled: bool) -> None:
        if bool(enabled) == self._spatial.binaural:
            return
        self._spatial.binaural = bool(enabled)
        self._reflections.binaural = self._spatial.binaural
        self._config.binaural = self._spatial.binaural
        self.spatialChanged.emit()

    @Property(list, notify=spatialChanged)
    def hrtfProfiles(self) -> list[str]:
        """可選的 profile。第一項永遠是內建合成模型，之後是使用者匯入的。

        把合成模型列成明確的選項，是因為「真人資料到底有沒有比較好」只能
        靠 A/B 回答 —— 沒有這個選項就比不了。
        """
        return [SYNTHETIC_PROFILE, *available_profiles()]

    def _active_profile(self) -> str:
        """設定裡的「自動」解析成實際生效的那一組。

        寫成方法而不是從別處讀 Property：Qt 的 Property 在型別檢查眼裡不是
        字串，跨方法讀它會得到看不懂的錯誤。
        """
        chosen = self._config.hrtf_profile
        if chosen:
            return chosen
        profiles = available_profiles()
        return profiles[0] if profiles else SYNTHETIC_PROFILE

    @Property(str, notify=spatialChanged)
    def hrtfProfile(self) -> str:
        """目前實際生效的 profile 名稱。"""
        return self._active_profile()

    @Slot(str)
    def setHrtfProfile(self, name: str) -> None:
        # 比的是**設定裡存的值**，不是解析後生效的那一組。沒有匯入任何資料時
        # 「自動」解析出來就是合成模型，但明確選了合成模型仍然是一個要記住的
        # 選擇 —— 之後匯入資料時「自動」會跑掉，明確選的不會。
        if name == self._config.hrtf_profile:
            return
        self._config.hrtf_profile = name
        self._spatial.hrtf_profile = name
        self._reflections.hrtf_profile = name
        self.spatialChanged.emit()

    @Property(float, notify=spatialChanged)
    def hrtfAccuracy(self) -> float:
        """空間精準度：高＝定位準，低＝音色自然。**不是高頻等化。**"""
        return self._spatial.cue_strength

    @Slot(float)
    def setHrtfAccuracy(self, value: float) -> None:
        if abs(value - self._spatial.cue_strength) < 1e-6:
            return
        self._spatial.cue_strength = value
        self._reflections.cue_strength = self._spatial.cue_strength
        self._config.hrtf_accuracy = self._spatial.cue_strength
        self.spatialChanged.emit()

    @Property(bool, notify=spatialChanged)
    def hrtfIsMeasured(self) -> bool:
        """目前用的是使用者匯入的實測資料，還是內建的合成頭部模型。

        UI 必須照實顯示。合成模型沒有耳廓，做不出可靠的前後區分 ——
        讓它冒充完成品，使用者只會覺得功能壞了。
        """
        return self._spatial.hrtf_is_measured

    @Property(float, notify=spatialChanged)
    def spatialAmount(self) -> float:
        return self._spatial.amount

    @Slot(float)
    def setSpatialAmount(self, amount: float) -> None:
        if abs(amount - self._spatial.amount) < 1e-6:
            return
        self._spatial.amount = amount
        self._reflections.amount = self._spatial.amount
        self._config.spatial_amount = self._spatial.amount
        self._rebuild()
        self.spatialChanged.emit()

    # ------------------------------------------------------------ 輸出狀態

    @Property(float, notify=latencyChanged)
    def latencyMs(self) -> float:
        """整條級聯的延遲（毫秒）。都關掉時是 0。"""
        rate = self._engine.sample_rate
        if rate <= 0:
            return 0.0
        return self._engine.processing_latency_frames / rate * 1000.0

    @Property(bool, notify=eqChanged)
    def limiterEngaged(self) -> bool:
        """限幅器是否曾經真的動作過。

        這是**事實紀錄**，不是故障指標。以前這裡寫「EQ 的自動餘裕已經保證
        不會超過，變成 True 代表上游沒守規矩」，但自動餘裕只保證振幅響應
        ≤ 0 dB、不保證樣本峰值，而且現代母帶的峰值本來就常在限幅門檻
        （−0.5 dBFS）以上 —— 詳見 ``core/dynamics.py`` 的模組 docstring。
        """
        return self._limiter.engaged_frames > 0

    def poll(self) -> None:
        """由 UI tick 呼叫。把回呼執行緒設下的旗標取回主執行緒。

        降級只會在回呼裡被標記（那裡不能做 I/O、也不能發 Qt signal），
        所以要靠輪詢把它撈出來 —— 與 ``AudioEngine.take_finished`` 同一個模式。
        """
        reason = self._engine.graph.take_degradation()
        if reason is not None:
            self.degraded.emit(reason)

    # ------------------------------------------------------------ 內部

    def _rebuild(self) -> None:
        """依目前的啟用狀態重建級聯。**只能從主執行緒呼叫。**"""
        # 停用時把處理器填成全平，否則 graph 裡還是會跑 FFT。
        self._eq.set_gains(
            self._config.eq_gains if self._eq_enabled else [0.0] * len(EQ_BAND_HZ)
        )
        eq_active = self._eq_enabled and not self._eq.is_flat
        stages: tuple[AudioProcessor, ...] = ()
        if eq_active or self._spatial.amount > 0.0:
            stages = (self._eq, self._spatial, self._reflections, self._limiter, self._meter)

        before = self._engine.graph.latency_frames
        self._engine.graph.set_stages(stages)
        if self._engine.graph.latency_frames != before:
            self.latencyChanged.emit()
