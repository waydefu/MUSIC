# 自然度改善：開工準備結果

日期：2026-10-03。獨立分支：`codex/audio-naturalness-plan`；基底 `5c312527`。
現行順序與修正封包見 [AUDIO_NATURALNESS_PLAN.md](AUDIO_NATURALNESS_PLAN.md)，
數字、素材／程式／輸出 hashes 見 [可版控基線](naturalness-baseline-2026-10-03.json)。

## 已完成

- 更新主計畫，補官方／作者 GitHub 來源；保留 XM4 有線開機、50–60% 的接受基準。
- 將下一輪分成 R0 可重現測試、R1 四項安全修正、R2 移除對照、R3 高段自然度；C／D、F／G 有各自 gate。
- 新增 [renderer](../tools/probe_naturalness.py) 與 [13 項工具回歸](../tests/test_naturalness_probe.py)，沒有新增產品 runtime dependency。
- 兩首原曲各產生 10 組、48 kHz／stereo／24-bit／20 秒 WAV；完整參數、答案表與盲聽清單分開保存。

## 驗證

| Gate | 實際結果 | 證明範圍 |
|---|---|---|
| 工具回歸 | 13 passed | 中文路徑 PCM 時間、global hop grid、真實 postroll、有限 tail、分塊、bypass、profile 拒絕、固定增益與交付 LUFS spread |
| 文件引用 | 26 passed | 本輪 Markdown 的本機路徑存在；不是外部網站內容自動驗證 |
| Ruff | 全倉檢查通過；最後改動的工具／測試另通過 | Python lint |
| Mypy | src＋工具共 48 files 通過 | 原程式與新工具型別 |
| 兩首實際矩陣 | exit 0、每首 10 組、全部 hash／limiter／交付 gate 通過 | 離線、指定條件的可重跑基線 |
| 主觀／實機／installer | **NOT_RUN** | 新版 100% 自然感、完整裝置 deadline／dropout、打包接受尚未證明 |

## 實際矩陣

條件：explicit synthetic、binaural、cue=1、flat EQ、user gain=1；效果臂保留 limiter，
全列共同輸入固定衰減 −12 dB，使實際 limiter gain 始終為 1。聽測檔再套整段常數衰減。
這會改變輸入 estimator／makeup 的電平，**不等同正常輸入電平的播放驗收**。

| 原曲段落 | 真實 preroll／postroll | 共同 LUFS target | 交付 max−min | 交付最高 TP |
|---|---|---:|---:|---:|
| Paperman 90–110 秒 | 2.000000／2 秒 | -18.73 | 0.01 LU | -7.44 dBTP |
| Castorice 91–111 秒 | 2.018667／2 秒 | -18.57 | 0.01 LU | -7.28 dBTP |

矩陣包含 dry、全鏈 50／55／60／75／100%、100% 無早期反射、僅反射、無 depth、反射減半。
同一原曲的所有列取同一 source frame span，各使用 fresh DSP；沒有動態 normalize。

在此 −12 dB 診斷條件下，100% 的 raw LUFS 相對 dry 為 +0.54／+0.81 LU；55% 為 +0.09／+0.17 LU。
這支持再查高段響度與音色，但不能直接當作產品增益修正，也不證明哪一臂自然。
下一輪補正常輸入電平與完整 gain-reduction envelope，再分別定 D 與 headroom 候選。

## 修正的測試流程問題

1. miniaudio 1.71 串流已 primed；額外 `next()` 會丟掉首 4,096 frames。新工具正確直接 `send()`，已用已知 PCM 回歸。產品舊 `decode_all` helper 另列待修；即時播放使用另一條正確路徑。
2. 段落尾端不能直接接人工靜音；真實 postroll 避免末尾 STFT window 受截斷影響。初次工程輸出已標 SUPERSEDED。
3. context 起點須對齊 source frame 0 的 scaled hop grid。兩首未對齊的 2／4 秒 context 差異最大值為 0.04052／0.04949；對齊後為 1.19e−7／7.45e−8，亦與從原曲起點渲染參考收斂。此證據只適用本次 synthetic／48 kHz／−12 dB／兩段素材，不泛化為所有 HRTF。
4. 24-bit WAV 回量後檢查整組 max−min ≤0.1 LU，不能只看每列距 target ≤0.1 LU。

## 本機產物與下一個封包

產物在本 worktree 的 `dist/naturalness-baseline-2026-10-03/`，兩首各有 WAV、diagnostics、answer_map、listener_manifest。
原曲與 WAV 不進版控。耳機 power=on 是依使用者回報預填的聽測條件，ANC 尚為 unknown；工具沒有量測實體耳機。

先用 R1-A／R1-B 修初始音量與部分 graph 輸出，接 R1-C／R1-D 的參數及量測快照；所有位置與測試已列在計畫。
R2 可用本批單因子對照與使用者評分選方向。50–60% 保留、高段候選尚未套入產品。

本輪交付使用獨立分支 `codex/audio-naturalness-plan`；GitHub 發佈與審查狀態以對應分支／PR 為準。
產品程式碼、使用者設定、安裝版保持本輪開始時的狀態。
