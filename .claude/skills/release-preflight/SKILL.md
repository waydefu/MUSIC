---
name: release-preflight
description: AURORA 發行前的完整封閉檢查——版本號、品質 gate、EXE 打包驗證、PowerShell BOM、發行壓縮檔與 SHA256。在準備打包發布新版本、產生 release zip，或使用者要求「發行前檢查」時使用。
---

# 發行前檢查

這是一個**有邊界的封閉集合**：下面每一項都要有結論才算完成。
中途發現缺陷就修掉（範圍內且安全時），然後**回到清單繼續**，不要停在第一個問題。

## 前置

- Windows x64、Python 3.11、`uv`
- `uv sync --dev`
- 打包會清掉並重建 `dist/AURORA`

## 封閉集合

逐項執行並記錄結果。

### 1. 版本號

版本的單一真相來源是 `src/aurora/__init__.py` 的 `__version__`。
`aurora.spec` 與 `tools/make_release.py` 都從那裡讀，**不要在別處改版本**。

確認它已更新，且沒有其他檔案寫死了舊版本：

```bash
uv run python -c "import aurora; print(aurora.__version__)"
grep -rn "<上一個版本號>" --include="*.py" --include="*.spec" --include="*.toml" --include="*.md" .
```

### 2. 品質 gate

跑完 [AGENTS.md](../../../AGENTS.md)「驗證契約」列出的全部四個 gate
（lint、型別、測試、QML 離屏載入）。發行是唯一一種**全部都要跑**的情境，
不適用平常的最小 gate 原則。

`pytest` 前先確認 `tests/_generated/` 存在，否則量到的是縮水的套件
（見 `/verify-change`）。基準數字見 README 的「品質檢查」。

### 3. 打包與 bundle 檢查

```powershell
uv run python tools/build_exe.py --verify
```

這一步同時做三件事，全部要綠：

- `REQUIRED` / `REQUIRED_GLOBS` 存在——特別是 `_cffi_backend*.pyd` 與
  `_miniaudio*.pyd`，miniaudio 是動態載入它們的，PyInstaller 靜態分析看不到，
  少了會在第一首歌就死掉。
- `FORBIDDEN` 沒有回來——`Qt6WebEngineCore.dll` 等贅重一旦復活，體積會爆增數百 MB。
- `--verify` 會在**凍結後的 EXE 裡**重跑 `--validate-qml`，這是唯一能抓到
  「Qt plugin 或 QML module 被剃太乾淨」的檢查。

### 4. 安裝腳本編碼

```powershell
uv run python tools/make_release.py
```

它會先擋 BOM：`packaging/*.ps1` 少了 UTF-8 BOM，PowerShell 5.1 會用系統 ANSI
代碼頁（繁中 cp950）解讀，使用者看到的是整頁 "Unexpected token" 而不是安裝畫面。

### 5. 發行壓縮檔

同一個命令會接著做：staging → 壓縮 → 內容檢查 → SHA256 → 寫出 `.zip.sha256`。

確認輸出：

- `dist/AURORA-<版本>-windows-x64.zip`
- `dist/AURORA-<版本>-windows-x64.zip.sha256`
- 內容檢查通過（含 `安裝.bat`、`install.ps1`、`uninstall.ps1`、`LICENSE.txt`）

**不要手動改壓縮檔內容後沿用舊雜湊。**

### 6. 文件同步

確認以下與這個版本一致：

- `README.md` 的品質基準數字與系統需求
- `packaging/README.txt` 的安裝說明與快捷鍵
- 快捷鍵表：`README.md`、`packaging/README.txt` 與 `Main.qml` 的實際綁定三者一致

### 7. 只能由人做的部分

以下**不要自行執行**，列成待辦交給維護者，並標成 MANUAL-VERIFICATION-REQUIRED：

- 在乾淨機器上解壓縮並執行 `安裝.bat`
- 打包版冷啟動、實際播放出聲、檔案關聯右鍵選單
- 解除安裝（含 `-Purge`）
- 建立 git tag 與上傳 GitHub Release

Agent 不要在維護者的機器上跑 `install.ps1`——它會真的安裝並寫入解除安裝登錄項。

## 完成條件

七項全部有明確結論（通過／已修正／已記錄為人工待辦）才算收尾完成。
若修正需要跨多個 commit，繼續做到封閉集合耗盡為止，不要在第一個 commit 後停下。
