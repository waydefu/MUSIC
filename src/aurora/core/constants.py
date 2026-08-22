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
#: 告訴 DSP 級聯「單次回呼最多幾框」時，在名目值上乘的餘裕係數。
#: 名目值是裝置緩衝長度換算的框數，但那只是提示：離線推進可以送任意大小，
#: 某些驅動也會給比名目值更大的塊。寧可讓處理器多配一點記憶體，
#: 也不要讓它在回呼裡因為 buffer 不夠而重新配置。
CALLBACK_FRAMES_HEADROOM: Final = 2

# ---------------------------------------------------------------- 等化器

#: 10 段 ISO 標準中心頻率（Hz）。
EQ_BAND_HZ: Final[tuple[float, ...]] = (
    31.0, 62.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0
)
#: 每段的增益上下限（dB）。章程 §7.1 訂 ±12。
EQ_GAIN_LIMIT_DB: Final = 12.0
#: FIR 核心長度（抽頭數）。奇數，這樣線性相位的群延遲剛好是 (N-1)/2 的整數。
#:
#: 這個數字是**低頻解析度與延遲的取捨**，不是隨便挑的：
#: 1023 抽頭 @48k 給約 47 Hz 的頻率解析度與 511 框（10.6 ms）的延遲。
#: 再短的話 31 Hz 那一段就沒有東西可以塑形（31 Hz 一個週期要 1548 個樣本），
#: 再長則延遲開始影響歌詞對齊與未來的 A/V 同步。
EQ_FIR_TAPS: Final = 1023

# ---------------------------------------------------------------- 空間音效

#: STFT 視窗長度。1024 @48k 約 47 Hz 解析度 —— 足以分辨「人聲」與「殘響」
#: 的相關性差異，這裡不做外科手術式的音源分離，不需要更細。
#:
#: **延遲等於這個值**（1024 框 ≈ 21 ms），不是 ``fft_size − hop``。
#: 前者是 STFT 的演算法延遲，但輸出只能以 hop 為單位產生，而回呼大小是
#: 裝置決定的任意值 —— 為了任何 block 大小都不 underrun，輸出佇列必須
#: 預填滿一個完整視窗。已用模擬驗證 ``fft_size − hop`` 的預填在
#: block=64／2880 時會 underrun。
#:
#: 選 1024 而不是 2048：延遲減半（42.7 ms → 21.3 ms），FFT 成本也減半。
#: A2 的 EQ 已經吃掉 9.22% 的 p99 預算，這裡省下來的很重要。
SPATIAL_FFT_SIZE: Final = 1024
#: 跳距。50% 重疊，sqrt-Hann 在這個重疊下相加為 1，可完美重建。
SPATIAL_HOP: Final = 512
#: 相關性的時間平滑係數（一階遞迴，越大越平滑）。
#:
#: 一定要平滑。逐框的瞬時相關性抖動很大，直接拿來當增益會讓穩定的人聲
#: 每 20 ms 被推一次，聽起來像有東西在呼吸。0.85 在「跟得上轉場」與
#: 「不抖」之間。
SPATIAL_COHERENCE_SMOOTHING: Final = 0.85
#: 去相關環繞成分折回立體聲時的音量。
#: 這是 P1 唯一真正「加東西」的地方，保守一點 —— 過量會讓像場散掉。
SPATIAL_SURROUND_LEVEL: Final = 0.6
#: 原始 side 成分的寬度倍率。1.0 = 不改變原本的立體聲寬度。
SPATIAL_WIDTH: Final = 1.0

# ---------------------------------------------------------------- 限幅與電表

#: 限幅器門檻（線性振幅）。留 0.5 dB 餘裕，避免轉檔或 DAC 端的
#: 取樣間峰值（inter-sample peak）超過滿刻度。
LIMITER_CEILING: Final = 0.944
#: 前瞻長度（框）。64 @48k ≈ 1.3 ms —— 夠讓增益在峰值抵達前降下來，
#: 又短到不會明顯增加延遲。
LIMITER_LOOKAHEAD_FRAMES: Final = 64
#: 增益回復速率（dB／秒）。慢回復比較不容易聽出抽吸感；
#: 這是 safety net 不是 loudness maximizer，回復慢一點沒有壞處。
LIMITER_RELEASE_DB_PER_SEC: Final = 40.0

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
