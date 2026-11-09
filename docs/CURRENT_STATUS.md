# AURORA 目前狀態

更新：2026-11-07  
本頁是**專案目前狀態與下一步的唯一權威入口**。歷史設計、實驗過程與舊交接保留在 `PROJECT_PLAN.md`；需要知道「現在做到哪、接下來做什麼」時，以本頁為準。

## 目前基線

- 主分支：`main`；本次整理前基線 `71271ec`（PR #44）
- 正式 Release：`v0.2.0`；main 已領先正式版，尚未發布新安裝包
- GitHub 治理：`main` 已啟用 `Protect main` ruleset
  - 必須經 Pull Request
  - required checks：`Windows`、`macOS`
  - 必須與最新 main 同步
  - unresolved review conversation 不可合併
  - 禁止 force push、禁止刪除
  - 無 bypass actor
- QML gate：`--validate-qml` 遇到 QML runtime warning / binding error 會失敗；PR #44 已消除先前 macOS offscreen 的 `motion == null` TypeError 與 signal-handler deprecation

## 最新自動化品質基準

2026-11-07，PR #44：

| Gate | Windows | macOS |
|---|---:|---:|
| Ruff | PASS | PASS |
| mypy | 47 source files / 0 errors | 42 source files / 0 errors |
| pytest | 641 passed / 2 skipped / 3 deselected | 617 passed / 1 skipped / 3 deselected |
| QML offscreen | PASS | PASS |
| Frozen bundle | 封裝敏感 PR 條件式執行 | 封裝敏感 PR 條件式執行 |

封裝 gate 會在真正的 Windows EXE / macOS app bundle 中驗 QML、平台 adapter、必要內容與禁止的贅重依賴；installer、乾淨機 cold-start、實際出聲、GUI 外觀、callback 權威效能與主觀自然度仍需實機／人工證據。

## 音訊與自然度主線

### 已完成

- R0：可重現自然度 baseline、manifest、離線 renderer
- R1-A：初始音量／mute 正確
- R1-B：DSP graph transactional output / failure fallback
- R1-C：EQ immutable publication / block-consistent snapshot
- R1-D：Analyzer RingBuffer consistent snapshot
- R2 客觀診斷：LUFS、true peak、頻帶能量、correlation / IACC、完整 limiter gain envelope
- C estimator 研究：已重新校準 covariance anisotropy、真實 direct fraction 與 Wiener/MMSE 輸出的關係
- E 聲學回歸：octave-band early/late IACC、IACC_E3、HRTF ILD preservation

### 最新聽測證據

Issue #43（單一聽者、單一曲目，屬 MANUAL-VERIFICATION-REQUIRED）目前支持：

1. **自然度下降的主要嫌疑是 SpatialUpmix 升混本身**，不是 limiter，也不是 early reflections。
2. early reflections 單獨使用沒有顯示穩定傷害；兩輪對「是否優於原曲」結果不一致，因此仍不能下結論。
3. depth 會明顯增加 limiter 壓力，但移除 depth **沒有改善自然度**；不能用 gain reduction 大小直接代理聽感。
4. 強度與自然度不是單調關係；「只有 100% 才失真」不是目前證據支持的描述。

限制：目前只有 Paperman 的單人聽測；第二輪是 RMS 對齊而非 LUFS；缺少重複刺激與跨曲風驗證。

## 現在的下一步

### P1 — R3 單因子拆解 SpatialUpmix

先做**實驗能力與候選，不直接改產品預設**：

- decomposition only
- ambience / surround contribution only
- HRTF renderer only
- decomposition + HRTF
- makeup off / fixed makeup
- current full chain 對照

輸出要求：

- 同來源、同時間範圍、同 STFT context
- loudness-matched
- blind ID / answer manifest 分離
- 同一候選可重複出現，用來估計單一聽者一致性
- 同時保存 LUFS / TP / 頻帶 / IACC 等描述量，但不把任何單一指標當自然度分數

退出條件：先定位造成自然度下降的因素，再設計 75–100% 候選；不得直接把 100% 偷偷映射成舊 60%。

### P2 — 有證據才進

- C：direct / ambient estimator runtime 參數或公式修改
- D：響度補償與 headroom
- F：Dense HRTF / phantom rendering
- G：room / BRIR / image-source / late reverb
- I：headphone EQ、個人 HRTF、head tracking 等個人化

F/G 目前不是下一步。只有 R3 後仍證明有定位／外部化／房間線索缺口才進。

## 目前仍需人工／特定環境

- WH-1000XM4 實際 A/B 與主觀評分
- 固定 ANC / Ambient / Windows enhancements / endpoint 的聽測條件
- Windows `tools/bench_callback.py --device` 權威 callback 效能
- Windows installer / cold start / 真實裝置出聲
- GUI 外觀與動效驗收

## 文件權威關係

| 問題 | 權威來源 |
|---|---|
| 現在做到哪、下一步是什麼 | **本檔 `docs/CURRENT_STATUS.md`** |
| 自然度實驗設計與 gate | `docs/AUDIO_NATURALNESS_PLAN.md` |
| 200-source 外部研究與方法論 | `docs/AURORA_AUDIO_RESEARCH_200.md` |
| 歷史設計、舊 benchmark、決策演進 | `PROJECT_PLAN.md` |
| 模組與資料流 | `ARCHITECTURE.md` |
| 使用／安裝／建置／品質基準 | `README.md` |
| Agent 不變量與驗證契約 | `AGENTS.md` |

若歷史文件中的「下一步」與本頁衝突，**以本頁為準**；若程式碼／CI 的實際行為與文件衝突，先把它當 drift 調查，不要自行假定文件或程式其中一方一定正確。
