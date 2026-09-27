"""把「在參考取樣率下定的樣本數」換算到實際取樣率。

EQ 的抽頭數、反射的帶通與 HRTF 核心、Spatial 的 STFT 視窗，全都是在
:data:`~aurora.core.constants.DSP_REFERENCE_RATE` 下量出來、調出來的樣本數。
它們真正代表的是**時間長度**（因而決定頻率解析度與延遲），所以換了取樣率
就要跟著換算 —— 否則 192k 下同一個核心只剩四分之一的頻率解析度，
低頻段、高通這些「靠長度才做得出來」的東西會靜靜失效。

兩種換算：

* :func:`scaled_taps` —— FIR 抽頭數，保持奇數（線性相位的群延遲才是整數）。
* :func:`scaled_fft_size` —— FFT 長度，取最近的 2 的冪次倍（FFT 效率、
  hop 整除）。44.1k 與 48k 因此用同一個長度。
"""

from __future__ import annotations

import math

from aurora.core.constants import DSP_REFERENCE_RATE

#: 縮放後 FFT 的下限。極低取樣率下再小就分析不出任何頻率結構。
_MIN_FFT = 256


def scaled_taps(reference_taps: int, sample_rate: int) -> int:
    """參考取樣率下的奇數抽頭數，換算成同樣秒數的奇數抽頭數。"""
    if sample_rate <= 0 or sample_rate == DSP_REFERENCE_RATE:
        return reference_taps
    half = (reference_taps - 1) / 2.0 * sample_rate / DSP_REFERENCE_RATE
    return 2 * max(1, round(half)) + 1


def scaled_fft_size(reference_size: int, sample_rate: int) -> int:
    """參考取樣率下的 FFT 長度，換算到最近的 2 的冪次倍。"""
    if sample_rate <= 0:
        return reference_size
    octaves = round(math.log2(sample_rate / DSP_REFERENCE_RATE))
    return max(_MIN_FFT, int(reference_size * 2.0**octaves))
