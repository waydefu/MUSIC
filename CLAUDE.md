# Claude Code 在本倉庫的作業方式

倉庫事實（架構、不變量、驗證契約、安全邊界）在共用文件裡，本檔不重複：

@AGENTS.md

本檔只描述 **Claude 在這裡該怎麼做事**。

## 環境現實

- **倉庫路徑本身含中文**（`D:\音樂撥放器\…`）。這不是意外，而是刻意保留的測試條件——
  非 ASCII 路徑正是 `stream_file` vs `decode_file`、`.pth` 編碼、PowerShell BOM
  這幾個坑的來源。不要「順手」建議搬到 ASCII 路徑。
- **PowerShell 是主要 shell**，Bash 工具也可用，但兩者語法不同，別混用。
- **所有 Python 命令都要 `uv run` 前綴**，不要直接呼叫 `python` 或 `pytest`。
- **把會輸出中文的工具腳本重導向時要加 `PYTHONUTF8=1`**，否則 Windows 會退回
  cp1252／cp950 並丟 `UnicodeEncodeError`。已知受影響：`tools/make_test_audio.py`、
  `tools/probe_endpoints.py`。
- 首次進到乾淨的 worktree 要先 `uv sync --dev`（`.venv/` 不進版控）。

## 動手之前

先讀後改。這個倉庫的程式碼註解密度很高，而且幾乎每個怪異寫法都附了「為什麼」——
在你判斷某段程式碼寫錯之前，先確認上面那段註解有沒有解釋它。**先讀註解，再下結論。**

需要先規劃再動手的情況：跨層變更（QML＋bridge＋core）、動到執行緒邊界或載入時序、
改動打包／發行流程。單檔的邏輯修正直接做。

**開新工作之前先比對 main。** worktree 的基底可能已經落後很多，而 session 開場
載入到 context 裡的 CLAUDE.md／AGENTS.md 是**那個舊基底**的版本 —— 它們會非常
有說服力地描述一個已經不存在的現況。實際踩過兩次：照舊文件認定某個機制「還沒做」
而開始重造一個 main 上早就有的東西；以及照舊 AGENTS.md 宣稱「這個倉庫沒有 CI」，
而 CI 當時已經在跑 Windows 與 macOS 兩個 job。成本是幾秒鐘：

```powershell
git fetch origin; git log --oneline HEAD..origin/main
```

有落後就先弄清楚落後的是什麼再動手。這條只針對**開新工作**；手上已經在做的
單檔修正不必每次都查。

## 驗證與宣稱

依 AGENTS.md 的驗證矩陣挑 gate，並遵守它的證據等級標籤。額外規則：

- **只跑需要的 gate。** 改文件不要跑打包；改 QML 不要只跑 pytest 就交差。
- **不要為了「保險」重跑已經綠燈且沒有相關變更的 gate。** 證據新鮮度看的是
  「這次改動之後有沒有跑過」，不是跑過幾次。
- **確定性的 bug 修正要附回歸測試**，除非該行為根本無法在無頭環境重現
  （GUI 外觀、實體音訊裝置、登錄檔副作用）——那就明講並標成
  MANUAL-VERIFICATION-REQUIRED。
- **本機測試綠燈不能推論打包版正常。** 打包版的宣稱需要
  `uv run python tools/build_exe.py --verify` 的實際輸出。
- 效能宣稱要有實測數字，不要用「應該更快」。

## 範圍

- 使用者要求的範圍就是交付範圍。讀相鄰程式碼時發現的問題**回報，不要順手修**。
- 不要因為看到改進空間就重構不相關的子系統、換相依套件或調 API。
- 文件用繁體中文，與既有文件一致。

## 子 agent

**預設單一 agent 完成。** 這個倉庫只有約 5,600 行 Python 與 4,000 行 QML，
直接讀比派 agent 去找還快。只有在使用者明確要求，或工作真的可以拆成互不相干的大塊時，
才考慮 subagent。不要為了「再檢查一次」而派一個 reviewer agent。

## Git

- 目前在 worktree 分支上作業。除非使用者要求，不要 commit 或 push。
- 不要 force push、不要 `git reset --hard`、不要 `git clean` 掉未追蹤檔案
  （`tests/_generated/` 重建要 ffmpeg）。

## 可用的 skill

- `/verify-change` —— 依實際改動挑選 gate，並產出正確的證據標籤。
- `/release-preflight` —— 發行前的完整封閉檢查（版本、打包、BOM、壓縮檔、雜湊）。

## 學到的東西該放哪

| 類型 | 去處 |
|---|---|
| 架構事實、不變量 | `AGENTS.md`（QML 專屬的放 `src/aurora/qml/AGENTS.md`） |
| Claude 的作業習慣 | 本檔 |
| 多步驟可重複流程 | `.claude/skills/<name>/SKILL.md` |
| 可機器判定的規則 | 測試（例如 `tests/test_docs_references.py`） |
| 單次任務的細節 | 哪裡都不放 |

一次性的失誤不要升級成永久規則。**不要靠把本檔寫長來解決問題。**
