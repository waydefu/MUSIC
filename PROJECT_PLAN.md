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

**S4（DSP graph 縫）尚未開始**，它屬於軌道 A，不擋 macOS。

## 10. 分軌期的交接清單

**架構期已完成，這份清單現在可以直接交出去。**

1. **起點就是 `src/aurora/platform/macos.py`。** 它已經在，繼承
   `NullAdapter`，每個能力都降級但不會壞。檔案的 docstring 就是實作指南：
   逐一列出每個方法要對應哪個 macOS API、以及**哪些刻意不要做**
   （`host_context` 與檔案關聯在本階段維持降級，理由都寫在裡面）。
2. **參考範例**是 `platform/windows.py`，契約在 `platform/base.py`（§4.4）。
3. **一次覆寫一個方法，每補一個推一次 CI。** 沒覆寫的自動降級，不會壞。
   建議順序：`system_animations_enabled`（最簡單、且是無障礙硬性要求）
   → `query_endpoints` → 其餘。
4. **兩條硬限制**（也寫在 `macos.py` 的 docstring 裡）：
   macOS 專屬的 import 一律放方法內部，不可放模組層級
   （`tests/test_platform.py` 會在 Windows 上 import 這個檔案來驗契約）；
   失敗一律降級不拋例外。
5. **地雷清單**見 §8.3，**CI 已知的四個坑**見 §9.1。
6. **哪些檔案不該碰**：`platform_win/`（Windows 實作細節）、`audio/`、
   `core/dsp*`、`tools/bench_callback.py` —— 這些屬於軌道 A，同時改會衝突。
7. **AGENTS.md 的證據等級規則**：結論要標 VERIFIED / CODE-ONLY /
   MANUAL-VERIFICATION-REQUIRED / BLOCKED，不要寫「應該沒問題」。
   他有實機，所以 §8.2 那幾條可以做到 VERIFIED。

---

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
