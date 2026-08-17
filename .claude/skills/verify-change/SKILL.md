---
name: verify-change
description: 依實際改動內容挑選最小必要的驗證 gate，判斷既有證據是否新鮮，並產出正確的證據等級標籤。在準備宣稱「改好了」之前使用，或使用者要求驗證／確認某項變更時使用。
---

# 驗證一項變更

目的：**用最少的執行量取得足夠的證據**，並誠實標示還沒被證明的部分。
不是「把所有測試再跑一遍」。

## 1. 先確定改了什麼

```bash
git status --short
git diff --stat
```

把改動分到這些類別（可複選）：

- `docs` —— 只有 Markdown、註解、docstring
- `pure` —— `src/aurora/core/`、`library/`、`audio/` 的純邏輯
- `bridge` —— `src/aurora/bridge/`：Qt 模型、執行緒、生命週期
- `qml` —— `src/aurora/qml/`（含 `shaders/`）
- `platform` —— `src/aurora/platform_win/`
- `packaging` —— `aurora.spec`、`tools/`、`packaging/`、`pyproject.toml` 相依

## 2. 挑 gate

對照 [AGENTS.md](../../../AGENTS.md) 的「依變更類型選 gate」表。不要超出、也不要少於它。

執行前確認前置條件：

- `pytest` 需要 `tests/_generated/`。不存在時大量測試會 **skip 而不是失敗**。
  沒有素材就先跑 `PYTHONUTF8=1 uv run python tools/make_test_audio.py`（需要 ffmpeg），
  或明確記錄「本次量到的是縮水的套件」。
- `--validate-qml` 需要 `QT_QPA_PLATFORM=offscreen` 才能在無頭環境跑。
- `build_exe.py --verify` 需要幾分鐘，而且會清掉 `dist/AURORA`。

## 3. 判斷證據新鮮度

對每個必要 gate 分類：

- **FRESH** —— 這次改動**之後**跑過且通過 → 不要重跑。
- **STALE** —— 跑過，但之後又改了相關檔案 → 重跑。
- **MISSING** —— 這次沒跑過 → 跑。

只執行 STALE 與 MISSING 的部分。「為了保險再跑一次」不是理由。

## 4. 回歸測試

確定性的 bug 修正要補一條回歸測試，放進對應的 `tests/test_*.py`。
先確認它在修正前會紅（可以用 `git stash` 驗證，或說明為什麼不需要）。

無法在無頭環境重現的行為**不要硬寫測試**——直接標成 MANUAL-VERIFICATION-REQUIRED：

GUI 版面與動效、實體音訊裝置出聲、藍牙端點資訊、檔案關聯右鍵選單、
安裝／解除安裝流程、打包版冷啟動。

## 5. 檢查同類缺陷

如果修掉的是某個**失敗類別**（不是單點筆誤），在倉庫裡搜同類的其他出現位置。
例如：某個工具腳本缺 UTF-8 stdout 保護時，其他 `tools/*.py` 是否也缺。
在範圍內、修起來安全的一併修掉；範圍外的記錄回報。

## 6. 產出結論

每一項宣稱都要帶標籤，並附上實際輸出摘要：

```
VERIFIED                        ruff / mypy / pytest 均通過（附實際輸出摘要）
CODE-ONLY                       platform_win 的登錄檔寫入路徑僅做程式碼推理
MANUAL-VERIFICATION-REQUIRED    面板圓角在 125% 縮放下的實際外觀
BLOCKED                         打包驗證：本機無 dist/ 產物且未授權執行完整打包
```

禁止用「應該可以」「看起來沒問題」「大概修好了」取代標籤。
沒跑就是 CODE-ONLY，跑不了就是 BLOCKED。

## 在較大的收尾任務中

若這次驗證屬於某個更大的清理／發行前收尾工作，驗證完成後**回到原本的工作繼續**，
不要因為單項驗證通過就結束整個收尾。
