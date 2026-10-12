# AURORA 音訊工程：200 個來源的擴大研究

**研究日期：2026-10-12**\
**範圍：** AURORA 的 R1 播放／DSP 安全、R2 聽測與故障診斷、R3 感知驗收、C/D 響度與品質估計、F/G HRTF／房間、I 耳機 EQ；另評估原建議的 11 個研究工具與 6 個 repo-specific Skills。[204][205]

## 摘要

- 彙整 **200 個不同來源記錄**：上一份整理的 68 個候選 GitHub 專案 + 子代理新增 66 個規範／論文／平台文件 + 本代理新增 66 個資料庫／研究／官方文件。已按網址正規化（保留有意義的 query，例如不同 AES e-library ID）檢查，200/200 唯一，沒有跨批重複網址；近似標題的兩組是不同資料庫／論文，不是重複引用。另有 14 個固定 commit 的 AURORA 內部基線檔案，單獨列出、不計入 200。
- 三批共 200 個來源頁均成功取得內容；這不代表每篇付費標準或論文都取得全文。部分只讀到官方摘要、資料頁或標準目錄。
- 前 68 個是承接使用者提供的清單：此輪檢查它們的 GitHub 頁可讀，不把先前對功能、授權、維護狀態的描述冒充成重新核實結果。後 132 個則逐頁擷取，並以來源頁／摘要核對用途與限制。
- **決策：不一次加入 11 個套件或建立 6 個 Skills。** 本 PR 依研究建議實作 R1-A／R1-B，以零新增依賴的確定性回歸測試驗收，再用現有 callback benchmark 做離線比較；量測和自然度不能靠 CI 綠燈代替。[204][205][202]

## 基線與範圍

本研究以 GitHub `main` 的 `da6dd5ac5212542e03d939d1a44b941a995bbdd8` 為基線；主線計畫與自然度計畫是當時下一步順序的依據。[204][205]\
研究開始時的本機狀態（terminal 驗證）：`codex/aurora-player-ui` @ `330c4d1cb14104ca66aba683f366ba07caf41df7`，相對當時 `origin/main` 落後 95、領先 0，工作樹乾淨；此後本 PR 從上述 main commit 建立新分支。

來源數是**可追溯資料索引**，不等同 200 次獨立實驗或 200 個彼此獨立的研究團隊。[69][70][150] 各版本標準、資料集、論文與實作文件可能有重疊；附錄保留身份與 URL，整合結論只依可讀到的範圍作限定推論。

## 主要發現

### 1. 先做 R1-A／R1-B，暫不加研究套件

主線 `PROJECT_PLAN.md`／`docs/AUDIO_NATURALNESS_PLAN.md` 的順序是先補播放安全與量測可信度，再往 R2/R3。[204][205]\
上一輪在 main 的程式快照上做的定向 probe 已重現：音量目標 `0.5778` 的第一個 4-sample stereo block 從舊增益開始，左右樣本的增益不相同；初始靜音時第一個輸出樣本仍非零。[210]\
DSP graph 在上游已改寫 buffer、下游拋例外時，雖進入 degraded 狀態，輸出仍是半處理 PCM。[211]\
這些是 R1-A/R1-B 的可測行為，不是需要先加新演算法庫的問題；研究基線（main）的測試缺口見 [test_engine.py](../tests/test_engine.py#L277-L296) 與 [test_dsp_graph.py](../tests/test_dsp_graph.py#L138-L150)。[212][213]

**R1-A 驗收建議：** 首次有效 PCM 直接採用當前目標增益；後續變更按音框平滑，左右聲道共用同一個 frame gain。[210][212]\
測試首次靜音、首次非 1.0 音量、短 block、連續調音量、load／seek／resume，以及 block size 邊界；不可只測 clamp 或「分析器在 mute 時仍讀到來源」。[212]

**R1-B 驗收建議：** 成功時提交完整處理結果；處理器或後續 stage 出錯時，呼叫端 buffer 必須逐位元保持原樣。[211][213]\
回歸測試要包含「第一級已修改、第二級才失敗」及「失敗 stage 自己先局部寫入」兩種情境，也要測容量上限、降級後不重試壞 stage、以及用全新／重置狀態安全恢復。[211][213]\
預先配置 scratch 是合理候選，但要量測其 copy 成本。[202][211]\
回退原 PCM **不等於** true-peak 安全；獨立的輸出安全 gate 仍要另驗。[71][204]

### 2. AURORA 已有自己的 callback benchmark，不要用微基準取代實機證據

`origin/main:tools/bench_callback.py:1-35,206-226,281-311,314-367,370-451` 明確區分兩種結果：`--offline` 用 `pump()`、不開裝置，只可用 p50；`--device` 才是實際 PlaybackDevice + Qt tick，p99/p99.9 必須在實體機量，且計時只涵蓋 `AudioEngine._process`、不含上游解碼。[202]\
預設蒐集數千次 callback，另看 allocated blocks 與 gen0 pressure。[202]\
這使 `pyperf`／`pytest-benchmark` 不能直接取代現有 device mode，也不適合把共用 CI runner 的 p99.9 當硬門檻。[50][51][202]

建議先用 deterministic test 固定正確性，再以同一台機器、相同音訊裝置、相同 buffer/chain 做 before/after；離線 p50 可作快速回歸，真實 callback 尾端要保留為手動實機 gate。[202]\
只在 benchmark 指出 Python 熱點後，才用 `py-spy` 等 profiler 定位。[53]

### 3. 11 個工具：分「現在／研究環境／真正需要時」而不是一次加進 dev/runtime

| 建議工具 | 建議 | 理由與界線 |
|---|---|---|
| `hypothesis` [49] | **暫緩，R1 確定性案例完成後再評估** | 可生成 block size／狀態組合，但不能代替兩個已知故障的具體回歸案例；若後續加入，只放 dev/test，不進 runtime。 |
| `pytest-benchmark` [50] | **現在不加** | 不是實機音訊回呼的 p99/p99.9 gate；與現有 benchmark 有功能重疊，測試計時也容易受環境噪音影響。 |
| `pyperf` [51] | **可留作離線 microbenchmark** | 只有要量純 Python／數值核心的差異時才有增益；不能替代 `tools/bench_callback.py --device`。 |
| `py-spy` [53] | **有量測疑點再用** | 取樣 profiler 是診斷工具，不是 callback deadline 或聲音品質驗收。 |
| `pyfar` [9] | **research extra，不列預設 dev** | 適合離線 IR／頻響分析；R1-A/B 不依賴它。 |
| `sofar` [7] | **只有新增 SOFA importer 才加** | 主線 [HRTF importer](../tools/import_hrtf.py#L1-L13) 明確選 WAV：讀 SOFA/HDF5 需要 `h5py`，目前 importer 用標準 `wave` 與 NumPy，避免把 HDF5 拉進執行包。[203] 現有 HRTF 匯入測試也已覆蓋方位、雙耳延遲、重取樣與錯誤回退。[214] |
| `pyloudnorm` [26] | **C/D 任務開始時再選** | 可作 BS.1770 類離線響度 oracle；LUFS 不是空間自然度。 |
| `pyroomacoustics` [11] | **G 的離線 oracle** | 用於 RIR／幾何對照，不要進播放器 callback/runtime。 |
| `slab` [14] | **人因研究環境** | 可協助聲音心理物理實驗，但不會讓主觀自然度成為 CI 指標。 |
| `libebur128` [25] | **僅在需要第二套獨立 oracle 時** | native library 有額外建置／ABI 面；先用一套參考實作比對，不必一開始同時維護兩套。 |
| `libmysofa` [6] | **僅在產品要直接讀 SOFA 時** | 目前資料流程是使用者下載 WAV → 轉小型 NPZ；不是即時 SOFA renderer。 |

另外，`Spatial_Audio_Framework`、Steam Audio、OpenAL Soft、Signalsmith、FFTConvolver 等適合當演算法／架構參考，不應只因成熟就整套加入 runtime。[1][4][41]

`pyfar`、`sofar`、`pyroomacoustics`、`slab` 可放獨立 research environment，避免 research 相依滲入 EXE。[7][9][11]

### 4. 聽測方法要跟問題配對；客觀分數不能代替自然度

ITU-R BS.1116 是小差異／小劣化的受控聽測方法；BS.1534（MUSHRA）面向中等品質評估；BS.1283 提醒如何選擇主觀評估方法。先定義要回答「是否可分辨」「哪個更偏好」「外化是否改善」「是否更薄／更硬」中的哪一題，再選方法，不要把 MUSHRA、ABX 或某個分數當通用自然度 oracle。[69][70][74]

R2 至少要把外化、定位、音色厚度／亮度、偏好、疲勞分開問；固定輸出響度、盲化順序、分開耳機開機／關機及 ANC/Ambient 條件，並記錄即時 profile/EQ。[74][183][184]\
foobar2000 ABX 是實用的雙盲比較器，AES ABX 論文提醒要用 signal detection theory 正確解讀正確率；軟體工具不會自動替 AURORA 的每一條鏈做等響或確認播放鏈沒有額外處理。[183][184]\
webMUSHRA 支援多種網頁聽測，但仍需要設計適合本問題的刺激與量表。[181]

BS.1770-5 定義節目響度與 true-peak 測量；BS.1387/PEAQ 是特定客觀品質估計，不是自然度量表。[71][72]\
PEAQ 的比較研究顯示成績會隨 speech/music 等內容類型變化；這些指標可以輔助確認 loudness/品質變化，不能判定空間外化、偏好或自然度。[182]

### 5. HRTF／room 資料豐富，但受試者、格式、授權與房間條件不同

HRTF 個體化綜述指出通用 HRTF 的外化／定位會有個體差異；SADIE II 的主觀研究甚至發現特定非個人化 HRTF 可能被更廣泛偏好，所以不可假設「個人化一定更好」。[150][200]\
用戶可盲聽挑選、可回退，比把某個 profile 宣稱為普遍最佳更有證據基礎。[150][200]

本輪核實到的代表性資料：HUTUBS 頁面列出 96 位受試者的 HRTF、3D 頭部網格、人體測量與耳機傳遞函數；ARI 說明含 250+ subjects、每人 1550 方位。[136][138]\
SONICOM 官網仍寫 200 subjects，但 2025 年更新論文說 measured subjects 已增到 300；這是資料版本差異，引用時應標版本，不能混成同一數字。[137][173]\
SADIE II 有 HRIR/BRIR、耳機 IR 與人體測量資料；RIEC 資料要求 SOFA API/MATLAB 或 Octave 等讀取流程。[135][139]

房間資料也要按任務選：BBC SBSBRIR 是 12 支喇叭、15 個聆聽位置並以 2° 頭轉角量測；360° BRIR 資料庫為 13 個接收位置、3.6° 角度間隔；3D3A 提供高解析平移／旋轉座標。[143][144][174]\
它們適合離線比較 renderer 幾何、方向與房間，不代表任一資料集等同 XM4 的個人聽感。[143][144][174]

資料授權不能只看論文或 GitHub README：SADIE II 頁面提供資料授權資訊；HUTUBS 使用 CC BY；FABIAN 文件標 CC BY-NC-SA。[135][136][149]\
OpenSLR28 為 Apache 2.0、16 kHz/16-bit 且偏 reverberant-speech corpus。[146]\
這些不應一律打進 AURORA 安裝包；先看原始資料條款、取樣率／通道／麥克風條件，再決定能否重散布或只做本機 oracle。[135][146][149]

### 6. 六個自訂 Skills：先不建六份平行規則

GitHub main 已追蹤 `AGENTS.md`、`CLAUDE.md` 和 `.claude/skills/release-preflight`、`verify-change`，但沒有追蹤 `.agents/skills/`。[206][207][208]\
六份 `aurora-audio-*` Skills 會重複規劃、驗收與 repo 指示，容易分叉。若 R1/R2 流程穩定後確實要讓不同代理重複執行，先做一份聚焦的 `aurora-naturalness-investigation` 工作流程，並讓它引用單一 canonical test matrix；其餘可等有真實重複需求再拆。[209][62][65]

## 建議順序

| 時序 | 工作 | 驗收方式 | 不做的事 |
|---|---|---|---|
| **本 PR** | 分開處理 R1-A 音量斜坡、R1-B graph 原子回退 | 針對重現故障加確定性測試；本機 pytest、ruff/mypy；離線 EQ p50 做 smoke comparison | 不新增 DSP 依賴；離線尾端數字不替代實機測量 [204][205][202] |
| **接續** | R1-C EQ snapshot、R1-D analyzer snapshot | race/concurrency 測試、stress/GC callback profile；引用 NumPy/Qt/Python 執行緒契約 | 不把 shared mutable NumPy buffer 當無鎖快照 |
| **R2** | 單因子診斷與受控聽測 | 預先定義指標、等響、隨機化、盲化；按問題選 BS.1116/MUSHRA/ABX；結果附受試條件 | 不用 LUFS、PEAQ 或 ViSQOL 直接給「自然度分數」 |
| **R3** | 100% 強度自然度／疲勞／偏好評估 | 真實耳機多輪聽測，分開自然度、偏好、外化、疲勞 | 不把一位使用者與一款耳機推廣成普遍最佳參數 |
| **F/G/I 後續** | HRTF、BRIR／房間、耳機 EQ 候選 | 先離線 oracle＋資料授權審查，再做 opt-in A/B；出現實際效益才考慮 native/runtime | 不把 research 庫直接塞進產品，不把模擬資料當實耳驗證 |

**本分支離線效能 smoke（不是實機驗收）：** 在 48 kHz、EQ chain、2880-frame blocks、`--callbacks 100` 下，研究基線與本分支各跑三次；p50 中位數分別為 2.607 ms 與 2.947 ms（本分支觀察到 +0.340 ms、約 +13%）。各次本分支 p50 為 2.601–3.363 ms，顯示離線執行有可見波動；這不足以定論裝置 callback 的延遲回歸。另以 10000-frame blocks 成功完成 offline smoke，確認自訂 block 先擴大 graph 工作區而非靜默降級。[202]

## 不能由這 200 個來源代替的驗證

外化、音色厚度、聽感自然度、偏好與疲勞仍需人在實際播放鏈上聽測；標準、repo、benchmark 或 CI 不能代替 WH-1000XM4 的開機／關機、ANC/Ambient、耳機輸出與個人 profile 條件。[160][162][204]\
R1-B 的輸出安全還要獨立驗 true peak；正確回退 PCM 不等於保證不削波。[71][211]

## 200 個來源索引

索引分成「前一份 68 個 repo 候選」「子代理新增 66 個規範／論文／平台文件」「本代理新增 66 個資料集／研究／實作文件」。每個 ID 可在文中引用；完整可點連結列於文件底部 Sources 區塊。[1][69][135]

### A. 前一份整理的 68 個 GitHub 候選（保留，不代表重新審核其技術主張）

| ID | 候選來源 | 原先映射階段 | 本輪狀態 |
|---:|---|---|---|
| [1] | `Spatial Audio Framework` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [2] | `SPARTA` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [3] | `IEM Plugin Suite` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [4] | `Steam Audio` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [5] | `OpenAL Soft` | F | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [6] | `libmysofa` | F | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [7] | `pyfar sofar` | F/I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [8] | `pyfar sofa conventions` | F/I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [9] | `pyfar` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [10] | `spaudiopy` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [11] | `pyroomacoustics` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [12] | `pyrato` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [13] | `spharpy` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [14] | `slab` | R2/R3 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [15] | `sound_field_analysis-py` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [16] | `ReTiSAR` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [17] | `VISR` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [18] | `s3a-decorrelation-toolbox` | R3 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [19] | `SoundScapeRenderer` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [20] | `Omniphony` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [21] | `Resonance Audio` | F/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [22] | `Impulcifer` | F/G/I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [23] | `ASH Toolset` | G/I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [24] | `AutoEq` | I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [25] | `libebur128` | C/D | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [26] | `pyloudnorm` | C/D | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [27] | `MoSQITo` | C/D/R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [28] | `ViSQOL` | R2/C/D | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [29] | `mir_eval` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [30] | `auraloss` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [31] | `Essentia` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [32] | `aubio` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [33] | `librosa` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [34] | `pedalboard` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [35] | `python-soundfile` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [36] | `python-sounddevice` | R1-B | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [37] | `pyminiaudio` | R1-B | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [38] | `PortAudio` | R1-B | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [39] | `soxr` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [40] | `libsamplerate` | R2 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [41] | `FFTConvolver` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [42] | `Signalsmith dsp` | G/R1-B | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [43] | `Signalsmith basics` | G/R1-B | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [44] | `PFFFT` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [45] | `JUCE` | R1-B/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [46] | `CamillaDSP` | R1-B/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [47] | `KFR` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [48] | `FFTW` | G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [49] | `Hypothesis` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [50] | `pytest-benchmark` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [51] | `pyperf` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [52] | `Scalene` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [53] | `py-spy` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [54] | `Memray` | R1 | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [55] | `pybind11` | R1/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [56] | `nanobind` | R1/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [57] | `cibuildwheel` | R1/G | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [58] | `Open-Unmix` | I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [59] | `Spleeter` | I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [60] | `Demucs` | I | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [61] | `OpenAI plugins` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [62] | `Agent Skills spec` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [63] | `Anthropic skills` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [64] | `Vercel agent skills` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [65] | `Trail of Bits skills` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [66] | `Trail of Bits curated skills` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [67] | `Superpowers developing for Claude Code` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |
| [68] | `JayRHa AgentSkills` | skills | GitHub 頁面可取；用途／授權／活躍度沿用前份整理，未逐項重新核實 |

### B. 子代理新增的 66 個規範、論文與平台文件

| ID | 來源標籤（頁面標題列於 Sources） | 子代理整理重點／限制 |
|---:|---|---|
| [69] | `ITU-R-BS.1116-3` | Rec, 2015, *Methods for the subjective assessment of small impairments*: designed for differences that need tightly controlled listening and statistical analysis; R2/R3. Too demanding for… |
| [70] | `ITU-R-BS.1534-3` | Rec, 2015, *Method for the subjective assessment of intermediate quality*: defines MUSHRA, using multiple stimuli, a hidden reference and anchors; R2/R3. Not the small-impairment protocol;… |
| [71] | `ITU-R-BS.1770-5` | Rec, 2023, *Algorithms to measure audio programme loudness and true-peak audio level*: specifies K-weighting, channel-weighted loudness, gating and true-peak measurement; C/D. Broadcast… |
| [72] | `ITU-R-BS.1387-2` | Rec, 2023, *Method for objective measurements of perceived audio quality*: specifies an objective method for a device under test, including low-bit-rate codecs; R2/C/D. It does not… |
| [73] | `ITU-R-BS.1284-2` | Rec, 2019, *General methods for the subjective assessment of sound quality*: covers assessment with or without a reference; R2/R3. It is a method framework, not an automated test; use to… |
| [74] | `ITU-R-BS.1283-2` | Rec, 2019, *Guidance for selecting ITU-R subjective-assessment Recommendations*: helps select a suitable method for the question; R2/R3. It gives guidance, not an implementation recipe;… |
| [75] | `ITU-R-BS.775-4` | Rec, 2022, *Multichannel stereophonic sound system*: specifies a multichannel reproduction system; F/G. Its scope is not ordinary headphone stereo; defer unless AURORA targets multichannel… |
| [76] | `ITU-R-BS.2051-3` | Rec, 2022, *Advanced sound system for programme production*: covers configurations that can support channel-, object- or scene-based systems; F/G. Production-system scope is broader than a… |
| [77] | `EBU-R128-v5` | EBU Rec, 2023, *Loudness normalisation and permitted maximum level*: defines broadcast programme-loudness and maximum-level recommendations; C/D. Broadcast targets are not universal… |
| [78] | `EBU-Tech-3341-v4` | EBU technical document, 2023, *Loudness metering: “EBU Mode”*: supplies meter specifications and conformance test material; C/D. Meter compliance is not EQ or naturalness validation;… |
| [79] | `EBU-Tech-3342-v3` | EBU technical document, 2023, *Loudness Range*: defines LRA using gated loudness-level percentiles; C/D. LRA is a programme statistic, not a compression recommendation; keep any use… |
| [80] | `EBU-Tech-3343` | EBU technical document, first published 2011, *Guidelines for Production of Programmes in Accordance with EBU R 128*: gives production practices for the recommendation; C/D.… |
| [81] | `EBU-Tech-3344-v2.1` | EBU technical document, 2016, *Guidelines for Distribution and Reproduction in accordance with EBU R 128*: addresses distribution and reproduction paths; C/D. It is broadcaster-chain… |
| [82] | `EBU-Tech-3276` | EBU technical document, 1998, *Listening conditions for the assessment of sound programme material*: specifies room and monitoring conditions for critical listening; R2. It is a… |
| [83] | `EBU-Tech-3276-S1` | EBU technical document, 2004, *Listening conditions—Supplement 1: Multichannel sound*: adds multichannel room, level and loudspeaker-layout conditions; F/G/R2. It targets multichannel… |
| [84] | `EBU-Tech-3286-S1` | EBU technical document, 2000, *Assessment methods for subjective evaluation of sound programme material—Multichannel*: sets out a multichannel evaluation method; R2/R3. It is… |
| [85] | `ISO-226:2023` | Std, *Normal equal-loudness-level contours*: specifies equal-loudness levels for pure tones in a frontal free field, with data from 20 Hz to 12.5 kHz; C/D. Its stated listener and stimulus… |
| [86] | `ISO-532-1:2017` | Std, *Loudness—Part 1: Zwicker method*: includes stationary and time-varying loudness estimation; C. It specifies listening conditions and normal-hearing listeners; treat as an offline… |
| [87] | `ISO-532-2:2017` | Std, *Loudness—Part 2: Moore–Glasberg method*: specifies stationary monaural or binaural loudness estimation, including earphone presentation; C. It does not model all dynamic perception… |
| [88] | `ISO-3382-1:2009` | Std, *Room acoustic parameters—Part 1: Performance spaces*: specifies reverberation-time and other room-parameter measurements from impulse responses; G. It is a measurement procedure, not… |
| [89] | `ISO-3382-2:2008` | Std, *Room acoustic parameters—Part 2: Reverberation time in ordinary rooms*: specifies room measurement positions, procedure and reporting; G. It measures a room rather than proving… |
| [90] | `ISO-3382-3:2022` | Std, *Room acoustic parameters—Part 3: Open-plan offices*: specifies measurements in unoccupied open-plan offices; G. Its office-specific scope is a poor fit for home listening; no… |
| [91] | `IEC-60268-7:2025` | Std, *Sound system equipment—Part 7: Headphones and earphones*: applies to headphones, earphones, headsets and earsets; I. It characterizes equipment, not a preferred EQ target; use for… |
| [92] | `IEC-60318-1:2009` | Std, *Simulators of human head and ear—Part 1*: specifies an ear simulator used for headphone measurements; I. A simulator is not an individual ear; reserve for lab measurement rather than… |
| [93] | `IEC-60318-4:2010` | Std, *Occluded-ear simulator for insert earphones*: defines an insert-earphone measurement simulator over 100 Hz–10 kHz; I. It is insert-specific and frequency-limited; use only for the… |
| [94] | `IEC-60268-21:2018` | Std, *Acoustical (output-based) measurements*: defines acoustic-output measurement methods for transducers and sound systems; I. It needs measurement equipment and fixtures; useful for lab… |
| [95] | `IEC-60268-22:2020` | Std, *Electrical and mechanical measurements on transducers*: applies to transducers and, under stated conditions, some sound systems including headphones; I. It does not establish… |
| [96] | `ITU-T-P.57 (2021)` | Rec, *Artificial ears*: specifies artificial-ear devices for telephonometry; I. Telephone measurement fixtures are not individualized consumer headphone fits; consult only for compatible… |
| [97] | `ITU-T-P.58 (2023)` | Rec, *Head and torso simulator for telephonometry*: specifies HATS characteristics; I/F. A standardized dummy is not a user-specific HRTF; use only for controlled measurement. |
| [98] | `AES69-2020` | AES Std, *Spatial acoustic data file format*: standardizes exchange of spatial data including HRTFs and spatial room impulse responses; F/G/I. The standard is copyrighted and version… |
| [99] | `PMID:2926000` | Wightman & Kistler, JASA paper, 1989, *Headphone simulation of free-field listening conditions I*: describes transfer-function-based headphone simulation; F. It depends on individual… |
| [100] | `Wightman-Kistler-II-1989` | JASA paper, 1989, *…II: Psychophysical validation*: validates simulated free-field localization psychophysically and reports more front/back confusions and less-defined elevation than… |
| [101] | `CIPIC-2001` | Algazi et al., conference paper, *The CIPIC HRTF Database*: Release 1.0 contains 45 subjects’ impulse responses at 1,250 directions plus anthropometric measures; F. It is a finite database… |
| [102] | `MIT-TR-280-1994` | Gardner & Martin, technical report, *HRTF Measurements of a KEMAR Dummy-Head Microphone*: documents 710 positions and measurements including headphone responses; F/I. A mannequin cannot… |
| [103] | `Møller-HRTF-1995` | Møller et al., AES paper, *Head-related transfer functions of human subjects*: reports measurements from human subjects; F. Measurement conditions and ear-canal coupling matter; consult… |
| [104] | `DOI:10.1038/25526` | Kulkarni & Colburn, research paper, 1998, *Role of spectral detail in sound-source localization*: experimentally examines how HRTF spectral detail affects localization; F. Results are… |
| [105] | `PMID:8354753` | Wenzel et al., JASA paper, 1993, *Localization using nonindividualized head-related transfer functions*: tests localization with generic HRTFs and reports increased confusions relative to… |
| [106] | `Hartmann-Wittenberg-1996` | JASA paper, *On the externalization of sound images*: uses psychophysical comparison to study whether headphone-rendered images sound external; F/R2. Externalization is distinct from EQ or… |
| [107] | `IEEE-1048207` | Zotkin et al., conference paper, 2002, *Virtual audio system customization using visual matching of ear parameters*: proposes visual ear-parameter matching for customization; F/I. This is… |
| [108] | `DOI:10.1250/ast.27.340` | Iwaya, journal paper, 2006, *Individualization of HRTFs with tournament-style listening test*: introduces DOMISO and a listening-based HRTF individualization method; F. It requires manual… |
| [109] | `PMID:11885605` | Begault et al., research paper, 2001, *Direct comparison of head tracking, reverberation, and individualized HRTFs…*: varies those factors with headphone-delivered virtual speech and… |
| [110] | `DOI:10.3389/fnins.2014.00451` | Andéol et al., paper, 2015, *Perceptual factors contribute more than acoustical factors…*: compares listener perceptual and acoustic factors in virtual-source localization; F/R2. The… |
| [111] | `DOI:10.3389/fnins.2014.00370` | Romigh & Simpson, paper, 2014, *Do you hear where I hear?*: isolates individualized sound-localization cues in HRTFs; F/R2. Its cue analysis does not yield a universal HRTF recipe; use to… |
| [112] | `DOI:10.2196/17576` | Jenny & Reuter, paper, 2020, *Usability of Individualized HRTFs in Virtual Reality*: 39 participants rated five perceptual qualities across individualized and generic HRTFs; F/R2. VR and… |
| [113] | `AES-ELib-16768` | Olive et al., AES paper, 2013, *Listener Preferences for Different Headphone Target Response Curves*: two double-blind tests compared eight target curves on two headphone models; I/R3.… |
| [114] | `AES-ELib-17042` | Olive & Welti, AES paper, 2013, *Listener Preferences for In-Room Loudspeaker and Headphone Target Responses*: listeners on average preferred 2 dB more bass and treble for the in-room… |
| [115] | `AES-ELib-17940` | Olive & Welti, AES paper, 2015, *Factors That Influence Listeners’ Preferred Bass and Treble Levels in Headphones*: 249 listeners repeatedly adjusted bass/treble across three programmes;… |
| [116] | `AES-ELib-19436` | Olive et al., AES paper, 2018, *A Statistical Model that Predicts Listeners’ Preference Ratings of Around-Ear and On-Ear Headphones*: evaluates 31 models with 130 listeners using virtual… |
| [117] | `AES-ELib-4465` | Toole, AES paper, 1985, *Subjective Measurements of Loudspeaker Sound Quality and Listener Performance*: reports repeatable ratings under adequate experimental control and listener… |
| [118] | `EBU-R022` | EBU recommendation, 1999, *Listening conditions for the assessment of sound programme material*: directs critical stereo and multichannel assessment to EBU Tech 3276 conditions; R2. It… |
| [119] | `Allen-Berkley-1979` | JASA paper, *Image method for efficiently simulating small-room acoustics*: computes an impulse response between points in a rectangular room for convolution; G. The geometric model is… |
| [120] | `AES-ELib-849` | Schroeder, AES paper, 1962, *Natural Sounding Artificial Reverberation*: describes adjustable electronic reverberation and an “ambiophonic” method; G. Its historical subjective claim is… |
| [121] | `DOI:10.1121/1.1936895` | Schroeder, JASA paper, 1961, *Further Progress with Colorless Artificial Reverberation*: describes parallel comb filters and sufficient conditions for subjectively colorless reverberation;… |
| [122] | `JSTOR:3680280` | Moorer, Computer Music Journal paper, 1979, *About This Reverberation Business*: examines comb/all-pass structures and cautions that flat magnitude response alone does not ensure… |
| [123] | `DAFX-1999-Beltran` | conference paper, *Matlab Implementation of Reverberation Algorithms*: uses impulse, filter and phase responses plus listening to compare implementations; G. It is an offline MATLAB study,… |
| [124] | `DAFX-2007-Stewart-Sandler` | conference paper, *Statistical Measures of Early Reflections of Room Impulse Responses*: describes a gradual early-to-late transition and measures that need no prior room geometry or… |
| [125] | `MS-IAudioClient3-Period` | Microsoft Doc, live API reference: `GetSharedModeEnginePeriod` returns supported minimum, maximum and fundamental periods; R1-B. Windows/WASAPI-specific; use as a buffer-timing reference,… |
| [126] | `MS-IAudioClient3-Initialize` | Microsoft Doc, live API reference: shared-stream period must be within returned bounds and an integral multiple of the fundamental period; R1-B. WASAPI-specific; consult only if changing… |
| [127] | `MS-IAudioRenderClient-GetBuffer` | Microsoft Doc, live API reference: obtains a pointer to the next render-endpoint buffer packet; R1-B. The API contract does not itself establish callback safety; use only as a backend… |
| [128] | `Apple-AURenderCallback` | Apple Doc, live API reference: defines the callback used to supply or process audio-unit render data; R1-B. Apple-specific and not a miniaudio contract; use only as a conceptual callback… |
| [129] | `Apple-Audio-Workgroups` | Apple Doc, live, *Understanding Audio Workgroups*: describes coordination of real-time audio threads; R1-B. Apple-only; do not add cross-platform code based on it. |
| [130] | `Apple-AU-Hosting-Guide` | Apple Doc, archived guide: describes hosting and connecting Audio Units; R1-B. It is an older iOS/AU-specific guide, not AURORA’s backend; use only as an architectural comparison. |
| [131] | `Android-AAudio` | Android NDK Doc, live: describes the AAudio low-latency API and callback model; R1-B. Android-only; callback concepts must be checked against AURORA’s actual miniaudio/Python path. |
| [132] | `Android-Avoid-PI` | AOSP Doc, live, *Avoiding Priority Inversion*: discusses avoiding blocking priority-inversion hazards in audio paths; R1-B. Android-specific guidance; apply the principle, not the platform… |
| [133] | `ALSA-PCM` | ALSA official Doc, live: describes PCM buffer/period operation and application/hardware pointers; R1-B. Linux-specific; useful for buffer concepts, not a Windows implementation target. |
| [134] | `ALSA-PCM-Direct` | ALSA official Doc, live: documents the mmap `begin`/`commit` access pattern; R1-B. Linux-specific and not proof of application-level allocation safety; consult only if a backend change… |

### C. 本代理新增的 66 個資料集、研究與實作來源

| ID | 來源 | 類型 | AURORA 階段 | 本輪定位 |
|---:|---|---|---|---|
| [135] | `SADIE II HRTF database` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [136] | `HUTUBS HRTF database` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [137] | `SONICOM HRTF dataset` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [138] | `ARI HRTF database` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [139] | `RIEC HRTF dataset` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [140] | `LISTEN HRTF database` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [141] | `RWTH Open-HRTF dataset` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [142] | `OpenAIR acoustic impulse-response library` | dataset | G | 離線 oracle／資料候選；用前先核對條件與授權 |
| [143] | `BBC SBSBRIR dataset` | dataset | G | 離線 oracle／資料候選；用前先核對條件與授權 |
| [144] | `360-degree BRIR database for 6DOF research` | dataset | G | 離線 oracle／資料候選；用前先核對條件與授權 |
| [145] | `Aachen Impulse Response Database` | dataset | G | 離線 oracle／資料候選；用前先核對條件與授權 |
| [146] | `OpenSLR Room Impulse Response and Noise Database (SLR28)` | dataset | G/R2 | 離線 oracle／資料候選；用前先核對條件與授權 |
| [147] | `ReverbDB real-room impulse response dataset` | dataset/paper | G/R2 | 離線 oracle／資料候選；用前先核對條件與授權 |
| [148] | `RealRIRs database-loader index` | software/data index | G/R2 | 離線 oracle／資料候選；用前先核對條件與授權 |
| [149] | `FABIAN HRTF database documentation` | dataset | F/I | 離線 oracle／資料候選；用前先核對條件與授權 |
| [150] | `HRTF Individualization: A Survey` | review paper | F/I/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [151] | `Individualizing HRTFs for Binaural Acoustic Applications` | research paper | F/I | 研究參考；受刺激、受試者與量測 setup 限定 |
| [152] | `Continuous HRTF representation based on hyperspherical harmonics` | research paper | F | 研究參考；受刺激、受試者與量測 setup 限定 |
| [153] | `Efficient representation of HRTFs in continuous space-frequency domains` | research paper | F | 研究參考；受刺激、受試者與量測 setup 限定 |
| [154] | `Magnitude-corrected and time-aligned HRTF interpolation` | research paper | F | 研究參考；受刺激、受試者與量測 setup 限定 |
| [155] | `Dynamic spectral cues and small head movements in sound localization` | research paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [156] | `On the ability of human listeners to distinguish between front and back` | research paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [157] | `On the variation of interaural time differences with frequency` | research paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [158] | `Across-channel interaural-level-difference processing demonstrates frequency dependence` | research paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [159] | `Auditory localization: a comprehensive practical review` | review paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [160] | `Sound Externalization: A Review of Recent Research` | review paper | F/G/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [161] | `The contribution of head movement to externalization and internalization of sounds` | research paper | F/G/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [162] | `Combined assessment of auditory distance perception and externalization` | research paper | R2/R3/G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [163] | `Effects of auditory distance cues and reverberation on spatial perception and listening strategies` | research paper/preprint | R2/G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [164] | `Effects of early and late reflections on intelligibility in reverberant rooms` | research paper | G/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [165] | `Impact thresholds of BRIR parameters on perceptual reverberation` | research paper | G/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [166] | `The impact of early reflections on binaural cues` | research paper | G/F | 研究參考；受刺激、受試者與量測 setup 限定 |
| [167] | `Auditory discrimination of early reflections in virtual rooms` | conference paper | G/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [168] | `Externalization of static virtual sources using HRTFs and parametric IIR plus room simulation` | conference paper | F/G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [169] | `Six Degrees of Auditory Spatial Separation` | research paper | R2/F | 研究參考；受刺激、受試者與量測 setup 限定 |
| [170] | `HRTF individualization based on anthropometric measurements` | research paper | F/I | 研究參考；受刺激、受試者與量測 setup 限定 |
| [171] | `HRTF individualization using anthropometric features and latent representation` | research paper/preprint | F/I | 研究參考；受刺激、受試者與量測 setup 限定 |
| [172] | `Towards HRTF personalization using denoising diffusion models` | research paper/preprint | F/I | 研究參考；受刺激、受試者與量測 setup 限定 |
| [173] | `The Extended SONICOM HRTF Dataset and Spatial Audio Metrics Toolbox` | research paper/data paper | F/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [174] | `The 3D3A Lab Binaural Room Impulse Response Dataset` | dataset | G/R2 | 離線 oracle／資料候選；用前先核對條件與授權 |
| [175] | `SofaMyRoom: shoebox room simulator for BRIR dataset generation` | research paper/software | G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [176] | `Efficient models for reverberation and distance rendering in computer music and virtual audio reality` | conference paper | G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [177] | `Efficient optimization of feedback delay networks for smooth reverberation` | research paper/preprint | G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [178] | `Modal decomposition of feedback delay networks` | research paper | G | 研究參考；受刺激、受試者與量測 setup 限定 |
| [179] | `Partitioned convolution algorithms for real-time auralization` | thesis/research | G/R1-B | 研究參考；受刺激、受試者與量測 setup 限定 |
| [180] | `Time-Variant Overlap-Add in Partitions` | research paper/preprint | G/R1-B | 研究參考；受刺激、受試者與量測 setup 限定 |
| [181] | `webMUSHRA: A Comprehensive Framework for Web-based Listening Tests` | research paper/software | R2/R3 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [182] | `Can we still use PEAQ? Performance analysis of the ITU perceived-audio-quality standard` | research paper | R2/C/D | 研究參考；受刺激、受試者與量測 setup 限定 |
| [183] | `Statistical Analysis of ABX Results Using Signal Detection Theory` | AES conference paper | R2/R3 | 研究參考；受刺激、受試者與量測 setup 限定 |
| [184] | `foobar2000 ABX Comparator` | software/tool | R2/R3 | 聽測／資料工具候選；不能代替人因驗收 |
| [185] | `miniaudio manual` | official library documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [186] | `Low Latency Audio - Windows drivers` | official platform documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [187] | `JACK Process Callback API` | official API documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [188] | `RtAudio callback API reference` | official API documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [189] | `Multimedia Class Scheduler Service` | official platform documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [190] | `XAudio2 callbacks` | official API documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [191] | `WASAPI shared-mode event-driven rendering` | official API documentation | R1-B | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [192] | `Python 3.11 threading documentation` | official language documentation | R1-C/R1-D | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [193] | `Python 3.11 C API: thread state and GIL` | official language documentation | R1-B/R1-C/R1-D | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [194] | `NumPy thread safety` | official library documentation | R1-C/R1-D | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [195] | `Qt 6 Threads and QObjects` | official framework documentation | R1-C/R1-D | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [196] | `Real-time audio programming 101: time waits for nothing` | engineering article | R1-B | 離線研究參考；非產品品質指標 |
| [197] | `MathWorks Parameter Smoother` | official DSP documentation | R1-A/R1-C | 平台／實作契約參考；不等同 AURORA 自身驗證 |
| [198] | `W3C Web Audio API AudioParam automation` | standard specification | R1-A/R1-C | 離線研究參考；非產品品質指標 |
| [199] | `Cross Fade of Digital Audio Streams` | technical white paper | R1-A | 研究參考；受刺激、受試者與量測 setup 限定 |
| [200] | `A Perceptual Evaluation of Individual and Non-Individual HRTFs: the SADIE II case study` | research paper | F/I/R2 | 研究參考；受刺激、受試者與量測 setup 限定 |

### D. 主線程式／規劃基線（14 個，不計入 200 個外部研究來源）

| ID | 檔案 | 用途 |
|---:|---|---|
| [201] | `pyproject.toml` | 固定 commit 的主線文件／程式核對來源 |
| [202] | `tools/bench_callback.py` | 固定 commit 的主線文件／程式核對來源 |
| [203] | `tools/import_hrtf.py` | 固定 commit 的主線文件／程式核對來源 |
| [204] | `docs/AUDIO_NATURALNESS_PLAN.md` | 固定 commit 的主線文件／程式核對來源 |
| [205] | `PROJECT_PLAN.md` | 固定 commit 的主線文件／程式核對來源 |
| [206] | `AGENTS.md` | 固定 commit 的主線文件／程式核對來源 |
| [207] | `CLAUDE.md` | 固定 commit 的主線文件／程式核對來源 |
| [208] | `.claude/skills/release-preflight/SKILL.md` | 固定 commit 的主線文件／程式核對來源 |
| [209] | `.claude/skills/verify-change/SKILL.md` | 固定 commit 的主線文件／程式核對來源 |
| [210] | `src/aurora/audio/engine.py` | 固定 commit 的主線文件／程式核對來源 |
| [211] | `src/aurora/core/dsp_graph.py` | 固定 commit 的主線文件／程式核對來源 |
| [212] | `tests/test_engine.py` | 固定 commit 的主線文件／程式核對來源 |
| [213] | `tests/test_dsp_graph.py` | 固定 commit 的主線文件／程式核對來源 |
| [214] | `tests/test_hrtf_data.py` | 固定 commit 的主線文件／程式核對來源 |

## Sources

[1] https://github.com/leomccormack/Spatial_Audio_Framework — GitHub - leomccormack/Spatial_Audio_Framework: A cross-platform framework for developing spatial audio algorithms and software in C/C++ · GitHub
[2] https://github.com/leomccormack/SPARTA — GitHub - leomccormack/SPARTA: A collection of spatial audio plug-ins developed using JUCE and the Spatial_Audio_Framework · GitHub
[3] https://github.com/tu-studio/IEMPluginSuite — GitHub - tu-studio/IEMPluginSuite · GitHub
[4] https://github.com/ValveSoftware/steam-audio — GitHub - ValveSoftware/steam-audio: Steam Audio · GitHub
[5] https://github.com/kcat/openal-soft — GitHub - kcat/openal-soft: OpenAL Soft is a software implementation of the OpenAL 3D audio API. · GitHub
[6] https://github.com/hoene/libmysofa — GitHub - hoene/libmysofa: Reader for AES SOFA files to get better HRTFs · GitHub
[7] https://github.com/pyfar/sofar — GitHub - pyfar/sofar: maybe the most complete python package for SOFA files so far · GitHub
[8] https://github.com/pyfar/sofa_conventions — GitHub - pyfar/sofa_conventions: machine readable implementation of SOFA conventions · GitHub
[9] https://github.com/pyfar/pyfar — GitHub - pyfar/pyfar: python package for acoustics research · GitHub
[10] https://github.com/chris-hld/spaudiopy — GitHub - chris-hld/spaudiopy: Spatial Audio Python Package · GitHub
[11] https://github.com/LCAV/pyroomacoustics — GitHub - LCAV/pyroomacoustics: Pyroomacoustics is a package for audio signal processing for indoor applications. It was developed as a fast prototyping platform for beamforming algorithms in indoor scenarios. · GitHub
[12] https://github.com/pyfar/pyrato — GitHub - pyfar/pyrato: Python Room Acoustics Tools · GitHub
[13] https://github.com/pyfar/spharpy — GitHub - pyfar/spharpy: Spherical array processing in python. · GitHub
[14] https://github.com/DrMarc/slab — GitHub - DrMarc/slab: python classes for working with sounds and conducting psychoacoustic  experiments · GitHub
[15] https://github.com/AppliedAcousticsChalmers/sound_field_analysis-py — GitHub - AppliedAcousticsChalmers/sound_field_analysis-py: Analyze, visualize, and process sound field data recorded by spherical microphone arrays. · GitHub
[16] https://github.com/AppliedAcousticsChalmers/ReTiSAR — GitHub - AppliedAcousticsChalmers/ReTiSAR: Real-Time Spherical Array Renderer for binaural reproduction in Python · GitHub
[17] https://github.com/s3a-spatialaudio/VISR — GitHub - s3a-spatialaudio/VISR: Software framework for audio processing · GitHub
[18] https://github.com/s3a-spatialaudio/s3a-decorrelation-toolbox — GitHub - s3a-spatialaudio/s3a-decorrelation-toolbox: Python toolbox for decorrelating and upmixing audio signals. · GitHub
[19] https://github.com/SoundScapeRenderer/ssr — GitHub - SoundScapeRenderer/ssr: Main source code repository for the SoundScape Renderer · GitHub
[20] https://github.com/mgth/Omniphony — GitHub - mgth/Omniphony: Real-time spatial / object-based audio rendering engine (VBAP + binaural) for multichannel and 3D audio — speakers or headphones. · GitHub
[21] https://github.com/resonance-audio/resonance-audio — GitHub - resonance-audio/resonance-audio: Resonance Audio Source Code · GitHub
[22] https://github.com/jaakkopasanen/Impulcifer — GitHub - jaakkopasanen/Impulcifer: Measurement and processing of binaural impulse responses for personalized surround virtualization on headphones. · GitHub
[23] https://github.com/ShanonPearce/ASH-Toolset — GitHub - ShanonPearce/ASH-Toolset: A set of tools for headphone correction and binaural synthesis of spatial audio systems on headphones · GitHub
[24] https://github.com/jaakkopasanen/AutoEq — GitHub - jaakkopasanen/AutoEq: Automatic headphone equalization from frequency responses · GitHub
[25] https://github.com/jiixyj/libebur128 — GitHub - jiixyj/libebur128: A library implementing the EBU R128 loudness standard. · GitHub
[26] https://github.com/csteinmetz1/pyloudnorm — GitHub - csteinmetz1/pyloudnorm: Flexible audio loudness meter in Python with implementation of ITU-R BS.1770-4 loudness algorithm · GitHub
[27] https://github.com/Eomys/MoSQITo — GitHub - Eomys/MoSQITo: MoSQITo is a unified and modular development framework of key sound quality metrics favoring reproducible science and efficient shared scripting among engineers, teachers and researchers community. · GitHub
[28] https://github.com/google/visqol — GitHub - google/visqol: Perceptual Quality Estimator for speech and audio · GitHub
[29] https://github.com/mir-evaluation/mir_eval — GitHub - mir-evaluation/mir_eval: Evaluation functions for music/audio information retrieval/signal processing algorithms. · GitHub
[30] https://github.com/csteinmetz1/auraloss — GitHub - csteinmetz1/auraloss: Collection of audio-focused loss functions in PyTorch · GitHub
[31] https://github.com/MTG/essentia — GitHub - MTG/essentia: C++ library for audio and music analysis, description and synthesis, including Python bindings · GitHub
[32] https://github.com/aubio/aubio — GitHub - aubio/aubio: a library for audio and music analysis · GitHub
[33] https://github.com/librosa/librosa — GitHub - librosa/librosa: Python library for audio and music analysis · GitHub
[34] https://github.com/spotify/pedalboard — GitHub - spotify/pedalboard: 🎛 🔊 A Python library for audio. · GitHub
[35] https://github.com/bastibe/python-soundfile — GitHub - bastibe/python-soundfile: SoundFile is an audio library based on libsndfile, CFFI, and NumPy · GitHub
[36] https://github.com/spatialaudio/python-sounddevice — GitHub - spatialaudio/python-sounddevice: :sound: Play and Record Sound with Python :snake: · GitHub
[37] https://github.com/irmen/pyminiaudio — GitHub - irmen/pyminiaudio: python interface to the miniaudio audio playback, recording, decoding and conversion library · GitHub
[38] https://github.com/PortAudio/portaudio — GitHub - PortAudio/portaudio: PortAudio is a cross-platform, open-source C language library for real-time audio input and output. · GitHub
[39] https://github.com/chirlu/soxr — GitHub - chirlu/soxr: The SoX resampler library · GitHub
[40] https://github.com/libsndfile/libsamplerate — GitHub - libsndfile/libsamplerate: An audio Sample Rate Conversion library · GitHub
[41] https://github.com/HiFi-LoFi/FFTConvolver — GitHub - HiFi-LoFi/FFTConvolver: Audio convolution algorithm in C++ for real time audio processing · GitHub
[42] https://github.com/Signalsmith-Audio/dsp — GitHub - Signalsmith-Audio/dsp: GitHub mirror of Signalsmith Audio's C++ DSP support library · GitHub
[43] https://github.com/Signalsmith-Audio/basics — GitHub - Signalsmith-Audio/basics: A collection of basic effects, available as open-source (MIT) C++ classes. · GitHub
[44] https://github.com/marton78/pffft — GitHub - marton78/pffft: A fork of Julien Pommier's Pretty Fast FFT (PFFFT) library, with several additions · GitHub
[45] https://github.com/juce-framework/JUCE — GitHub - juce-framework/JUCE: JUCE is an open-source cross-platform C++ application framework for desktop and mobile applications, including VST, VST3, AU, AUv3, LV2 and AAX audio plug-ins. · GitHub
[46] https://github.com/HEnquist/camilladsp — GitHub - HEnquist/camilladsp: A flexible cross-platform IIR and FIR engine for crossovers, room correction etc. · GitHub
[47] https://github.com/kfrlib/kfr — GitHub - kfrlib/kfr: Fast, modern C++ DSP framework, FFT, Sample Rate Conversion, FIR/IIR/Biquad Filters (SSE, AVX, AVX-512, ARM NEON, RISC-V RVV) · GitHub
[48] https://github.com/FFTW/fftw3 — GitHub - FFTW/fftw3: DO NOT CHECK OUT THESE FILES FROM GITHUB UNLESS YOU KNOW WHAT YOU ARE DOING. (See below.) · GitHub
[49] https://github.com/HypothesisWorks/hypothesis — GitHub - HypothesisWorks/hypothesis: The property-based testing library for Python · GitHub
[50] https://github.com/ionelmc/pytest-benchmark — GitHub - ionelmc/pytest-benchmark: pytest fixture for benchmarking code · GitHub
[51] https://github.com/psf/pyperf — GitHub - psf/pyperf: Toolkit to run Python benchmarks · GitHub
[52] https://github.com/plasma-umass/scalene — GitHub - plasma-umass/scalene: Scalene: a high-performance, high-precision CPU, GPU, and memory profiler for Python with AI-powered optimization proposals · GitHub
[53] https://github.com/benfred/py-spy — GitHub - benfred/py-spy: Sampling profiler for Python programs · GitHub
[54] https://github.com/bloomberg/memray — GitHub - bloomberg/memray: Memray is a memory profiler for Python · GitHub
[55] https://github.com/pybind/pybind11 — GitHub - pybind/pybind11: Seamless operability between C++11 and Python · GitHub
[56] https://github.com/wjakob/nanobind — GitHub - wjakob/nanobind: nanobind: tiny and efficient C++/Python bindings · GitHub
[57] https://github.com/pypa/cibuildwheel — GitHub - pypa/cibuildwheel: 🎡 Build Python wheels for all the platforms with minimal configuration. · GitHub
[58] https://github.com/sigsep/open-unmix-pytorch — GitHub - sigsep/open-unmix-pytorch: Open-Unmix - Music Source Separation for PyTorch · GitHub
[59] https://github.com/deezer/spleeter — GitHub - deezer/spleeter: Deezer source separation library including pretrained models. · GitHub
[60] https://github.com/facebookresearch/demucs — GitHub - facebookresearch/demucs: Code for the paper Hybrid Spectrogram and Waveform Source Separation · GitHub
[61] https://github.com/openai/plugins — GitHub - openai/plugins: OpenAI Plugins · GitHub
[62] https://github.com/agentskills/agentskills — GitHub - agentskills/agentskills: Specification and documentation for Agent Skills · GitHub
[63] https://github.com/anthropics/skills — GitHub - anthropics/skills: Public repository for Agent Skills · GitHub
[64] https://github.com/vercel-labs/agent-skills — GitHub - vercel-labs/agent-skills: Vercel's official collection of agent skills · GitHub
[65] https://github.com/trailofbits/skills — GitHub - trailofbits/skills: Trail of Bits Claude Code skills for security research, vulnerability detection, and audit workflows · GitHub
[66] https://github.com/trailofbits/skills-curated — GitHub - trailofbits/skills-curated: Curated, community-vetted Claude Code plugin marketplace · GitHub
[67] https://github.com/obra/superpowers-developing-for-claude-code — GitHub - obra/superpowers-developing-for-claude-code · GitHub
[68] https://github.com/JayRHa/AgentSkills — GitHub - JayRHa/AgentSkills: The largest community-driven library of Agent Skills (SKILL.md + scripts/references/examples) for Claude, Codex, Gemini CLI, Cursor and friends. · GitHub
[69] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1116-3-201502-I!!PDF-E.pdf — RECOMMENDATION ITU-R BS.1116-3 – Methods for the subjective assessment of small impairments in audio systems
[70] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1534-3-201510-I!!PDF-E.pdf — Template BR_Rec_2005.dot
[71] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1770-5-202311-I!!PDF-E.pdf — Recommendation ITU-R BS.1770-5 (11/2023) Algorithms to measure audio programme loudness and true-peak audio level
[72] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1387-2-202305-I!!PDF-E.pdf — RECOMMENDATION  ITU-R  BS.1387-2 - Method for objective measurements of perceived audio quality
[73] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1284-2-201901-I!!PDF-E.pdf — General methods for the subjective assessment of sound quality
[74] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1283-2-201910-I!!PDF-E.pdf — RECOMMENDATION  ITU-R  BS.2126-0 - Methods for the subjective assessment of sound systems with accompanying picture
[75] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.775-4-202212-I!!PDF-E.pdf — RECOMMENDATION  ITU-R  BS.775-4* - Multichannel stereophonic sound system with and without accompanying picture
[76] https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.2051-3-202205-I!!PDF-E.pdf — RECOMMENDATION  ITU-R  BS.2051-3* - Advanced sound system for programme production
[77] https://tech.ebu.ch/docs/r/r128.pdf — Loudness normalisation and permitted maximum level of audio signals
[78] https://tech.ebu.ch/docs/tech/tech3341.pdf — 'EBU Mode' loudness metering to supplement R 128
[79] https://tech.ebu.ch/docs/tech/tech3342.pdf — Loundess Range: a measure to supplement R 128
[80] https://tech.ebu.ch/docs/tech/tech3343.pdf — Guidelines for Production of Programmes in Accordance with EBU R 128
[81] https://tech.ebu.ch/docs/tech/tech3344.pdf — Guidelines for Distribution and Reproduction in accordance with EBU R128
[82] https://tech.ebu.ch/docs/tech/tech3276.pdf — EBU Tech 3276-1998 Listening conditions for sound programme material: M&S
[83] https://tech.ebu.ch/docs/tech/tech3276s1.pdf — EBU Tech 3276s1-2004 Listening conditions: Suppl. 1, Multichannel sound
[84] https://tech.ebu.ch/docs/tech/tech3286s1.pdf — EBU Tech 3286s1-2001 Subjective evaluation of quality; Sup.1 Multichannel
[85] https://www.iso.org/standard/83117.html — ISO 226:2023 - Acoustics — Normal equal-loudness-level contours
[86] https://www.iso.org/standard/63077.html — ISO 532-1:2017 - Acoustics — Methods for calculating loudness — Part 1: Zwicker method
[87] https://www.iso.org/standard/63078.html — ISO 532-2:2017 - Acoustics — Methods for calculating loudness — Part 2: Moore-Glasberg method
[88] https://www.iso.org/standard/40979.html — ISO 3382-1:2009 - Acoustics — Measurement of room acoustic parameters — Part 1: Performance spaces
[89] https://www.iso.org/standard/36201.html — ISO 3382-2:2008 - Acoustics — Measurement of room acoustic parameters — Part 2: Reverberation time in ordinary rooms
[90] https://www.iso.org/standard/77437.html — ISO 3382-3:2022 - Acoustics — Measurement of room acoustic parameters — Part 3: Open plan offices
[91] https://webstore.iec.ch/en/publication/86573 — IEC 60268-7:2025 | IEC
[92] https://webstore.iec.ch/en/publication/1443 — IEC 60318-1:2009 | IEC
[93] https://webstore.iec.ch/en/publication/1445 — IEC 60318-4:2010 | IEC
[94] https://webstore.iec.ch/en/publication/28687 — IEC 60268-21:2018 | IEC
[95] https://webstore.iec.ch/en/publication/60560 — IEC 60268-22:2020 | IEC
[96] https://www.itu.int/rec/T-REC-P.57-202106-I — P.57 : Artificial ears
[97] https://www.itu.int/rec/T-REC-P.58/recommendation.asp?lang=en&parent=T-REC-P.58-202303-I — P.58 : Head and torso simulator for telephonometry
[98] https://aes2.org/publications/standards-store/?id=99 — (no title)
[99] https://pubmed.ncbi.nlm.nih.gov/2926000 — Headphone simulation of free-field listening. I: Stimulus synthesis
[100] https://pubs.aip.org/asa/jasa/article/85/2/868/807017/Headphone-simulation-of-free-field-listening-II — Headphone simulation of free‐field listening. II: Psychophysical validation | The Journal of the Acoustical Society of America | AIP Publishing
[101] https://www.ece.ucdavis.edu/cipic/wp-content/uploads/sites/12/2015/04/cipic_WASSAP_2001_143.pdf — The CIPIC HRTF Database
[102] https://sound.media.mit.edu/resources/KEMAR/hrtfdoc.txt — (no title)
[103] https://vbn.aau.dk/da/publications/head-related-transfer-functions-of-human-subjects-2 — Head-related transfer functions of human subjects
      -  Aalborg Universitets forskningsportal
[104] https://www.nature.com/articles/25526 — Role of spectral detail in sound-source localization | Nature
[105] https://pubmed.ncbi.nlm.nih.gov/8354753 — Localization using nonindividualized head-related transfer functions
[106] https://pubs.aip.org/asa/jasa/article/99/6/3678/751322/On-the-externalization-of-sound-images — On the externalization of sound images | The Journal of the Acoustical Society of America | AIP Publishing
[107] https://ieeexplore.ieee.org/document/1048207 — Virtual audio system customization using visual matching of ear parameters | IEEE Conference Publication | IEEE Xplore
[108] https://www.jstage.jst.go.jp/article/ast/27/6/27_6_340/_article — Individualization of head-related transfer functions with tournament-style listening test: Listening with other’s ears
[109] https://pubmed.ncbi.nlm.nih.gov/11885605 — Direct comparison of the impact of head tracking, reverberation, and individualized head-related transfer functions on the spatial perception of a virtual speech source
[110] https://pmc.ncbi.nlm.nih.gov/articles/PMC4310278 — Perceptual factors contribute more than acoustical factors to sound localization abilities with virtual sources
[111] https://pmc.ncbi.nlm.nih.gov/articles/PMC4249451 — Do you hear where I hear?: isolating the individualized sound localization cues
[112] https://pmc.ncbi.nlm.nih.gov/articles/PMC7509635 — Usability of Individualized Head-Related Transfer Functions in Virtual Reality: Empirical Study With Perceptual Attributes in Sagittal Plane Sound Localization - PMC
[113] https://www.aes2.org/publications/elibrary-page/?id=16768 — Listener Preferences for Different Headphone Target Response Curves
[114] https://aes2.org/publications/elibrary-page/?id=17042 — (no title)
[115] https://aes.org/publications/elibrary/elibrary-page/?id=17940 — Factors That Influence Listeners’ Preferred Bass and Treble Levels in Headphones
[116] https://aes.org/publications/elibrary/elibrary-page/?id=19436 — A Statistical Model that Predicts Listeners’ Preference Ratings of Around-Ear and On-Ear Headphones
[117] https://secure.aes.org/forum/pubs/journal/?elib=4465 — AES Journal Forum » Subjective Measurements of Loudspeaker Sound Quality and Listener Performance
[118] https://tech.ebu.ch/publications/r022 — Listening conditions for the assessment of sound programme material
[119] https://pubs.aip.org/asa/jasa/article/65/4/943/765693/Image-method-for-efficiently-simulating-small-room — Image method for efficiently simulating small‐room acoustics | The Journal of the Acoustical Society of America | AIP Publishing
[120] https://aes.org/publications/elibrary-page?id=849 — E-library page - AES
[121] https://doi.org/10.1121/1.1936895 — Further Progress with Colorless Artificial Reverberation | The Journal of the Acoustical Society of America | AIP Publishing
[122] https://www.jstor.org/stable/3680280 — About This Reverberation Business on JSTOR
[123] https://www.dafx.de/paper-archive/1999/beltran.pdf — Matlab Implementation of Reverberation Algorithms.
[124] https://dafx.de/paper-archive/2007/Papers/p059.pdf — Statistical Measures of Early Reflections of Room Impulse Responses
[125] https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient3-getsharedmodeengineperiod — IAudioClient3::GetSharedModeEnginePeriod (audioclient.h) - Win32 apps | Microsoft Learn
[126] https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient3-initializesharedaudiostream — IAudioClient3::InitializeSharedAudioStream (audioclient.h) - Win32 apps | Microsoft Learn
[127] https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiorenderclient-getbuffer — nf-audioclient-iaudiorenderclient-getbuffer
[128] https://developer.apple.com/documentation/audiotoolbox/aurendercallback — AURenderCallback | Apple Developer Documentation
[129] https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups — Understanding Audio Workgroups | Apple Developer Documentation
[130] https://developer.apple.com/library/archive/documentation/MusicAudio/Conceptual/AudioUnitHostingGuide_iOS/Introduction/Introduction.html — About Audio Unit Hosting
[131] https://developer.android.com/ndk/guides/audio/aaudio/aaudio — AAudio  |  Android NDK  |  Android Developers
[132] https://source.android.com/docs/core/audio/avoiding_pi — Avoid priority inversion  |  Android Open Source Project
[133] https://alsa-project.org/alsa-doc/alsa-lib/pcm.html — ALSA project - the C library reference: PCM (digital audio) interface
[134] https://alsa-project.org/alsa-doc/alsa-lib/group___p_c_m___direct.html — ALSA project - the C library reference: Direct Access (MMAP) Functions
[135] https://www.york.ac.uk/sadie-project/database.html — SADIE | Spatial Audio For Domestic Interactive Entertainment
[136] https://depositonce.tu-berlin.de/items/dc2a3076-a291-417e-97f0-7697e332c960 — The HUTUBS head-related transfer function (HRTF) database
[137] https://www.sonicom.eu/tools-and-resources/hrtf-dataset — SONICOM HRTF dataset Sonicom | Virtual Reality | Augmented Reality
[138] https://www.oeaw.ac.at/en/ari/outreach/software/hrtf-database — HRTF-Database
[139] https://www.riec.tohoku.ac.jp/pub/hrtf/hrtf_data.html — The RIEC HRTF Dataset
[140] http://hrtf.ircam.fr — LISTEN HRTF DATABASE
[141] https://www.akustik.rwth-aachen.de/cms/institut-fuer-hoertechnik-und-akustik/forschung/~pein/open-hrtf — Open-HRTF Dataset | Institut für Hörtechnik und Akustik | RWTH Aachen University | DE
[142] https://www.openair.hosted.york.ac.uk — OpenAIR – Open Air Library
[143] https://www.bbc.co.uk/rd/publications/sbsbrir — Spatially-sampled binaural room impulse responses
[144] https://zenodo.org/records/2641166 — 360° Binaural Room Impulse Response (BRIR) Database for 6DOF spatial perception research | Zenodo
[145] https://www.iks.rwth-aachen.de/en/research/tools-downloads/databases/aachen-impulse-response-database — IKS: Aachen Impulse Response Database
[146] https://www.openslr.org/28 — openslr.org
[147] https://arxiv.org/abs/1811.06795 — [1811.06795] Building and Evaluation of a Real Room Impulse Response Dataset
[148] https://github.com/jonashaag/RealRIRs — GitHub - jonashaag/RealRIRs: Python loaders for many Real Room Impulse Response databases · GitHub
[149] https://depositonce.tu-berlin.de/bitstreams/3b77ff9d-ce1b-4f0d-9269-0e50893ec543/download — depositonce.tu-berlin.de
[150] https://arxiv.org/abs/2003.06183 — [2003.06183] HRTF Individualization: A Survey
[151] https://arxiv.org/html/2203.11138v1 — Individualizing Head-Related Transfer Functions for Binaural Acoustic Applications
[152] https://arxiv.org/abs/2209.05110v1 — [2209.05110v1] Continuous head-related transfer function representation based on hyperspherical harmonics
[153] https://arxiv.org/abs/2307.09352 — [2307.09352] Efficient representation of head-related transfer functions in continuous space-frequency domains
[154] https://arxiv.org/abs/2303.09966 — [2303.09966] Magnitude-Corrected and Time-Aligned Interpolation of Head-Related Transfer Functions
[155] https://pmc.ncbi.nlm.nih.gov/articles/PMC9936143 — Dynamic spectral cues do not affect human sound localization during small head movements - PMC
[156] https://pmc.ncbi.nlm.nih.gov/articles/PMC2814998 — On the ability of human listeners to distinguish between front and back - PMC
[157] https://pubmed.ncbi.nlm.nih.gov/27106329 — On the variation of interaural time differences with frequency
[158] https://pmc.ncbi.nlm.nih.gov/articles/PMC5798994 — Across-channel interaural-level-difference processing demonstrates frequency dependence - PMC
[159] https://pmc.ncbi.nlm.nih.gov/articles/PMC11267622 — Auditory localization: a comprehensive practical review - PMC
[160] https://pmc.ncbi.nlm.nih.gov/articles/PMC7488874 — Sound Externalization: A Review of Recent Research - PMC
[161] https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0083068 — The Contribution of Head Movement to the Externalization and Internalization of Sounds | PLOS One
[162] https://arxiv.org/abs/2408.14198 — [2408.14198] Combined assessment of auditory distance perception and externalization
[163] https://arxiv.org/abs/2505.18020 — [2505.18020] Effects of auditory distance cues and reverberation on spatial perception and listening strategies
[164] https://pmc.ncbi.nlm.nih.gov/articles/PMC3874051 — Effects of early and late reflections on intelligibility of reverberated speech by cochlear implant listeners - PMC
[165] https://eprints.whiterose.ac.uk/id/eprint/184429 — Impact Thresholds of Parameters of Binaural Room Impulse Responses (BRIRs) on Perceptual Reverberation - White Rose Research Online
[166] https://pubmed.ncbi.nlm.nih.gov/22779451 — The impact of early reflections on binaural cues - PubMed
[167] https://www.dafx.de/paper-archive/2025/DAFx25_paper_52.pdf — Auditory Discrimination of Early ReflecTions in Virtual Rooms
[168] https://pub.dega-akustik.de/DAGA_2023/data/articles/000454.pdf — Externalization of Static Virtual Sound Sources using HRTFs  Approximated by Parametric IIR Filters and Room Simulation
[169] https://pmc.ncbi.nlm.nih.gov/articles/PMC4854823 — Six Degrees of Auditory Spatial Separation - PMC
[170] https://ieeexplore.ieee.org/document/9610904 — ieeexplore.ieee.org
[171] https://arxiv.org/abs/2508.16176v1 — [2508.16176v1] Head-Related Transfer Function Individualization Using Anthropometric Features and Spatially Independent Latent Representation
[172] https://arxiv.org/abs/2501.02871v1 — [2501.02871v1] Towards HRTF Personalization using Denoising Diffusion Models
[173] https://arxiv.org/abs/2507.05053v2 — [2507.05053v2] The Extended SONICOM HRTF Dataset and Spatial Audio Metrics Toolbox
[174] https://datacommons.princeton.edu/discovery/catalog/doi-10-34770-6gc9-5787 — The 3D3A Lab Binaural Room Impulse Response (BRIR) Dataset || 'untitled'
[175] https://arxiv.org/abs/2106.12992 — [2106.12992] SofaMyRoom: a fast and multiplatform "shoebox" room simulator for binaural room impulse response dataset generation
[176] http://articles.ircam.fr/textes/Jot97b — Jean-Marc Jot: Efficient models for reverberation and distance rendering in computer music and virtual audio reality (ICMC: International Computer Music Conference, Septembre 1997). <!--#IF EXPR="$DOCUMENT_NAME = /-e.html/" -->IRCAM Multimedia Library<!--#ELSE -->Médiathèque de l'Ircam<!--#ENDIF --> © Ircam, 1996-2008 - <!--#IF EXPR="$DOCUMENT_NAME = /-e.html/" -->Research Institute in Acoustics and Music<!--#ELSE -->Institut de Recherche et Coordination Acoustique/Musique <!--#ENDIF -->- Paris, France
[177] https://arxiv.org/abs/2402.11216 — [2402.11216] Optimizing tiny colorless feedback delay networks
[178] https://arxiv.org/abs/1901.08865 — [1901.08865] Modal Decomposition of Feedback Delay Networks
[179] https://publications.rwth-aachen.de/record/466561/files/466561.pdf — Partitioned convolution algorithms for real-time auralization
[180] https://arxiv.org/abs/2310.00319 — [2310.00319] Time-Variant Overlap-Add in Partitions
[181] https://openresearchsoftware.metajnl.com/articles/187 — webMUSHRA — A Comprehensive Framework for Web-based Listening Tests | Journal of Open Research Software
[182] https://arxiv.org/abs/2212.01467 — [2212.01467] Can we still use PEAQ? A Performance Analysis of the ITU Standard for the Objective Assessment of Perceived Audio Quality
[183] https://aes2.org/publications/elibrary-page?id=15022 — E-library page - AES
[184] https://www.foobar2000.org/components/view/foo_abx — foobar2000: Components Repository - ABX Comparator
[185] https://miniaud.io/docs/manual — miniaudio - A single file audio playback and capture library.
[186] https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio — Low Latency Audio - Windows drivers | Microsoft Learn
[187] https://jackaudio.org/api/group__ClientCallbacks.html — JACK-AUDIO-CONNECTION-KIT: Setting Client Callbacks
[188] https://ccrma.stanford.edu/software/stk/RtAudio_8h.html — The Synthesis ToolKit in C++ (STK)
[189] https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service — Multimedia Class Scheduler Service - Win32 apps | Microsoft Learn
[190] https://learn.microsoft.com/en-us/windows/win32/xaudio2/xaudio2-callbacks — XAudio2 Callbacks - Win32 apps | Microsoft Learn
[191] https://learn.microsoft.com/en-us/windows/win32/coreaudio/rendersharedeventdriven — RenderSharedEventDriven - Win32 apps | Microsoft Learn
[192] https://docs.python.org/3.11/library/threading.html — threading — Thread-based parallelism — Python 3.11.17 documentation
[193] https://docs.python.org/3.11/c-api/init.html — Initialization, Finalization, and Threads — Python 3.11.16 documentation
[194] https://numpy.org/doc/2.1/reference/thread_safety.html — Thread Safety — NumPy v2.1 Manual
[195] https://doc.qt.io/qt-6/threads-qobject.html — Threads and QObjects | Qt 6.12
[196] http://www.rossbencina.com/code/real-time-audio-programming-101-time-waits-for-nothing — Ross Bencina » Real-time audio programming 101: time waits for nothing
[197] https://www.mathworks.com/help/dsp/ref/parametersmoother.html — Parameter Smoother - Smooth input parameters using exponential smoothing - Simulink
[198] https://webaudio.github.io/web-audio-api — Web Audio API 1.1
[199] https://www.ti.com/lit/wp/spraaj5/spraaj5.pdf — Cross Fade of Digital Audio Streams White Paper
[200] https://www.mdpi.com/2076-3417/8/11/2029 — A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study of the SADIE II Database
[201] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/pyproject.toml — AURORA main pyproject.toml
[202] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/tools/bench_callback.py — AURORA main tools/bench_callback.py
[203] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/tools/import_hrtf.py — AURORA main tools/import_hrtf.py
[204] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/docs/AUDIO_NATURALNESS_PLAN.md — AURORA main docs/AUDIO_NATURALNESS_PLAN.md
[205] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/PROJECT_PLAN.md — AURORA main PROJECT_PLAN.md
[206] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/AGENTS.md — AURORA main AGENTS.md
[207] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/CLAUDE.md — AURORA main CLAUDE.md
[208] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/.claude/skills/release-preflight/SKILL.md — AURORA main .claude/skills/release-preflight/SKILL.md
[209] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/.claude/skills/verify-change/SKILL.md — AURORA main .claude/skills/verify-change/SKILL.md
[210] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/src/aurora/audio/engine.py — AURORA main src/aurora/audio/engine.py
[211] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/src/aurora/core/dsp_graph.py — AURORA main src/aurora/core/dsp_graph.py
[212] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/tests/test_engine.py — AURORA main tests/test_engine.py
[213] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/tests/test_dsp_graph.py — AURORA main tests/test_dsp_graph.py
[214] https://github.com/waydefu/MUSIC/blob/da6dd5ac5212542e03d939d1a44b941a995bbdd8/tests/test_hrtf_data.py — AURORA main tests/test_hrtf_data.py
