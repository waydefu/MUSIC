"""全專案常數的單一集中地。

規約：任何模組都不得自行寫死數字常數，一律從這裡取。
QML 側的動效 token 另外集中在 ``qml/Aurora/Motion.qml``；
配色不在 QML，而是由 ``core/models.py`` 的 ``Palette`` 經 ``bridge/theme.py`` 提供。
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- 音訊輸出

#: 查不到輸出端點取樣率時的退路。48k 是 Windows 共用混音器最常見的值。
FALLBACK_SAMPLE_RATE: Final = 48000
OUTPUT_CHANNELS: Final = 2
#: 每次向解碼器索取的框數。1024 @48k ≈ 21ms，兼顧延遲與回呼開銷。
FRAMES_PER_CHUNK: Final = 1024
#: 音量斜坡長度（框）。避免調整音量時的爆音。
VOLUME_RAMP_FRAMES: Final = 512

# ---------------------------------------------------------------- 即時頻譜

FFT_SIZE: Final = 2048
SPECTRUM_BARS: Final = 64
SPECTRUM_FREQ_MIN: Final = 30.0
SPECTRUM_FREQ_MAX: Final = 16000.0
#: 條狀圖上升係數（每幀朝目標值靠近的比例）。大 = 反應快。
BAR_ATTACK: Final = 0.35
#: 條狀圖下降係數。小 = 殘留久，視覺較滑順。
BAR_DECAY: Final = 0.08
#: 峰值標記的重力加速度（正規化單位 / 秒²）。
PEAK_GRAVITY: Final = 1.8
#: 峰值標記被頂上去後停留多久才開始落下（秒）。
PEAK_HOLD_SEC: Final = 0.35
#: 正規化用的滾動最大值衰減係數（每幀）。
ROLLING_MAX_DECAY: Final = 0.999

# ---------------------------------------------------------------- 音質分析

#: 長窗 FFT。8192 @48k → 約 5.9Hz 解析度，足以定位頻譜截止。
ANALYSIS_FFT_SIZE: Final = 8192
#: 相對於頻譜峰值多少 dB 以下視為「沒有內容」。
ROLLOFF_FLOOR_DB: Final = -80.0
#: 累積多少個分析框才願意下判斷。太早下判斷會誤判安靜的前奏。
ROLLOFF_MIN_FRAMES: Final = 40
#: 削波判定門檻（正規化振幅）。
CLIP_THRESHOLD: Final = 0.999
#: 連續多少個滿刻度樣本才算一次削波事件。
CLIP_RUN_LENGTH: Final = 3

#: 頻譜截止 → 推估來源品質的對照表，由高到低比對。
#: (最低截止頻率 Hz, 標籤, 推估位元率 kbps 或 None)
ROLLOFF_TIERS: Final[tuple[tuple[float, str, int | None], ...]] = (
    (20500.0, "無損／透明", None),
    (19000.0, "約 256–320 kbps", 320),
    (17000.0, "約 160–192 kbps", 192),
    (15000.0, "約 128 kbps", 128),
    (0.0, "96 kbps 以下或受傳輸限制", 96),
)
#: 無損容器的截止低於此值 ⇒ 疑似由有損來源轉檔。
#:
#: 刻意訂得保守。真正的無損母帶依混音風格不同，可能在 20–22 kHz 之間任一處
#: 自然收掉；320 kbps 的 LAME 也切在 20.5 kHz 左右。把門檻壓到 20 kHz 表示
#: 我們放過部分高位元率轉檔，但**絕不冤枉**一個真無損檔案 ——
#: 誤報比漏報傷害大得多，使用者會不信任整個面板。
FAKE_LOSSLESS_CUTOFF_HZ: Final = 20000.0

# ---------------------------------------------------------------- 鼓點偵測

ONSET_FFT_SIZE: Final = 1024
ONSET_HOP: Final = 512
#: 自適應門檻：flux 要超過移動中位數的這個倍數。
#: 實測連續白噪音的 flux 雖高（中位數 0.29）但很穩定（最大 0.33，僅 1.15 倍），
#: 1.6 倍足以擋掉；而鼓點通常高出中位數 100 倍以上。
ONSET_THRESHOLD_MULT: Final = 1.6
#: 正規化 flux 的絕對下限。穩定正弦波因頻譜洩漏會有 0.004 上下的抖動，
#: 沒有這個下限的話自適應門檻會把它誤判成連續鼓點。實測鼓點都在 0.85 以上。
ONSET_MIN_FLUX: Final = 0.06
#: 兩次 onset 的最短間隔（秒），避免單一鼓點被觸發多次。
ONSET_MIN_INTERVAL_SEC: Final = 0.08
#: 移動中位數的視窗長度（幀）。
ONSET_MEDIAN_WINDOW: Final = 16

# ---------------------------------------------------------------- 封面抽色

COVER_SAMPLE_SIZE: Final = 64
#: 低於此飽和度的像素不參與主色投票。純白與純灰的飽和度是 0，
#: 所以這一條同時也擋掉了過曝區域 —— 不需要再對明度設上限，
#: 那會誤殺純紅（HSV 明度為 1.0）這類完全合理的鮮豔主色。
COLOR_MIN_SATURATION: Final = 0.15
#: 近黑像素的色相是數值噪音，不可信。
COLOR_MIN_VALUE: Final = 0.12
#: 每通道量化位元數。4 bit → 16 階 → 4096 個分箱。
COLOR_HIST_BITS: Final = 4
#: accent 色的亮度會被強制夾進這個區間，確保在深色底上可讀。
ACCENT_MIN_VALUE: Final = 0.62
ACCENT_MAX_VALUE: Final = 0.98
ACCENT_MIN_SATURATION: Final = 0.45
#: 次要強調色相對主色的色相偏移（度）。
ACCENT2_HUE_SHIFT: Final = 32.0
#: 背景漸層兩端的亮度。
BG_TOP_VALUE: Final = 0.10
BG_BOTTOM_VALUE: Final = 0.04
BG_SATURATION: Final = 0.35
#: 沒有封面時，以檔名雜湊決定色相。
FALLBACK_HUE_COUNT: Final = 360

# ---------------------------------------------------------------- 音樂庫

AUDIO_EXTENSIONS: Final = frozenset({".mp3", ".flac", ".wav", ".ogg", ".oga"})
LYRICS_EXTENSION: Final = ".lrc"
#: 掃描時每累積這麼多首才發一次訊號，避免 signal 風暴。
SCAN_BATCH_SIZE: Final = 50

# ---------------------------------------------------------------- UI 節拍

#: UI 輪詢引擎狀態的頻率。刻意不從音訊執行緒發 Qt signal。
UI_TICK_HZ: Final = 60
#: 輪詢預設輸出端點是否變更的間隔（毫秒）。
ENDPOINT_POLL_MS: Final = 2000
#: 跳轉快捷鍵的步進（秒）。
SEEK_STEP_SEC: Final = 5.0
#: 音量快捷鍵的步進。
VOLUME_STEP: Final = 0.05
