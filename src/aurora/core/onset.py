"""鼓點（onset）偵測，用來驅動封面衝擊、色散閃動與擴散環等動效。

演算法是標準的 **spectral flux**：把相鄰兩幀頻譜的「正向差」加總，
能量突然湧現時這個值會尖起來。門檻取移動中位數的倍數，
所以整首歌變大聲時不會整段狂觸發 —— 它偵測的是變化，不是音量。

純 numpy，可以對合成節拍訊號做單元測試。
"""

from __future__ import annotations

from collections import deque

import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    ONSET_FFT_SIZE,
    ONSET_HOP,
    ONSET_MEDIAN_WINDOW,
    ONSET_MIN_FLUX,
    ONSET_MIN_INTERVAL_SEC,
    ONSET_THRESHOLD_MULT,
)

FloatArray = npt.NDArray[np.float32]

#: 中位數要先累積這麼多幀才開始判定，避免開頭幾幀的雜訊被當成鼓點。
_MIN_HISTORY = 4
#: 頻譜總能量低於此值視為靜音，正規化會除出無意義的大數。
_SILENCE_ENERGY = 1e-6


class OnsetDetector:
    """串流式鼓點偵測器。持續餵 PCM，回報偵測到的時間點。"""

    def __init__(
        self,
        sample_rate: int,
        fft_size: int = ONSET_FFT_SIZE,
        hop: int = ONSET_HOP,
    ) -> None:
        self._sample_rate = sample_rate
        self._fft_size = fft_size
        self._hop = hop
        self._window = np.hanning(fft_size).astype(np.float32)
        self._previous = np.zeros(fft_size // 2 + 1, dtype=np.float32)
        self._history: deque[float] = deque(maxlen=ONSET_MEDIAN_WINDOW)
        self._pending = np.zeros(0, dtype=np.float32)
        self._position = 0
        self._last_onset = -ONSET_MIN_INTERVAL_SEC
        self._primed = False

    def reset(self) -> None:
        self._previous[:] = 0.0
        self._history.clear()
        self._pending = np.zeros(0, dtype=np.float32)
        self._position = 0
        self._last_onset = -ONSET_MIN_INTERVAL_SEC
        self._primed = False

    def feed(self, mono: FloatArray) -> list[float]:
        """餵入單聲道 PCM，回傳本批中偵測到的 onset 時間（秒，自串流起算）。"""
        if mono.size:
            self._pending = np.concatenate((self._pending, mono.astype(np.float32, copy=False)))

        detected: list[float] = []
        while self._pending.size >= self._fft_size:
            block = self._pending[: self._fft_size]
            timestamp = self._position / self._sample_rate
            self._pending = self._pending[self._hop :]
            self._position += self._hop

            if self._step(block, timestamp):
                detected.append(timestamp)
        return detected

    def _step(self, block: FloatArray, timestamp: float) -> bool:
        magnitude = np.abs(np.fft.rfft(block * self._window)).astype(np.float32)
        rise = float(np.sum(np.maximum(magnitude - self._previous, 0.0)))
        total = float(magnitude.sum())
        self._previous = magnitude

        # 除以該幀總能量，把 flux 變成「相對增量」而非絕對值。
        # 這一步是整個偵測器能用的關鍵：連續白噪音的絕對 flux 很大，
        # 但相對值穩定在 0.29 上下；鼓點則會直接衝到 0.85 以上。
        flux = rise / total if total > _SILENCE_ENERGY else 0.0

        # 第一幀的前一幀是全零，flux 必然爆表。既不能當事件，
        # 也不能進歷史 —— 否則中位數會被墊高好幾幀，開頭的鼓點全被吃掉。
        if not self._primed:
            self._primed = True
            return False

        median = float(np.median(self._history)) if self._history else 0.0
        threshold = max(median * ONSET_THRESHOLD_MULT, ONSET_MIN_FLUX)
        self._history.append(flux)

        if len(self._history) < _MIN_HISTORY:
            return False
        if flux <= threshold:
            return False
        if timestamp - self._last_onset < ONSET_MIN_INTERVAL_SEC:
            return False

        self._last_onset = timestamp
        return True
