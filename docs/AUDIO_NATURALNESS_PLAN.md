# AURORA 自然空間音效：實作計畫與驗收

更新：2026-10-03。原始碼基線：`5c312527f9733f2e04cd8fc5920d0c7e0ae439c3`。
本文件接續 [PROJECT_PLAN.md](../PROJECT_PLAN.md) §10.3／§10.7，作為下一輪音訊工作的現行順序；舊文件的實驗紀錄保留作歷史證據。

## 1. 本輪要改善的行為

使用者的最新回報是：WH-1000XM4、3.5 mm 有線，關機時悶、薄；開機後舒服，空間強度 **50–60% 很可以，100% 仍不自然**。先前限幅／不限幅 A/B 聽起來差不多。

因此目標是保留可用的中段聽感，讓高段仍保有低頻厚度、人聲穩定與自然距離感。50–60% 是這位使用者、這副耳機的基準，不是所有耳機的最佳值。100% 是效果強度上限，不代表定位準確度或音質百分比。

本輪先準備量測工具、實驗矩陣與分批實作封包。播放器演算法、已安裝程式及使用者設定尚未改動；後續主觀驗收均為 **NOT_RUN**。不因「零削波」或 CI 通過就宣稱自然度問題已解決。

## 2. 證據、未定事項與量測邊界

可版控的基線摘要見 [naturalness-baseline-2026-10-03.json](naturalness-baseline-2026-10-03.json)。原曲、個人裝置設定與輸出的 WAV 保留在本機，不進倉庫。

| 狀態 | 已知事項 | 對下一步的影響 |
|---|---|---|
| 使用者回報 | XM4 開機後舒服；50–60% 可用、100% 不自然 | 以開機有線模式建立 anchor；高段需單獨驗收 |
| 尚未確認 | ANC／Ambient 模式、Windows enhancements、3.5 mm 輸出端、即時 HRTF profile／cue／EQ | 聽測表必填；未知留 `unknown`，不能從存檔設定推定即時狀態 |
| 已量測 | 舊 A/B 兩首 2／3 的 LUFS 差為 0.10／0.27 LU，未達整數 full-scale | 與使用者回報並列；LUFS／sample peak 不判可聽性，限幅差異仍需盲聽 |
| 已量測 | 舊 A/B 1／3 等 RMS，卻相差 +0.87／+0.94 LU；20–250 Hz 相對少約 1.4–2.0 dB、1–4 kHz 多約 3.0–4.6 dB | 支持重新查音色與響度；頻帶能量不是耳機頻響或線性傳遞函數 |
| 證據不足 | 舊 WAV 沒有 renderer manifest、完整 GR envelope；「>3 dB 佔 30%／36%」未獨立重算 | 不把檔名當 pipeline 證明；新 renderer 重跑有上下文的原曲 |
| 已核對 | 安裝 EXE 的九個關鍵內嵌模組與基線程式碼相同 | 有新 DSP；不是所有資源／QML／即時播放驗收 |
| 已離線重現 | 初始音量斜坡、graph 部分輸出洩漏、EQ 參數競態、analyzer snapshot 四個邊界缺陷 | 先修播放安全與量測可信度；尚未證明它們造成持續悶薄 |

Sony 官方說明有線開機可使用降噪／環境音，關機仍可播放但無降噪；ON／OFF 必須作不同測試條件。官方未公開可直接移植的 XM4 DSP 係數，也不能推定 App EQ 在每種有線模式有效。[Sony 型號手冊](https://helpguide.sony.net/mdr/wh1000xm4/v1/en/contents/TP0002752734.html)

## 3. 從官方與作者實作採用的方法

下表區分公開事實與本專案推論。借鑑設計與對照方法，不宣稱品牌等效，也不把社群偏好票數當演算法證據。

| 來源與公開方法 | AURORA 的採用方式 | 邊界 |
|---|---|---|
| Dolby 的 binaural renderer 可按 object／bed channel 設 Off、Near、Mid、Far。[官方說明](https://professionalsupport.dolby.com/s/article/What-is-Binaural-Render-Mode-and-how-do-the-settings-affect-my-mix) | 距離與空間量分開設計候選 | 一般 stereo 沒有 Atmos object metadata；不能恢復每個樂器真實三維位置 |
| Sony 360 Reality Audio 使用物件位置資料；耳形分析最佳化相容服務。[360RA](https://electronics.sony.com/360-reality-audio)、[耳形分析](https://www.sony.com/electronics/support/articles/00233341) | 先提供可辨識、可選擇的 HRTF profile | 通用 profile 偏好選擇不是耳形個人化；無已驗證 mapping 不加入拍耳朵功能 |
| Bose Still／Motion 有不同聲場錨定與 recenter；CustomTune 使用耳內聲學回授。[手冊](https://assets.bosecreative.com/m/8f024ac3c0159c1/original/884885_OG_QCUH-HEADPHONEARN_en.pdf)、[CustomTune](https://www.bose.com/stories/sound-shaped-to-you-bose-customtune-technology) | 先把固定頭部座標的前方場景做好；耳機音色與房間分開檢查 | 無姿態 sensor 不宣稱 head tracking；無耳內麥克風／校準通道不宣稱 CustomTune |
| Steam Audio 分開 direct、reflections、air absorption 與 spatial blend。[Source](https://valvesoftware.github.io/steam-audio/doc/unity/source.html)、[blend](https://valvesoftware.github.io/steam-audio/doc/unity/guide.html#blend-between-spatialized-and-unspatialized-audio) | 先做單因子移除，之後才定獨立參數與平滑換入 | 遊戲音源模型不是 stereo master 的等價模型；不整套換引擎 |
| HeSuVi 分開 stereo upmix、角度、crossfeed 與 bypass。[作者 wiki](https://sourceforge.net/p/hesuvi/wiki/Usage%20of%20the%20Graphical%20User%20Interface/)；OpenAL 作者說 direct channels 與關閉 3D spatialize 不等價。[#935](https://github.com/kcat/openal-soft/issues/935)、[#1302](https://github.com/kcat/openal-soft/issues/1302) | 設直接 stereo、輕 crossfeed、HRTF、upmix 的不同參考；檢查已雙耳渲染內容與系統處理路由 | 不是 AURORA 已發生雙重處理的證明；商業捕获 IR 不能因可下載就隨產品散布 |
| AutoEq 作者區分防削波 preamp 與感知響度匹配；本專案另以 LUFS 建立測試條件。[README](https://github.com/jaakkopasanen/AutoEq)、[作者 #44](https://github.com/jaakkopasanen/AutoEq/issues/44) | headroom 與等響度分兩項 gate；耳機 EQ 以模式、target、有限增益記錄 | 不只看「XM4」型號就套 EQ；不能用 limiter 持續壓縮代替負 preamp |
| Impulcifer／ASH-Toolset 分離 headphone compensation、room response、校準 target。[Impulcifer](https://github.com/jaakkopasanen/Impulcifer)、[ASH-Toolset](https://github.com/ShanonPearce/ASH-Toolset) | 耳機模式檢查前移，BRIR 補償另列；個人量測保留來源與條件 | 缺量測硬體時只能選通用候選；程式與每份資料授權分別核對 |
| CamillaDSP 的 FIR／reload 有 block、sample-rate 與資源版本邊界；libmysofa 區分 normalize/no-norm、座標與 delay 單位。[CamillaDSP](https://github.com/HEnquist/camilladsp)、[libmysofa](https://github.com/hoene/libmysofa) | filter 先完整建立、hash、驗證，再發布 immutable snapshot；保留 Data.Delay 與 normalization | 不在 callback 讀檔；不默默二次 normalize 或丟掉 ITD |

耳機 response target 在 stereo 與 spatial content 的偏好可能不同；head movement 也影響外部化。「換 measured BRIR 就會自然」與「各商業廠牌都用量測 BRIR」不作先驗結論。[Engel 等原始研究](https://secure.aes.org/forum/pubs/journal/?elib=21564)、[Brimijoin 等原始研究](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0083068)
native／C++ 是獨立的 profiling 與交付成本決策，聽覺研究不能替它作結論。

社群原作者的 XM4 ON／OFF 測量提供固定模式的理由，但只是該作者樣本，不代表使用者實機，也不採用文中 passive EQ 當 powered EQ。[ASR 原始測量](https://www.audiosciencereview.com/forum/index.php?threads/sony-wh-1000xm4-review-noise-cancelling-headphone.19828/)

## 4. 調整後的順序與退出條件

| 階段 | 交付與順序 | 進入／退出 gate |
|---|---|---|
| **R0 實驗基線** | 離線 renderer、manifest、原曲上下文、固定增益 LUFS 對齊；保留 0／50／55／60／75／100% | 輸出可重現、對齊、不 clipping；明列 limiter-inactive 診斷與即時生產條件差別 |
| **R1 播放安全** | 下節四個獨立修正；每個小 PR 可分別審查 | deterministic failure 測試先失敗後通過；對外輸出／音量邊界及參數快照可信 |
| **R2 查因** | 先移除 early reflections、depth，再查 upmix／HRTF／makeup；必要時补精確生產電平渲染 | 有至少兩種內容支持的單因子結果，且使用者聽測；不因一個 IACC 變小決定方向 |
| **R3 高段自然度** | 維持現有 50–60% anchor；試 direct floor、reflection cap、distance coloration 或低變色的 blend 候選 | 50–60% 不退步；75／100% 的厚度、清晰、人聲、自然度通過；連續強度與切換 gate 通過 |
| **C／D 有條件修正** | C：有限樣本估計與時間平滑；D：K 加權慢補償及 limiter 前 headroom，分開實驗 | 各自先量實際問題，再改演算法；重新驗 R2／R3，不因舊排序就一次全疊 |
| **F／G 離線原型** | 若仍有定位／房間缺口，再做密集 HRTF／phantom 與一階 image-source／短尾巴；測 CPU 後決定 native | 證明比便宜候選改善、資料授權清楚、實機回呼有餘裕；不通過就停在現有方案 |
| **I 分項後續** | 耳機模式診斷已前移；選配 headphone EQ／HRTF；head tracking 需 sensor；stem-aware 需獨立品質與成本評估 | 不捆成一個必做功能；不拿未實現硬體能力作本輪依賴 |

100% 不能只偷偷改成舊 60%，再宣布改善完成。若候選確實採用強度壓縮，須揭露映射、保留 legacy mode，比較同等空間感的替代方案；先作 opt-in 實驗，不改預設。若 100% 不適合某些素材，可以提供明確效果模式／可用上限，但不聲稱所有內容自然外部化。

## 5. 第一批可直接開工的修正封包

四項是已重現的邊界問題，與持續音色主因分開。提交前補最小回歸；產品 DSP 本輪仍未改。

| 封包 | 位置 | 修正契約 | 必要驗證 |
|---|---|---|---|
| **R1-A 初始音量** | [engine.py](../src/aurora/audio/engine.py)：初始化、`_process`／`_gain_ramp` | 第一次有效 PCM 使用當下 target gain；後續轉換按 frame 平滑，兩耳共用一個 gain | volume=0／mute 首樣本零；0.5778 首樣本不超標；短 callback、load／seek／resume、不對稱增益回歸 |
| **R1-B graph 交易輸出** | [dsp_graph.py](../src/aurora/core/dsp_graph.py)：`prepare`／`process` | 在預配置工作區完成全鏈才 commit；失敗 caller PCM 完整保留、降級只通知一次 | gain→throw、stage 寫後 throw、最後 stage／第二聲道失敗；不能洩漏部分放大的 PCM；容量外 untouched fallback |
| **R1-C EQ snapshot** | [eq.py](../src/aurora/core/eq.py)：`set_gains`／`process` | callback 只讀一次 immutable spectrum；UI 完整設計後原子發布；history 由 callback 擁有 | forced FFT 中 flatten／disable／換係數；整次 block 同版、下一次新版本、不永久降級；舊 EQ 響應不退步 |
| **R1-D analyzer 一致讀取** | [analyzer.py](../src/aurora/audio/analyzer.py)：`RingBuffer.read_since`／`latest` | cursor、window、copy 在同一次 lock 取得；重計算留在鎖外，helper 不重複上鎖 | forced writer schedule、wrap／oversized write／overflow；不漏、不重複；小型 reader/writer 壓力測試 |

R1-B 要明定 callback 容量契約：prepare 至少涵蓋 engine 的最大 callback。超大 buffer 可以在呼叫端分塊或 untouched bypass／降級；不能在例外路徑臨時配置大型 backup。fallback 保留的是未處理 input，不承諾對任意超滿刻度 input 限幅；產品 safety limiter 的持續可用契約須另行設計、驗證，不能把 input bypass 描述成一定峰值安全。

R1-B 的 PCM 交易不會回滾已執行 stage 的 history。降級後保持 bypass，恢復必須換入 fresh prepared graph，或在 callback 停止時完整 reset；不能只清 degradation flag 就重用部分推進的 history。補 failure → explicit recovery 測試。另列 **R1-B-S：降級期間的獨立安全輸出** gate，評估 limiter 與效果 graph 的隔離、延遲、非有限 input 及 limiter 自身失敗；R1-B 輸出交易通過不代表這项也通過。

每個封包先跑相關 engine／graph／EQ／analyzer 回歸，加 ruff、mypy。涉及交易 copy 或 transition 的改動再跑同機性能 before／after。最後由一個整合封包驗證四項同時成立，再進自然度演算法；不混在一次大改中。

## 6. 離線工具與實驗規格

[probe_naturalness.py](../tools/probe_naturalness.py) 是本輪新增的無裝置 renderer；[工具測試](../tests/test_naturalness_probe.py) 守輸出與控制條件。需要本機 FFmpeg，但不新增產品 runtime dependency，不寫 AURORA config，不開音訊裝置。

### 6.1 第一輪實際提供的矩陣

所有列使用 fresh DSP instances、explicit profile、同一原曲及 block schedule。baseline 包含 dry、全鏈 50／55／60／75／100%；診斷臂包含 100% 移除早期反射、僅反射、移除 depth、反射減半。記錄每個有效參數，不把「Spatial 無 reflection」命名成純 HRTF：它仍含 upmix、中心補償、RMS makeup。

初版選「全列共同固定 preattenuation，直到 limiter 未介入」來查空間本身。Limiter 仍在效果臂內；dry 是精確硬 bypass。**這是 limiter-inactive 的診斷條件**，會改變輸入到 estimator／makeup 的電平，不等於平常即時播放。保存衰減值與 raw metrics；若低振幅補償改變行為，另做相同方法的數個電平掃描，再準備生產電平及完整 GR 觀測。不能用這批輸出聲稱已驗證正常音量的限幅行為。

第二輪依 R2 需要再增加：direct HRTF 候選（surround=0、depth=0、width=1，仍非純線性 transfer）、crossfeed、stereo／binaural、cue 0／0.5／1、不同 makeup。現有 amount 同時牽動多項係數；獨立 HRTF mix 要先改 API，不假裝一個 setter 已提供完整因素隔離。

### 6.2 原曲上下文、延遲及匯出

- Paperman 90–110 秒、Castorice 91–111 秒；從原曲取得至少 2 秒真實 preroll，再餵 2 秒真實 postroll，最後裁出原定 20 秒。postroll 不以補零代替，避免污染末尾 STFT window；真實曲尾不足時明列 EOF。
- decode 起點向下對齊該 sample-rate 的 Spatial hop grid，實際 preroll 可以稍長，source start/end 不變。未對齊的不同 preroll 會改變整段 STFT 視窗，不是同一生產時間網格。2 秒是初始工程值，另比較對齊後的 2／4 秒與全曲 context；不可用未對齊結果判 history 收斂。
- 依 graph declared latency 對齊 source 時間；flush latency 加有限反射尾巴。tail 與 latency 不同：反射 latency=0 仍會有尾巴。初版 conservative padding 要另用追加 padding 收斂測試。
- miniaudio 1.71 的 `stream_file` 回傳已 primed generator；不得再 `next()` 丟掉首塊。舊 `decode_all` helper 的額外 priming 會丟掉 4,096 frames，需另修並保留 regression；即時播放走另一條正確路徑。本工具直接使用正確串流。原曲解碼用 `miniaudio.stream_file`，保留 Windows 中文路徑契約；任一非有限樣本、graph degraded、指定 profile 缺失即拒絕結果，不能靜默 fallback synthetic。
- FFmpeg `loudnorm` 只取 input LUFS／TP 量測；不用其 processed samples。每首全矩陣只套整段常數衰減，選所有列都不用 boost 且 TP ≤−2 dBTP 的共同 LUFS target。此 −2 是聽測檔保守 headroom，產品 limiter 設計目標仍為 −1 dBTP。[FFmpeg 文件](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)、[EBU Tech 3341](https://tech.ebu.ch/docs/tech/tech3341.pdf)
- 匯出後再量，任兩列 integrated LUFS 差 ≤0.1 LU 是工具品質目標；20 秒 LRA 不作可靠長期動態結論。零訊號／非有限 LUFS 要報 invalid，不以假數字配對。
- 保存 source／core hashes、git SHA／dirty、block size、profile、requested／actual preroll／postroll、hop grid、flush／latency、全部參數、raw/export LUFS／TP、constant gain、limiter engaged frames、輸出 hash、工具版本。engaged% 不等於 GR >3 dB%，不能反推失真。
- 盲化檔名與答案表分開；seed 可重跑。選擇性 ABX 回答能否辨別；自然度與偏好要另評，不用 ABX 取代偏好聽測。

可重跑命令（PowerShell，先以本機原曲路徑代換）：

```powershell
$env:PYTHONUTF8='1'
uv run python tools/probe_naturalness.py --help
uv run python tools/probe_naturalness.py --in '原曲完整路徑.mp3' --out 'dist/naturalness/paperman' --start 90 --seconds 20 --profile synthetic --rate 48000 --seed 20261003 --xm4-power on --anc unknown
```

本輪 baseline 仍使用 synthetic 以便無資料依賴重跑；不代表它就是使用者當時的即時 profile。measured profile 須顯式指定、核對檔案與授權，再另做矩陣。

## 7. 聽感、數值與實機 gate

### 7.1 聽感 gate

在 XM4 3.5 mm＋開機、固定 ANC／Ambient、固定系統處理及同一輸出端下聽。播放預渲染 WAV 時把播放器 Spatial／EQ 關閉，避免重複效果；比較時保持同一系統音量。先兩首 pilot，之後加入乾人聲、寬 stereo、acoustic／古典與 dense bass，以及各曲較安靜片段。現有兩首重低音不能代表全曲庫。

按隨機成對比較分別記錄：低頻厚度、清晰度、中央人聲位置／穩定、自然距離、音場寬度、久聽舒適、整體偏好；每項 1–7 與簡短原因。量表是專案 pilot 工具，非品牌或學術通用門檻。單一使用者只作個人接受，不推廣成群體證明。

候選進入產品的條件：

1. 現有 50／55／60 anchor 不退步；未調該段參數時數值輸出保持 legacy 一致。
2. 高段在等響度下減少「薄／悶／人聲遠、反射不自然」，中央不漂；空間目標有清楚改善。不能只更大聲、更寬或反相。
3. 第一次 pilot 後隔日重聽仍接受，至少兩類不同素材成立；若結果不一致就保留實驗分支、擴展曲目，不改預設。
4. **NOT_RUN → 使用者接受** 必須填來源與日期；數值／CI 不可代填。

### 7.2 數值 gate

- 所有有效輸出 finite；相同參數可重現；bypass 保真；declared latency 與實測一致；64／1024／2880／非 hop 倍數／隨機 block schedules 對齊后在約定容差內一致。先查 renderer／stage 的 block dependence，再判聽感。
- 置中、偏位 6 dB、硬左／右、L=−R、低頻置中＋高頻擴散、短瞬態、曲尾脈衝、低振幅、44.1／48／96 kHz。mono bass、ILD／ITD、pre-echo、transient 舊回歸不退步。
- sample peak 與獨立 TP oracle 分列。產品 B 目標仍為 −1 dBTP；FFmpeg／FFT oracle 的演算法與邊界須註明，對爭議結果用第二 oracle，不靠 sample peak 推定 TP。
- true IACC 是指定 lag（例如 ±1 ms）內正規化互相關絕對值的最大值；IR 的 early／late window 從直達聲到達點起算，音樂 rolling-window 另作描述指標。zero-lag correlation 另列。[原始公式](https://www.acoustics.asn.au/conference_proceedings/INTERNOISE2014/papers/p901.pdf)**撤銷舊全頻 <0.3／低頻 <0.6 的合格門檻**，不把低頻自然相關當缺陷。頻帶能量與 IACC 供診斷，無單一「自然分數」。
- R3 掃 0–100% 連續曲線，特別 49／50／55／60／61／75／100%；0 為真正 bypass。parameter step、seek、pause/resume、下一曲與 profile 切換驗 click／短暫靜音／history；平滑策略與延遲對齊先定契約。

### 7.3 C／D 的獨立前提

C 用多種子、音量、方向、sample-rate 的 0／25／50／75／100% 已知直達比例驗偏差，再量 onset response。誤差 <0.1、90% 跟上 <100 ms 是舊計畫的候選工程目標，非已達成或通用準則。`_analyse` 的 estimator 平滑與 `_compensate` 的 makeup 平滑分開；防止 diffuse transient 誤判、pre-echo、ILD 退步與抽吸。

D 先在有來源 manifest 的真實音樂、完整上下文及不同強度重測。舊 WAV 的 +0.87／+0.94 LU 足以重開調查，**不足以直接指定產品增益修正**。只有偏差穩定超過專案自訂 ±0.5 LU，且候選有可聽收益，才改產品。先固定 gain 作參考，再試慢 K 加權能量補償；不把 gated integrated LUFS 逐 callback 跟蹤成快速 AGC。

減少 limiter GR 的 headroom 必須放在 limiter 前；目前 user volume 在 limiter 後，降低旋鈕不會減少先前 GR。0.9 LU 校正不能保證消除約 5.4 dB crest-factor 差。保留 final user volume 及 safety limiter，量 GR／crest-factor／瞬態，不能用響度匹配掩蓋持續重壓。

### 7.4 callback、打包與回退

純 core 不引 Qt。係數／IR／新 graph 在非回呼執行緒 prepare，完整 snapshot 一次發布；callback 不讀檔、不發 Qt signals、不新增可避免的大型配置／阻塞。換入新 stage 時定義 history、tail、dry/wet delay 與 crossfade，不能重用 UI 正在修改的物件。

工具計時只是離線 `_process` 成本。產品變更後需同機同參數 before／after、實際 block deadline 的 mean／p99／max，再驗含 QML、解碼與實體裝置的整條回呼及 dropout。歷史預算偏離保留，新增成本不能用離線 mean 代替實機批准。

涉及 QML 才跑 QML gate；涉及產品／封裝再做 build verify、安裝版 cold-start 及 listening。此次只加離線工具與文件，未更換 installer。每份交付保存 source SHA、dirty、版本、build manifest、EXE／ZIP hash；現在同版號不同 SHA，不能只用「0.2.0」辨識。

rollback：候選 flag 預設關；舊 config 可讀、sanitize 新值、保留 legacy renderer；任何數值／聽感／CPU gate 失敗即不發布該候選。不自動套耳機 EQ，不移除安全限幅。

## 8. F／G 與資料引入的決策包

先把有限一階反射做成離線對照，再決定是否加短 late tail。現有 HRTF 的延長不代表可直接裝入任意長 BRIR；長尾需分區卷積原型、latency／tail／buffer contract。native 只在完整 callback profiling 定位熱點後評估；先證明功能收益，再增加打包成本。

每份 HRIR／BRIR／耳機 profile 在導入前記：原始網址、作者、license、允許再散布／修改、hash、sample-rate、coordinates、L/R order、Data.Delay 單位、normalization／target、重取樣方法、版本。reader 程式 license 不涵蓋 dataset。

採用選擇：AutoEq／Impulcifer／Steam Audio／CamillaDSP／libmysofa 先借鑑公開方法與離線對照；目前不新增依賴。ASH-Toolset 為 AGPL，若搬程式碼要另核 obligations；CamillaDSP README 的 GPLv3／MPL-2.0 與 ASIO build 例外按實際版本確認。HeSuVi captured 商業 IR 與 SADIE 資料再散布權未核清，不列進本輪 bundle。逐份 license 不明就不導入，而不是用「免費下載」當授權。

## 9. 實作交接與目前完成度

| 交付 | 本輪狀態 |
|---|---|
| 更新現行順序、官方／GitHub 方法、R1 封包與 R2–G gate | 文件已完成 |
| renderer／constant-gain 匯出／manifest／針對工具的回歸 | **已通過：13 項工具測試、Ruff、src＋工具 Mypy** |
| 兩首原曲 pilot baseline | **已完成 20 WAV**，每首交付 spread 0.01 LU、limiter 全程 gain=1；[實際結果](NATURALNESS_PREPARATION_RESULT.md)，不是自然度改善候選 |
| R1 四項產品修正、C／D 演算法、R3 新映射 | **尚未實作**，已指定位置與驗收 |
| 新版 100% 主觀接受、完整裝置性能、installer／release | **NOT_RUN** |

下一個產品實作先做 R1-A／R1-B；R0 結果可並行協助 R2 查因。R1 完成後每次只疊一個音色因素，用相同 renderer／曲目／模式重跑，再決定候選是否進產品。
