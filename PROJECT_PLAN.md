# AURORA 專案規畫書

《AURORA 企業級專案章程 v1.0》（2026-08-22，基準 commit `0f8618f`）回答「要往哪走」。
本文件回答**「兩個人怎麼同時動工而不互相擋路」**。

章程是單一路線的敘述。本文件把它的音訊路線切成兩條可並行的軌道，並把兩條軌道之間的
介面先釘死——這是本文件真正的價值，不是重述章程。

| 欄位 | 內容 |
|---|---|
| 版本 / 日期 | v1.0 / 2026-08-22 |
| 基準 | commit `0f8618f`、`__version__ = "0.1.0"` |
| 涵蓋範圍 | 章程的 PI-0～PI-1 音訊部分 + macOS 桌面平台 |
| 人力 | 架構期單人（維護者，Windows）；分軌期兩人（+ 一位 Mac 開發者） |

---

## 1. 定位與範圍

### 1.1 與章程的分工

| 文件 | 負責 |
|---|---|
| 章程 v1.0 | 方向、願景、風險登記、KPI、長期 Roadmap |
| **本文件** | 階段順序、兩人分工、介面契約、驗證管道 |
| [AGENTS.md](AGENTS.md) | 倉庫不變量、驗證矩陣、證據等級 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 現有模組責任與資料流 |

章程的數字與風險編號（R1、R6、§6.3 等）在本文件直接引用，不複製。

### 1.2 本階段做什麼

- 建立可承載 DSP 的地基（graph 契約、安全網、量測）
- 等化器（EQ）全套
- 環繞音效 P1：虛擬 5.1 upmix
- macOS 能跑起來

### 1.3 本階段明確**不**做

影片播放、4K/HDR、YouTube 匯出、iOS、Android、C++ / C ABI 下沉、macOS 打包與簽章。

這些不是被遺忘，是刻意排除。章程把它們排在 PI-3 之後。

---

## 2. 現況基線

目前的音訊鏈路是**乾淨但空的**：

```
檔案 → miniaudio.stream_file → float32 stereo PCM
     → Analyzer（寫入環形緩衝）
     → 音量斜坡
     → PlaybackDevice
```

中間沒有任何 DSP 級。以下九點是動工前已核對原始碼確認的事實，
它們直接決定了本文件的階段順序。

| # | 事實 | 影響 |
|---|---|---|
| 1 | `platform_win/` 對外只有 4 個呼叫點 | macOS 移植比章程假設的便宜得多 |
| 2 | 著色器已在編 Metal（[tools/build_shaders.py](tools/build_shaders.py) 的 `--msl 12`） | macOS 的 `ShaderEffect` 路徑不需要新工作 |
| 3 | PySide6 / miniaudio / mutagen / numpy 全套跨平台 | 不需要換技術棧 |
| 4 | [src/aurora/core/paths.py](src/aurora/core/paths.py) 的 `app_data_dir()` 寫死 `%APPDATA%` | 唯一硬綁 Windows 的核心路徑 |
| 5 | [tests/test_endpoint.py](tests/test_endpoint.py) 已有 `skipif(sys.platform != "win32")` | 平台跳過有現成模式可沿用 |
| 6 | `@pytest.mark.audio` 只用在 [tests/test_engine.py](tests/test_engine.py) 的 3 個測試 | 唯一會開實體音訊裝置的部分 |
| 7 | 沒有 `.github/`，也沒有任何 benchmark 工具 | CI 與量測都是從零開始 |
| 8 | **今天的程式碼在 macOS 上連 import 都過不了** | 見下方 2.1 |
| 9 | `EndpointInfo`、`TransportKind` 已在 core，只有 `EndpointSnapshot` 位置錯 | 見 §4.3 |

三個目前不存在的東西要特別點名，因為後面反覆會提到：
**callback 沒有任何例外防護**、**沒有任何實測效能數字**、**沒有 CI**。

### 2.1 為什麼 macOS 現在連 import 都過不了

[src/aurora/bridge/quality.py](src/aurora/bridge/quality.py) 在**模組層級** import
`platform_win.endpoint` 與 `platform_win.btregistry`，而後者 import `winreg` 與
`ctypes.wintypes`——這兩個在 macOS 上 import 當場失敗。

這不是「跑起來會怪怪的」，是「載不進來」。所以 macOS 的 CI job 在平台縫完成之前
**不可能**綠。這是 S3 存在的真正理由。

---

## 3. 階段與軌道

### 3.1 架構期：單人循序

Mac 開發者在分軌期才加入，所以架構期沒有人在等待。順序因此可以純粹依
**資訊價值與風險**排，不必為了解除別人的封鎖而搶做。

| # | 項目 | 為什麼排這個位置 |
|---|---|---|
| **S1** | GitHub Actions CI（`windows-latest` job，跑現況） | 不改任何程式碼就能上線，之後每個 patch 都自動驗證。同時建立章程 §17 要求的 baseline |
| **S2** | callback benchmark harness + 現況基線數字 | 必須在**未改動的**程式碼上量才是真基線。而且這個數字是 S4 的**設計輸入** |
| **S3a** | 把 `EndpointSnapshot` 搬到 core（前置小 patch） | 不搬的話 S3b 的 Protocol 會反過來依賴 Windows 型別 |
| **S3b** | 平台縫（`platform/` 契約 + Windows 薄包裝） | 小、無即時性顧慮。完成後 macOS CI job 才可能綠 |
| **S4** | DSP graph 縫 + 安全網 + Hard Bypass | 最大的一塊，且只有自己接下來要用。放最後，讓它吃到 S2 的數字 |

**S2 為什麼一定要在 S4 之前**：先知道 Python callback 到底還剩多少 headroom，
才能決定 DSP graph 該設計到什麼複雜度。反過來做的話，很容易因為
「覺得 Python 應該慢」而提早下沉 C++——章程 §4 的 Measure Before Optimize
擋的就是這件事。

### 3.2 分軌期：兩人並行

| 軌道 A — 音訊（維護者，Windows） | 軌道 B — macOS（開發者 2，Mac） |
|---|---|
| **A1** Aligned A/B compare | **B1** `platform/macos.py` 實作 |
| **A2** EQ 全套（§5，不可拆） | **B2** `app_data_dir()` 的 macOS 分支 |
| **A3** Spatial P1 虛擬 5.1（§5.1） | **B3** macOS CI job 轉綠 |
| | **B4** 實機驗證（§8） |

軌道指派的理由：**開發者 2 的開發機就是 Mac**，macOS 軌由他從實作到實機測試一手包辦。

### 3.3 驗證不對稱——分軌期最大的協作風險

架構期是單人，沒有這個問題。但分軌期一開始它就存在，**規則要先立好再開工**。

維護者在 Windows、開發者 2 在 Mac。**兩人都無法在本機驗證對方的平台。**

- 開發者 2 改到 `core/` 或 `bridge/` 時，看不見自己是否弄壞了 Windows 路徑
- 維護者的 DSP graph 改動，也無法在本機證明 macOS 仍然跑得動

這正是「可自動化的 Gate 全面移至 GitHub Actions」這個決定真正的價值——
它不只是省事，而是這個組合下**唯一**能防止互相破壞的機制。

據此三條硬規則：

1. `windows-latest` 與 `macos-latest` 兩個 job **都**必須是 required check，缺一不可
2. 平台差異一律走 `platform/` 契約。不得在 `bridge/` 或 `core/` 裡直接寫
   `sys.platform` 分支——唯一例外是 `paths.py` 的 `app_data_dir()`
3. 任何一方宣稱「另一個平台沒問題」時，**證據只能是 CI 的輸出**，不能是推論

---

## 4. 介面契約

本文件最重要的一節。兩份契約都要在動工前定稿，因為它們是兩條軌道的接縫。

### 4.1 契約一：`AudioProcessor` / `DspGraph`

新檔 `core/dsp_graph.py`。位於 `core/`，因此受 mypy strict 且不得 import Qt。

```python
class AudioProcessor(Protocol):
    def prepare(self, sample_rate: int, channels: int, max_frames: int) -> None: ...
    def process(self, buf: FloatArray) -> None: ...   # in-place，callback 執行緒
    def reset(self) -> None: ...
    @property
    def latency_frames(self) -> int: ...
```

五條規則：

1. `process()` 一律 **in-place**，不回傳新陣列
2. `process()` **不得產生可避免的穩態配置**——工作 buffer 在 `prepare()` 配好（精確定義見 4.2）
3. latency 由 processor 自行申報，`DspGraph` 負責加總
4. 任何例外 → 整個 graph **永久**降級為 bypass 並記錄一次。
   **不可每 callback 重試**，否則每 60 ms 拋一次例外比原本的問題更糟
5. bypass 時 samples 完全不被觸碰 → **bit-identical**

[src/aurora/audio/engine.py](src/aurora/audio/engine.py) 的 `_process` 改成：

```
analyzer.push_interleaved  →  graph.process  →  gain ramp
```

這個順序刻意符合章程 §6.1：Source Analyzer 在最前（量的是來源），
User Volume 在最後（不污染量測）。現行程式碼已經是這個語意，改動只是在中間插入 graph。

### 4.2 「零配置」不能寫成絕對保證

用 Python + NumPy 時，部分 ufunc、FFT backend 與 CPython 內部行為會產生小型
runtime allocation，即使程式碼看起來完全 in-place。把契約寫成「理論上零 allocation」
的後果是有人花好幾天去追 NumPy 內部幾個小物件——**而那不是章程 R1 的成因**。

契約的正確寫法：

> 不得有 graph 自己建立的、隨 callback 累積或成長的、可避免的穩態配置。

真正要擋的是「每 60 ms 就新建一批 ndarray / FFT workspace / filter buffer」這種等級的事。

量測方式配套：**pre-warm 若干次 callback 後**才開始取樣，用 `tracemalloc` 或
`sys.getallocatedblocks()` 在**多次 iteration 之間**取差值，
判定標準是「穩態下不成長」而非「絕對為零」。這樣才抓得到回歸又不會產生假警報。

### 4.3 前置工作：`EndpointSnapshot` 搬到 core

**這件事必須在契約二之前完成，而且獨立成一個 patch。**

不搬的話，`PlatformAdapter` 的回傳型別會指向 `platform_win.endpoint.EndpointSnapshot`，
等於平台抽象層反過來依賴 Windows 模組——那就不是 seam，只是換了個名字。

好消息是這件事比看起來便宜：

- `EndpointInfo` 與 `TransportKind` **本來就在** [src/aurora/core/models.py](src/aurora/core/models.py)
- `EndpointSnapshot`（[src/aurora/platform_win/endpoint.py](src/aurora/platform_win/endpoint.py)）
  只是持有它們的薄容器，**內容本身已經中立**，純粹是位置錯了
- [src/aurora/platform_win/__init__.py](src/aurora/platform_win/__init__.py) 的 docstring
  早就宣告「對上層只暴露 `aurora.core.models` 裡的值物件」

換句話說**這是修既有漂移，不是引入新規則**。

唯一的實際工作：`hfp_also_connected` 這個 property 依賴模組私有的 `_strip_hfp_suffix`，
搬家時要一起處理，連同它在 [tests/test_endpoint.py](tests/test_endpoint.py) 的回歸測試。

**不另建 `platform/models.py`。** 這個倉庫已經有指定的值物件家（`core/models.py`），
而且這個型別的組成零件都已經住在那裡。開第三個家只會讓「該放哪」變模糊。

### 4.4 契約二：`PlatformAdapter`

新套件 `platform/`。

```python
class PlatformAdapter(Protocol):
    def system_animations_enabled(self) -> bool: ...
    def query_endpoints(self) -> EndpointSnapshot | None: ...   # core.models 的中立型別
    def host_context(self) -> HostContext: ...
    def register_file_types(self) -> bool: ...
    def unregister_file_types(self) -> bool: ...
    def os_build(self) -> int: ...
```

- `platform/windows.py` 是**薄包裝**，轉呼叫現有 `platform_win/`。
  刻意不搬動既有實作檔案（那裡有兩百行手寫的 COM vtable 呼叫），把風險壓到最低
- `platform/macos.py` 由開發者 2 實作。Core Audio 的資訊要轉成**同一個**中立
  `EndpointSnapshot`；查不到的回 `None`／`False`，音質面板降級顯示
- 依賴方向仍是 `qml → bridge → audio/library/platform → core`
- 改完要檢查 [aurora.spec](aurora.spec) 的 hiddenimports 是否需要補新子套件

現有的 4 個呼叫點會改成透過 adapter 取得：
[src/aurora/bridge/motion.py](src/aurora/bridge/motion.py)、
[src/aurora/bridge/player.py](src/aurora/bridge/player.py)、
[src/aurora/bridge/quality.py](src/aurora/bridge/quality.py)、
[src/aurora/__main__.py](src/aurora/__main__.py)。

---

## 5. EQ 是一包，不可拆

現在音量 clamp 在 `[0, 1]`（[src/aurora/audio/engine.py](src/aurora/audio/engine.py)
的 `volume` setter），這是**唯一**的削波保護。EQ 一旦能提供正增益，這道保護就失效。

所以以下五項必須**同一批交付**：

```
Graphic / Parametric EQ
  + Auto Headroom
  + Match Gain
  + Limiter
  + Output Meter
```

本質上這是一個完整的 gain-staging feature，不是五個功能。
只交「+12 dB 的 EQ」而 limiter 與 headroom 還沒好，等於直接製造削波回歸——
章程風險 R6 講的就是這件事。

**同時要注意**：目前的 `LevelMeter`（[src/aurora/core/dsp.py](src/aurora/core/dsp.py)）
吃的是 pre-gain 訊號，也就是說**現在只有 source meter，沒有 output meter**。
UI 上不能把它當輸出電平用。Output Meter 是這一包裡的新東西，不是既有元件的改名。

### 5.1 Spatial P1 的 renderer 邊界

「P1 = 虛擬 5.1 upmix，還沒有 HRTF」這句話**只描述了場景建構，沒有描述輸出**。
不補完的話，之後必然出現這個爭論：
「5.1 都已經拆出來了，但沒有 HRTF，耳機到底怎麼聽到？」

P1 的完整鏈路是四段，缺一不可：

```
Stereo
  → Virtual 5.1 Scene        （FL FR C LFE SL SR，僅為內部表示）
  → Basic Stereo Renderer
  → 2ch output
```

| 階段 | 負責 |
|---|---|
| **P1 Basic Stereo Renderer** | 中置／前方重建、ambience folding、去相關的環繞貢獻、立體聲寬度與深度 |
| **P2 HRTF Renderer** | 前後定位、頭外化（externalization）、虛擬喇叭 |

這個切法不是保守，而是**被現況決定的**：解碼器目前強制 stereo
（[src/aurora/audio/engine.py](src/aurora/audio/engine.py) 把 `OUTPUT_CHANNELS`
直接餵給 `stream_file`），**根本沒有 5.1 輸出路徑可走**。
folding 回 stereo 是唯一選項，不是妥協。

真正的多聲道輸出要等「解除強制 stereo」，已列在 §11 押後。

> **5.1 場景在 P1 是中介表示，不是輸出格式。**

---

## 6. CI 契約與搬不動的殘餘

### 6.1 決策的精確措辭

> **所有可自動化、可重現的 Gate** 全面移至 GitHub Actions。

不是「所有測試」。下面這四項本質上搬不動，硬要塞進 CI 只會得到假綠燈。

| 項目 | 為什麼搬不動 | 去處 |
|---|---|---|
| `@pytest.mark.audio`（3 個） | runner 沒有音訊裝置 | CI 用 `-m "not audio"`；兩人各自在本機跑自己的平台 |
| `build_exe.py --verify` | 可在 windows runner 跑但很慢 | 只在 tag / 手動觸發 |
| benchmark 的權威數字 | runner 是共用 VM，尾端數字不可信（詳見 §7） | 本機 `--device` |
| GUI 外觀、實際出聲、著色器視覺 | 本質需要人 | `release-preflight` 的手動清單 |

### 6.2 Job 規劃

`windows-latest` 與 `macos-latest` 兩個 job，各跑：

```
uv sync --dev
→ 產生測試素材（tools/make_test_audio.py）
→ ruff check .
→ mypy
→ pytest -m "not audio"
→ QT_QPA_PLATFORM=offscreen aurora --validate-qml
```

兩個實作細節要在 S1 實際確認，不要假設：

- **ffmpeg 是否為 runner 內建**——[tools/make_test_audio.py](tools/make_test_audio.py)
  需要它做格式轉換。沒有內建就加安裝步驟。
  素材缺席時測試是 **skip 而不是 fail**，所以這一步做錯會得到「綠燈但其實沒測到」
- **`PYTHONUTF8=1`**——`make_test_audio.py` 輸出被重導向時會印中文，
  沒有這個環境變數在 Windows 上會 `UnicodeEncodeError`

### 6.3 一件好消息

非 ASCII 路徑這條頭號不變量在 CI 上**仍然被守住**。
[tests/test_engine.py](tests/test_engine.py) 的守門測試是用 `tmp_path` 自己造中文目錄
（`音樂 資料夾 テスト`），不依賴倉庫路徑本身。所以 CI 跑在 ASCII 路徑下也照樣有效。

---

## 7. benchmark 契約

新增 `bench_callback.py`（放 [tools/](tools)），兩種模式：

| 模式 | 做什麼 | CI |
|---|---|---|
| `--offline` | 用 `AudioEngine.pump()` 推進，不開音訊裝置 | **可執行** |
| `--device` | 真實 `PlaybackDevice` + Qt UI + Analyzer + GC | **不可執行**（runner 沒有音訊裝置） |

輸出 p50 / p95 / p99 / p99.9 / max，以 deadline 百分比表示，對齊章程 §6.3 的
mean ≤10% / p99 ≤25% / max ≤50%。

### 7.1 為什麼效能數字不能上 CI

這個問題會反覆被問，所以正面回答：**不能**。

理由不是「跑不動」（offline 模式跑得動），而是**數字不可信**。
GitHub 的 runner 是共用 VM，鄰居噪音在 CPU-bound 微基準上造成的變異很大，
而受污染最嚴重的正是 p99 / p99.9——也就是這個 benchmark 唯一的重點。
章程 R1 要抓的是 Python GC 造成的長尾；在 VM 上量到的尾巴主要是 hypervisor 排程抖動。

**不準的尾端數字比沒有數字更危險**，因為它會讓人以為問題已經被量過了。

所以章程 §6.3 的正式數字**只能在實體機器上跑 `--device` 產生**。

### 7.2 CI 上該放的是確定性檢查

這五條不受 VM 噪音影響：

| 檢查 | 怎麼測 | 價值 |
|---|---|---|
| **穩態下無可避免的配置** | pre-warm 後多次 iteration 取差值 | **配置正是 GC 長尾的成因**。鎖死這條等於結構性移除大半個 R1 |
| bypass bit-identical | `np.array_equal` 對照未處理輸入 | 章程 §15 的 KPI |
| latency 加總正確 | 對照各 processor 申報值 | R2 的基礎 |
| graph 未降級 | 檢查 degraded 旗標為假 | 確保安全網沒被誤觸發 |
| 數量級時間上限 | offline 模式的 **p50**，設 10 倍餘裕 | 只抓「有人在 callback 裡放了檔案 I/O 或 O(n²)」這種等級的退化。**不可比 max**，理由見 §7.5 |

第一條最重要：它把一個**統計性的、需要實體機器的效能問題**，
轉換成一個**確定性的、CI 就能守住的結構問題**。
時間上限那條刻意設寬——它不是效能門檻，是防呆。

### 7.3 擁有權與跨平台數字

架構期由維護者本人在 Windows 上建置並產生權威基線（S2）。
分軌期之後 Mac 開發者也會有 Core Audio 的數字，兩邊可互相對照：
若長尾**只出現在單一平台**，那就不是 Python GIL/GC 的問題，而是平台音訊層的問題——
這個區分很有價值。

但**不可拿 Core Audio 的數字去對章程 §1.1 的 WASAPI 基準**。
那組基準（48 kHz、60 ms deadline、2880 frames/callback）綁定特定機器與音訊子系統。

### 7.4 現況基線（已量測，VERIFIED）

S2 已完成。以下是 2026-08-22 在維護者的 Windows 機器上、
`--device` 模式（真實 `PlaybackDevice` + Qt 事件迴圈 + 60 Hz 分析器 tick、
靜音、4000 次回呼、丟棄前 200 次暖機）量到的數字：

| 指標 | 時間 | 佔 deadline | §6.3 上限 | |
|---|---|---|---|---|
| mean | 0.319 ms | 0.53% | ≤10% | OK |
| p50 | 0.237 ms | 0.39% | — | |
| p95 | 0.614 ms | 1.02% | — | |
| p99 | 1.881 ms | 3.13% | ≤25% | OK |
| p99.9 | 2.762 ms | 4.60% | — | |
| max | 3.570 ms | 5.95% | ≤50% | OK |

環境：48 kHz、每次回呼 2880 frames、deadline 60.00 ms。
量的是 `_process` 本身，**不含解碼**（解碼在 miniaudio 的產生器上游完成）。
這與章程 §1.1 的定義一致，兩邊數字可直接對照。

**三個結論：**

1. **R1 的長尾是真的。** p99 是 p50 的 8 倍，max 是 15 倍。
   Python 的 GIL／GC／OS 排程確實製造出明顯的重尾，這不是杞人憂天。
2. **但餘裕非常大。** p99 只吃掉 3.13% 的預算，離 25% 的上限還有約 13 ms。
   **目前沒有任何實測證據支持提早下沉 C++**，章程 §4 的 Measure Before
   Optimize 在這裡的答案是「不要」。Spatial P1 純 Python 實作看起來可行。
3. **記憶體壓力低。** 穩態下淨 block 增量 ≈ 0，而且量測窗內 gen0 回收
   一次都沒觸發 —— 目前的回呼幾乎不製造垃圾。這是很好的起點，
   也是 §7.2 那條檢查未來要守住的東西。

### 7.5 一個意外發現：offline 的尾巴比 device 還糟

規畫時假設 offline 模式「不準但堪用」。實測推翻了「堪用」的部分。

同一台機器、同一份程式碼跑五次 offline：

| | 五次的範圍 |
|---|---|
| p50 | 0.116 – 0.126 ms（**穩定**） |
| max | 0.577 – 16.112 ms（**28 倍差距**） |

而同一天的 device 模式 max 只有 3.570 ms。**「比較便宜」的量測模式產生了
比真實情況更糟的尾巴。**

原因：offline 用 `pump()` 全速推進，CPU 完全飽和，跟機器上其他東西搶；
device 模式被音訊時鐘節流，每 60 ms 之間 CPU 是閒的。

**這改變了 §7.2 的第五條檢查**：CI 的時間 tripwire 要比 **p50**，不能比 max。
在專用實體機上尾巴都能差 28 倍，共用的 CI runner 只會更糟。

這件事也把「效能數字不上 CI」從一個謹慎的判斷變成有實測支撐的結論。

同時要記錄一個章程沒講的權衡：60 ms 的 deadline 來自
[src/aurora/audio/engine.py](src/aurora/audio/engine.py) 的 `_BUFFER_MSEC`，
那是為了壓低視覺化延遲所選的值，**不是硬性上限**。
若 benchmark 結果吃緊，加大 buffer 換 headroom 是選項之一——
代價是視覺化延遲與（未來的）A/V sync 餘裕。

---

## 8. macOS 的完成定義

開發者 2 有實機，所以這一軌可以做到 **VERIFIED**，不需要延後清單。

### 8.1 CI 自動化（每個 PR）

- macOS runner 上 `ruff` / `mypy` / `pytest -m "not audio"` 全綠
- `QT_QPA_PLATFORM=offscreen aurora --validate-qml` 通過

第二條的含金量比看起來高：它會實例化所有控制器（因此走過平台 adapter 的選擇路徑）
並載入全部 QML 與 import。但它**只證明載得起來，不證明畫面正確**。

### 8.2 實機驗證（MANUAL-VERIFICATION-REQUIRED，要附輸出或截圖）

- `uv run aurora` 開得起來、真的出聲
- 畫面、動效、著色器外觀正確（**Metal 後端，與 Windows 的 D3D11 是不同路徑**）
- Core Audio 裝置切換與取樣率對齊（`configure_output` 在 macOS 的行為）
- `@pytest.mark.audio` 那 3 個測試在實機通過

### 8.3 macOS 專屬的已知地雷

開工前就該知道，不要現場踩：

- **APFS 的 Unicode 正規化**：macOS 檔名走 NFD，Windows 走 NFC。
  音樂庫的 cache key 是「路徑 + mtime + 大小」（見 ARCHITECTURE.md 的效能不變量），
  跨平台共用設定檔時同一個檔案可能算出不同的 key。
  中文字大多不受影響，但帶變音符號的西文檔名會。
- **非 ASCII 路徑在 macOS 不是問題**：`sys.getfilesystemencoding()` 在 macOS 是 UTF-8，
  `decode_file` 的坑不存在。但 `stream_file` 這條不變量**仍然要維持**——
  它是為 Windows 存在的，不能因為 macOS 沒事就放寬。
- **`app_data_dir()`**：macOS 應為 `~/Library/Application Support/Aurora`。
- **檔案關聯**：macOS 靠 `Info.plist` 的 `CFBundleDocumentTypes`，不是登錄檔。
  本階段不打包，所以 `register_file_types()` 在 macOS 直接回 `False` 即可，不要硬做。

---

## 9. 粗估時程與 Mac 開發者的加入點

以下是**粗估，不是承諾**（沿用章程 §13 對 target window 的措辭）。
任何一項只有在前一項的證據充足時才進下一步。

| 階段 | 項目 | 粗估 |
|---|---|---|
| 架構期 | S1 CI | ~0.5 週 |
| 架構期 | S2 benchmark + 基線數字 | ~0.5 週 |
| 架構期 | S3a `EndpointSnapshot` 搬家 | ~0.5 週 |
| 架構期 | S3b 平台縫 | ~0.5 週 |
| 架構期 | S4 DSP graph 縫 + 安全網 | ~1 週 |
| 分軌期 A | A1 Aligned A/B | ~0.5 週 |
| 分軌期 A | A2 EQ 全套 | ~2 週 |
| 分軌期 A | A3 Spatial P1 | ~2–3 週 |
| 分軌期 B | B1–B4 macOS | ~1.5 週 |

**關鍵時點：S3b 完成 = Mac 開發者可以開工的最早時間。**

若希望他更早進場，唯一能提前的做法是把 S3a/S3b 插到 S2 之前，
代價是 benchmark 基線晚幾天拿到、S4 的設計輸入延後。這個取捨由維護者屆時決定。

---

### 9.1 架構期實作紀錄（S1–S3b 已完成，VERIFIED）

CI 兩個 job 全綠：

| | Windows | macOS |
|---|---|---|
| ruff | 通過 | 通過 |
| mypy | 37 檔 | 32 檔（排除 `platform_win`，見下） |
| pytest `-m "not audio"` | 220 passed / 1 skipped | 195 passed / 1 skipped |
| QML 離屏載入 | 通過 | 通過 |

**macOS job 一上線就挖出四個既存缺陷**，全部屬於「以前沒有非 Windows CI
所以沒人會踩到」。記在這裡，因為接手時很容易重犯：

1. **`skipif` 不阻止 import。** `tests/test_endpoint.py` 原本有
   `pytestmark = skipif(sys.platform != "win32")`，但那只跳過**執行**；
   module-level 的 `platform_win` import 在**收集階段**照樣跑，於是
   `import winreg` 讓整個收集中斷。正解是
   `pytest.skip(..., allow_module_level=True)`。
   **新增 Windows 專屬測試檔時要沿用這個寫法。**
2. **不要依賴 ffmpeg 對副檔名的隱含編碼器。** 那個預設隨版本與建置漂移：
   macOS 上產出的 `.ogg` 讓 mutagen 丟 "no appropriate stream found"。
3. **Homebrew 的 ffmpeg 8.x 沒有 libvorbis。** 明寫 `-c:a libvorbis` 會得到
   "Unknown encoder"。改用 ffmpeg **內建**的 `vorbis`（需 `-strict -2`）——
   它不依賴外部函式庫，每個 build 都有。
4. **macOS 的 mypy 要排除 `platform_win`。** typeshed 把 `winreg` 與
   `ctypes.wintypes` 標為 win32 專屬，直接跑會冒出 41 個 `attr-defined`。
   用 `--exclude 'platform_win' --follow-imports=silent`；已用注入真錯的
   方式驗證這個組合仍抓得到其他檔案的問題，不是關掉檢查換綠燈。

另有一條與 runner 有關的教訓：查 runner 能力要看 **run log 裡的 Image 欄位**，
不要照 `windows-latest` / `macos-latest` 的字面猜。實際值是
`windows-2025-vs2026` 與 `macos-26-arm64`，都不是照字面推得到的那個。

### 9.2 S4（DSP graph 縫）已完成

`core/dsp_graph.py` 定義 `AudioProcessor` 契約與 `DspGraph` 級聯，
`AudioEngine._process` 變成 **Source Analyzer → DSP graph → User Volume**。
graph 預設是空的，此時訊號逐位元原樣通過。

五條規則各有機器判定得了的測試（`tests/test_dsp_graph.py`，18 條）。
**這些測試驗證過會真的失敗**：把 `process()` 的 try/except 拆掉之後，
6 條轉紅（含兩條引擎整合測試），還原後全綠。

空 graph 的成本實測 ≈ 0：p50 在 S4 前後都落在 0.116–0.132 ms 的同一區間，
gen0 回收依然未觸發。

兩件刻意**不**在 S4 做的事：

- **`take_degradation()` 還沒接到 UI。** 目前沒有任何處理器，降級不可能
  發生，接了也無法端到端驗證。這一條併入 A2（EQ）—— 屆時才有東西會壞。
- **`processing_latency_frames` 還沒被 `position` 補償。** 延遲恆為 0，
  補償寫了沒有東西可驗。屬性先存在，是為了讓歌詞對齊與未來的 A/V 同步
  有個一等公民的來源，而不是到時候再從各處拼湊。

### 9.3 A1／A2 的量測結果（VERIFIED）

**A2 的實作方式是量出來的，不是選出來的。** EQ 的教科書做法是 biquad 級聯，
但 IIR 在時間上遞迴、numpy 無法向量化。實測（2880 框、兩聲道、10 段）：

| 做法 | 平均 | 佔 60 ms deadline |
|---|---|---|
| Python biquad 迴圈 | 394 ms | **658%** |
| FFT overlap-add | 0.414 ms | 0.69% |

biquad 是整個預算的 6.5 倍——不是「有點慢」而是完全不可行。
所以走線性相位 FIR + FFT overlap-add，全程向量化，**連 native 都不必**。

`--device` 權威量測，十段全開 +12 dB（使用者做得到的最壞情況）：

| | 空 graph | EQ 全鏈 | §6.3 上限 |
|---|---|---|---|
| mean | 0.319 ms（0.53%） | 2.165 ms（3.61%） | ≤10% |
| p99 | 1.881 ms（3.13%） | 5.534 ms（9.22%） | ≤25% |
| max | 3.570 ms（5.95%） | 9.561 ms（15.94%） | ≤50% |

三項全部通過。**純 Python 的 EQ 是可行的**，這不再是推測。
**剩給 A3 的 p99 餘裕約 15 個百分點**，Spatial 也要量。

兩件要記錄的事：

- **gen0 回收從「不觸發」變成「每 667 次回呼一次」。** numpy 的 FFT API
  沒有 `out=` 參數，無法寫進預先配置的 buffer，所以 FFT 的配置是
  **不可避免**的——這正是 §4.2 契約寫「可避免的穩態配置」而不是「零配置」
  的原因。實測影響在預算內，暫不最佳化（章程 §4 的 Measure Before Optimize）。
- **自動餘裕讓「提升」變成相對的。** 拉高某段 9 dB 的同時 preamp 壓低 9 dB，
  所以絕對音量不變，變的是頻段之間的比例。調 EQ 不會突然變大聲、
  也不可能削波，代價是使用者聽到的是「其他頻段變小」。這是刻意的取捨。

**A1** 的 `estimate_latency_frames()` 現在被 A2 用來驗證 EQ 與限幅器申報的
延遲與實測相符——申報錯了會當場紅燈，而不是等到歌詞對不上才發現。

**A2 的 UI 已接上**（見 §9.5）。

### 9.4 A3 的量測結果，以及一個要正視的預算問題（VERIFIED）

Spatial P1 完成。`--device` 權威量測，全部開到最大
（EQ 十段 +12 dB、upmix amount=1.0、限幅器、輸出電表）：

| | 空 graph | EQ | Spatial | **EQ+Spatial** | §6.3 上限 |
|---|---|---|---|---|---|
| mean | 0.53% | 3.61% | — | **9.11%** | ≤10% |
| p99 | 3.13% | 9.22% | — | **20.59%** | ≤25% |
| max | 5.95% | 15.94% | — | **29.35%** | ≤50% |

（Spatial 單獨的 offline p50 是 5.65%，比 EQ 的 2.87% 貴一倍 ——
STFT 每次回呼跑約 5.6 個 hop、22 次 FFT，EQ 只有 2 次。）

**三項都過，但 mean 只剩 0.9 個百分點的餘裕。** 這比看起來嚴重：

- 最緊的是 **mean 而不是尾巴**，代表這是**穩態**成本高，不是偶爾爆一下。
  尾巴還有空間，穩態沒有。
- 這已經接近真實的最壞情況。EQ 的成本與增益值無關（FFT 工作量一樣），
  `amount=1.0` 也是正常設定 —— 不是刻意刁難出來的數字。
- **章程的下一步 P2 HRTF 會再加一組 STFT。照現在的做法一定會超過。**

因此有一條架構結論，是量出來而不是推論出來的：

> **P2 的 HRTF renderer 必須與 Spatial 共用同一個 STFT，不能自己再開一組。**

這正是章程 §4 說的「Implementation Fusion, Architecture Separation」——
`spatial.py` 已經把 `_build_scene` 與 `_render_stereo` 分開，
P2 要換的是後者，前者的 STFT 與相關性分析原地重用。
現在有數字證明這不只是漂亮的設計，而是**預算上的必要條件**。

其他要記錄的：

- **延遲是 `fft_size` 而不是 `fft_size − hop`。** 後者是 STFT 的演算法延遲，
  但輸出只能以 hop 為單位產生，而回呼大小是裝置決定的任意值。用模擬驗證過
  `fft − hop` 的預填在 block=64／2880 時會 underrun。多出來的那個 hop
  一樣聽得到，所以誠實申報進去。EQ 511 + Spatial 1024 = 1535 框（32 ms）。
- **完美重建是逐位元的。** 環繞關掉、寬度設 1 時，STFT 分析／合成的誤差
  在暖機一個 hop 之後**恰好是 0.0**。這條是其他所有測試的地基 ——
  沒有它就分不清量到的差異來自演算法還是重建誤差。
- 章程 §6.3 點名的四種失敗模式（人聲跑掉、低頻相位抵消、瞬態塗抹、
  單聲道塌陷）各有一條確定性測試。

**A3 的 UI 已接上**（見 §9.5）。

### 9.5 A2／A3 的 UI 接線（已完成）

`bridge/audiofx.py` 把三個處理器接到 QML，`qml/Aurora/EffectsPanel.qml`
是操作面板，設定存進 `Config`。面板走既有的 panel 系統（新增
`PanelName = "effects"` 與工具列按鈕），版面跟著 `SettingsPanel` 走。

三個值得記錄的設計決定：

1. **級聯「有人開啟才掛」。** EQ 與 Spatial 關閉時本來就會直接返回，
   但**限幅器不是免費的** —— 它有延遲線、每次回呼都要算增益包絡，
   還帶 64 框延遲。所以兩者都關時 graph 是空的，訊號逐位元原樣通過。
   全平的 EQ 也算「沒開」：只是好奇按了開關不該付出任何代價。
2. **設定檔是增益的唯一真相來源，處理器不是。** 停用時處理器會被填成
   全平（否則 graph 裡還是會跑 FFT）—— 如果 UI 從處理器讀值，滑桿就會
   歸零、使用者調好的曲線憑空消失。**這是實作時真的寫錯過的地方**，
   現在有測試守著。
3. **UI 要解釋自動餘裕。** 「拉高卻沒變大聲」違反直覺，不講的話使用者
   會以為滑桿壞了。所以面板直接顯示 headroom 與額外延遲。

降級回報走輪詢：音訊回呼不能發 Qt signal，所以 `AudioFxController.poll()`
由 `PlayerController._tick()` 每幀呼叫，把旗標撈回主執行緒 ——
與 `AudioEngine.take_finished` 同一個模式。

**面板外觀屬於 MANUAL-VERIFICATION-REQUIRED。** `--validate-qml` 只證明
載得起來，不證明畫面正確（見 `src/aurora/qml/AGENTS.md`）。

### 9.6 依權威資料修正 Spatial P1（VERIFIED）

實機試聽回報「中段差距太小、有種沒打開的感覺」之後，去查了文獻，
結果不只解決那一項，還挖出兩個**只有讀資料才會發現**的缺陷。
四項修正全部由量測驗證：

| 性質 | 修正前 | 現在 |
|---|---|---|
| 真實混音加寬 | 1.00x（幾乎無效果） | **1.21x** |
| 硬左偏樂器洩漏到另一聲道 | **0.395** | **0.000** |
| 滑桿 50% 的實際進度 | 25.8% | **47%** |
| 低頻 side 被推高 | 1.09x | **1.00x** |
| 人聲置中 / 音量變化 | — | 1.000 / +0.17 dB |

**一、環繞路徑有一道多餘的閘門。** `side` 本身就是不相關成分，再乘
`(1 − centre_weight)` 等於平方衰減；實測那道閘門在真實素材上中位數只有
0.19，加上隨機相位是以功率相加，最後只換到 0.7% 的側能量。拿掉。

**二、乾濕比不是聽感線性。** 側能量是 √(1+g²)，直接讓 g = amount 的話
前半段幾乎是平的。改成先決定目標側能量再回推增益。

**三、只用 coherence 分不出「硬左偏樂器」與「環境音」。** 兩者的
coherence 都是 0（實測 0.000 對 0.006），結果硬左偏的樂器有 39.5% 能量
漏進原本靜音的另一聲道 —— 定位被抹散。
Avendaño 與 Jot 的 upmix 框架同時使用 **inter-channel coherence 與
panning index**，兩者缺一不可。panning index 可由已有的量推出，不必多做
FFT：`Δ = 2·Re(M·conj(S)) / (|M|²+|S|²)`。三個量都必須時間平滑 ——
未平滑時真環境音的 |Δ| 是 0.497，平滑後掉到 0.168，與硬左偏的 1.000
差距變成 6 倍。

這與章程 §1.3 從 Sennheiser 學到的「**mix intent preservation**」是同一件事：
混音師把樂器擺在左邊是有意圖的，處理器不該把它搬走。

**四、去相關要做 high-pass。** 內部研究文件明確建議「再做適度 high-pass，
避免低頻 phase chaos」。實測未加時 <200 Hz 的 side 能量被推高 1.09 倍；
加上 raised-cosine 護欄後降到 1.00x，而全頻加寬完全沒有損失。

順帶釐清一件事：**單聲道相容性由 M/S 結構本身保證**，不需要額外處理。
折單聲道拿到的是 mid，而環繞只動 side，`out_mid` 從頭到尾沒被碰過。

#### 測試盲點

這一輪連續兩次遇到同一類問題：**弱斷言讓真實缺陷通過**。

- 加寬測試用的是完全不相關的素材，那剛好繞過閘門，所以它一路是綠的，
  而真實音樂上效果幾乎是零。
- 乾濕比測試只斷言 `off < half < full`，而 5.4%/25.8%/58.2% 完全滿足遞增。

兩條都改成斷言**倍率與比例**而不是方向。教訓寫在這裡：
**只看方向的斷言抓不到「效果小到聽不出來」與「刻度不成比例」。**

### 9.7 P1.1：距離機制（D/R 控制）

實機回報「太近沒有拉遠、定位有點擠、0→100% 沒有質變」。三個症狀有三個
不同成因，其中第一個可以**直接從程式碼證明**：

```
centre + front_mid  ==  mid*c + mid*(1-c)  ==  mid
dry_mid*(1-a) + wet_mid*a  ==  mid
```

**直達聲在任何 amount 下都是恆等的。** 實測 D/R 從 0 到 100% 只變
−0.62 dB，而人耳判斷距離需要數 dB —— 所以「拉遠」在機制上就不可能發生，
再怎麼調參數都沒用。原本的滑桿實際上是「側向加寬量」而不是「距離量」。

加入三段式距離機制：壓低**置中的**直達成分（擴散成分不動，D/R 才會真的
變）→ 環繞相對增益 → 全域響度補償。補償對 mid 與 side **等量**施加，
所以總響度回到原本、D/R 比保留 —— 不補的話使用者會把「變小聲」誤認成
「變遠」。

實測 depth 軸（真實 Dolby Atmos 素材）：

| amount | 25% | 50% | 75% | 100% |
|---|---|---|---|---|
| Atmos D/R | −0.63 | −1.61 | −2.91 | **−4.64 dB** |
| Orchestral D/R | −0.84 | −1.93 | −3.29 | **−4.94 dB** |

音量偏差 ≤0.42 dB（A/B 門檻 0.5），低頻絕對能量只變 −0.22～−0.95 dB
（沒有變薄），人聲相關性 1.000、保留 96%，硬定位洩漏 0.000。

曲線用 `amount**0.45` 而不是 `amount`：D/R 的分子與分母同時在變，
直接用 amount 會得到凸曲線（50% 只走完 27%）。指數把線性度誤差從 23%
壓到 15%；無法完全線性是兩個機制交互作用的結果。

#### 又一次「指標量錯東西」

加入距離機制後三條測試同時紅燈，成因**不是程式錯，是測試指標被污染**：

- 絕對 side 能量被全域補償增益帶著跑 → 改用 `side/mid` 比值。
- 但 `side/mid` 同時被加寬（拉高 side）與距離（壓低 mid）影響，
  **一個指標量兩個軸** → 驗加寬時把距離關掉（`depth_db = 0`），
  每條測試只隔離一個機制。
- 低頻測試的殘差 1.049x 全部來自 STFT 暖機，跳過一個 hop 後是 0.995x。

順帶抓到一個真回歸：環繞量從 1.0 拉到 1.4 之後，護欄淡入區漏出來的量
變大，低頻推高回到 1.09x。護欄從 220 Hz 提到 300 Hz 後回到 0.995x，
而 500–2 kHz 的加寬完全沒有損失。

**仍未解決**：「定位擠」需要 re-panning（風險較高，需要 object stability），
「質變」需要 P2 HRTF 的頭外化 —— P1 的 Basic Stereo Renderer 設計上做不到。

### 9.8 P1.2：早期反射，以及一個必須正視的預算超標

#### 做了什麼

`core/reflections.py`：兩個離散抽頭（11 ms / 23 ms）、交叉餵送、帶通、
**沒有回授**。順序是 `EQ → Spatial → EarlyReflections → Limiter → Meter`
—— 反射要對**已經被拉遠的**訊號作用，順序反過來空間線索會互相矛盾。

**延遲為 0。** 直達聲原樣通過，反射是加在後面的，所以這一級可以白拿。

「不可以長出殘響尾巴」有專門的測試守著。那是設計意圖，而意圖沒有測試
就會被「順手加個回授讓它更有空間感」毀掉，且沒有任何自動檢查會反對。

#### 預算超標（必須正視，不能靜默上線）

`--device` 全鏈最大設定（EQ 十段 +12 dB + Spatial 100% + 反射 100%）：

| | 加反射前 | 加反射後 | 視窗改 2048 後 | §6.3 上限 |
|---|---|---|---|---|
| mean | 9.11% | 15.65% | **12.49%** | ≤10% ❌ |
| p99 | 20.59% | 37.17% | **27.68%** | ≤25% ❌ |
| max | 29.35% | 51.73% | 47.02% | ≤50% ✅ |

**mean 與 p99 仍然超標。** 這是最壞情況（三個效果同時全開），但那是
使用者做得到的組合，不能當作不存在。

#### 這一輪踩到的坑，依序記錄

**一、33 抽頭的 FIR 做不出 300 Hz 高通。** 48 kHz 下 33 抽頭的頻率解析度
約 1455 Hz，實測 100 Hz 只被抑制到 0.79。這與 `eq.py` 的低頻解析度是同一
個物理限制，我在寫反射時沒有想到。257 抽頭抑制到 0.061，代價 0.66 ms。

**二、我對效能瓶頸猜錯了兩次。**

- 第一次猜「`np.concatenate` 每個 hop 增長陣列」是主因（那確實違反
  `dsp_graph` 契約規則 2）。改成預先配置後 —— **完全沒有變快**
  （4.240 → 4.451 ms，噪音範圍內）。改動本身是對的，但不是瓶頸。
- 第二次才去 profile。真相：FFT 只佔 0.96 ms，**3.1 ms 是每個 hop 上
  數十次 numpy 呼叫的累積開銷**。2880 框的回呼在 hop=512 下要跑 5.6 個
  hop，每個 hop 的固定開銷被乘了 5.6 倍。

  教訓寫在這裡：**效能問題要 profile，不要推理。** 我推理了兩次都錯，
  profile 一次就對了。

**三、唯一有效的槓桿是減少 hop 數，不是加快每個 hop。**

| fft/hop | 每回呼 hop | 成本 | 延遲 |
|---|---|---|---|
| 1024/512 | 5.6 | 4.435 ms | 21.3 ms |
| **2048/1024** | **2.8** | **2.514 ms** | **42.7 ms** |
| 4096/2048 | 1.4 | 2.618 ms | 85.3 ms |

4096 完全沒有進一步收益 —— FFT 成本的成長剛好抵銷 hop 數的減少，只剩
延遲變差。所以 2048 不是折衷，是唯一的合理點。

**視窗大小因此由效能決定，不是由頻率解析度決定。** 這與我原本寫在
`SPATIAL_FFT_SIZE` 註解裡的理由完全相反，註解已更正。

**四、加反射後三條 ViewModel 測試紅燈**，因為它們斷言級聯有 4 級。
改成斷言**組成型別**而不是數量 —— 數量對不上只會說「4 != 5」，
型別對不上會直接指出少了哪一級。

#### 現在的選項（需要決定）

1. **接受並記錄預算偏離** —— 最壞情況才超標，日常設定（單開 EQ 或單開
   空間）都在預算內。
2. **把早期反射預設關閉** —— 它是最新加的一級，拿掉可回到 mean ~10%。
3. **下沉 native** —— 章程 §4 說「沒有實測證據不要提早下沉 C++」。
   **現在有證據了**：profile 明確指出瓶頸是 Python/numpy 的逐次呼叫開銷，
   而那正是 native 能解決、純 Python 解決不了的東西。這是本專案第一次
   有數據支持這條路。

延遲代價也要一併考慮：`EQ 511 + Spatial 2048 + Limiter 64 = 2623 框
（54.6 ms）`。播放沒問題，但歌詞對齊需要用 `processing_latency_frames`
補償（機制已經存在，尚未接上）。

### 9.9 預算偏離的決定（已定案）

§9.8 列出的三個選項，維護者在實機試聽後選擇**選項一：接受並記錄**。

#### 實機聽感結論（MANUAL-VERIFICATION，已完成）

| 項目 | 結果 |
|---|---|
| 早期反射是否加分 | **是** |
| 響度補償是否造成抽吸感 | **沒有起伏** |

第二項先前一直標記為「無法用數字判定」—— 補償增益的標準差是 0.20，
那個數字本身無法告訴我聽起來如何。現在由人耳確認，這一項結案。

#### 決定內容

**接受**：全鏈最大設定（EQ 十段 +12 dB + Spatial 100% + 反射 100%）
超出章程 §6.3 的 mean 與 p99 預算。

**理由**：

1. **超標的是安全邊際，不是 deadline。** deadline 是 60 ms，實測用掉
   7.5 ms（12.49%），離真正來不及還有 87% 的空間。章程訂 10% 是為了給
   Python 的不可預測長尾留餘裕，不是效能天花板。
2. **只有三個效果同時全開才超標。** 單開 EQ 是 3.61%、單開 Spatial 約
   5.6%，都在預算內。
3. **反射經實機確認有加分**，所以「預設關閉」（選項二）不划算。
4. **native 化（選項三）留給 P2。** 那時會有兩個理由（預算 + 頭外化功能），
   一次投資解決兩件事，比現在只為追回 2.5 個百分點划算。

#### 這個決定何時要重新檢視

- **P2 HRTF 開始之前** —— 屆時預算會再次成為硬限制，而且已有 profile
  證據支持 native（§9.8）。
- **收到較慢機器上爆音的回報時** —— 本次量測只在維護者的 Windows 機器上
  做過，較慢的 CPU 餘裕會更少。
- **若單一效果或日常設定也超標** —— 那就不是這個決定的範圍，是新的回歸。

`tools/bench_callback.py` **刻意保留超標警告**，只在輸出裡指向本節。
把警告消音會讓未來真正的回歸一起被藏起來。

## 10. 交接：目前狀態

> 這一節原本是「Mac 開發者要開工」的清單。B1–B4 已完成（PR #11），
> 所以改寫成**當前狀態**，讓任何人接手時不必回頭讀整份歷史。

### 10.1 兩條軌道的完成度

| | 項目 | 狀態 |
|---|---|---|
| **架構期** | S1 CI ／ S2 benchmark ／ S3 platform 縫 ／ S4 DSP graph | 全部已合併 |
| **軌道 A** | A1 Aligned A/B ／ A2 EQ 全套 ／ A3 Spatial P1 | 已合併 |
| | UI（音效面板）、P1.1 距離機制、P1.2 早期反射 | PR #10 待合併 |
| **軌道 B** | B1 `platform/macos.py`（reduce motion + Core Audio 端點） | 已合併 |
| | B2 `app_data_dir()` 與快取鍵的 macOS 分支 | 已合併 |
| | B3 macOS CI job 綠 | 已達成 |
| | B4 實機驗證 | 由 Mac 開發者持有 |

`platform/macos.py` 目前實作了 `system_animations_enabled` 與
`query_endpoints`；`host_context` 與三個檔案關聯方法**刻意維持降級**，
理由寫在該檔的 docstring（`bt_codecs.toml` 只有 Windows 區段；
macOS 的檔案關聯靠 `Info.plist`，本階段不打包）。

### 10.2 預算偏離：已定案

全鏈最大設定超出章程 §6.3 的預算（mean 12.49% / 上限 10%）。
維護者在實機試聽後選擇**接受並記錄**，完整理由與重新檢視的時機見 §9.9。

**在 P2 HRTF 之前不要再往 DSP 鏈加東西** —— 餘裕已經用完，再加只會更深。

### 10.3 接下來的順序

依實機聽感回饋定下的順序，目前走到 ④：

1. ✅ D/R 距離機制（§9.7）
2. ✅ 實測 D/R + 響度匹配
3. ✅ 人工 A/B（實機聽過並接受）
4. ✅ 早期反射（§9.8）
5. ⬜ **P1 freeze** —— 預算決定已定案（§9.9），這一步現在沒有阻塞
6. ⬜ P2 HRTF —— 頭外化。**注意 §9.4 的約束：必須與 Spatial 共用同一個
   STFT**，不能自己再開一組（預算已經沒有空間）

「定位擠」仍未解決，需要 re-panning。風險比 D/R 高很多（vocal 漂移、
每個 STFT frame 位置變動），需要 object stability 與時間平滑，
建議排在 P1 freeze 之後單獨處理。

### 10.4 尚未驗證的項目

| 項目 | 狀態 |
|---|---|
| 音效面板外觀（等比例縮放、滑桿吸附） | 實機看過並修正過兩輪；最新一輪未再確認 |
| 響度補償是否造成抽吸感 | ✅ 實機確認**沒有起伏**（§9.9） |
| 早期反射的實際聽感 | ✅ 實機確認**有加分**（§9.9） |
| 打包版 | 最後一次 `build_exe.py --verify` 在加入 EQ／Spatial／反射之前 |

### 10.5 給接手者的三條教訓

這幾輪反覆踩到同一類問題，寫在這裡避免重蹈：

1. **效能問題要 profile，不要推理。** 本專案推理兩次都錯（詳見 §9.8），
   profile 一次就對。
2. **量測指標會被新機制污染。** 加入距離機制後三條測試同時紅燈，成因不是
   程式錯而是指標同時反映兩個軸。每條測試只隔離一個機制。
3. **合成訊號不能代表真實音樂。** 加寬效果在合成訊號上是綠的，在真實
   Dolby Atmos 素材上卻幾乎是零（§9.6）。斷言要用**倍率**而不是方向 ——
   只看「有變大」抓不到「小到聽不出來」。

## 11. 明確押後

| 項目 | 為什麼現在不做 |
|---|---|
| MediaClock | 沒有影片，`_frames_played` 夠用。但 S4 的 latency accounting 要留得下成長空間，不要寫死 |
| C++ / C ABI 下沉 | 等 S2 的數字指出 hotspot。章程 §4 的 Measure Before Optimize |
| 解除強制 stereo | 跨模組變更（engine、`mix_to_mono`、`OUTPUT_CHANNELS`、`AudioFormat`、endpoint 全動）。是 HRTF 的前置，不是 P1 的 |
| HRTF（P2） | 需要 HRTF 資料集，有授權問題（章程 §12 與 ADR-008） |
| 影片、4K/HDR、匯出 | 章程排在 PI-4 之後 |
| iOS / Android | 章程排在 PI-5 |

---

## 附錄：本文件的驗證

本文件的路徑引用由 [tests/test_docs_references.py](tests/test_docs_references.py) 自動驗證。
修改本文件後至少要跑：

```powershell
uv run pytest tests/test_docs_references.py
```

文中所有關於**未來效能**與 **macOS 行為**的敘述都是 **CODE-ONLY**——
它們來自讀程式碼的推理，不是實測。S2 完成後才會有第一組 VERIFIED 的效能數字。
