# AURORA — Agent 作業指南

給 Claude / Codex / Gemini 等程式協作 agent 的共用倉庫脈絡。
本檔只放**跨 agent 通用且長期穩定**的事實：驗證契約、不變量、任務路由、安全邊界。

## 這個倉庫是什麼

**Windows 專屬**的桌面音樂播放器（AURORA 極光播放器）。
Python 3.11 + PySide6／Qt Quick（QML）介面，miniaudio 播放層，mutagen 讀標籤，
numpy 做 FFT／音質分析。uv 管相依，PyInstaller `onedir` 打包，PowerShell 腳本安裝。
授權 GPL-3.0（由 mutagen 與 PySide6 的相依授權決定，不是偏好）。

**沒有 CI，沒有伺服器，沒有網路服務。** 所有驗證都發生在維護者的 Windows 機器上。
「測試綠燈」不等於「打包後的 EXE 正常」，這個落差是本倉庫最主要的風險來源。

## 先讀哪一份

| 想知道 | 權威來源 |
|---|---|
| 模組責任、依賴方向、執行緒邊界、點歌到出聲的時序 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 安裝、快捷鍵、從原始碼執行、建置、品質基準數字 | [README.md](README.md) |
| 驗證契約、不變量、任務路由、安全邊界 | 本檔 |
| QML／著色器子樹的額外規則 | [src/aurora/qml/AGENTS.md](src/aurora/qml/AGENTS.md) |

不要把 ARCHITECTURE.md 的架構圖或 README.md 的基準數字複製到這裡；它們有各自的擁有者。

## 單一真相來源

修改前先確認你動的是真正的來源，不是它的副本。

| 事實 | 來源 |
|---|---|
| 版本號 | `src/aurora/__init__.py` 的 `__version__`（`aurora.spec`、`make_release.py` 都從這裡讀） |
| Python 版本、相依、lint／型別／測試設定 | `pyproject.toml` |
| 音訊、頻譜、分析的所有數值常數 | `src/aurora/core/constants.py`（其他模組不得自行寫死） |
| 資源與使用者資料路徑（含打包前後差異） | `src/aurora/core/paths.py` |
| 使用者可見的 UI 文案 | `src/aurora/qml/Aurora/Strings.qml` |
| QML 元件註冊 | `src/aurora/qml/Aurora/qmldir` |
| EXE 打包內容與排除清單 | `aurora.spec` + `tools/build_exe.py` 的 `REQUIRED` / `FORBIDDEN` |
| 發行壓縮檔內容 | `tools/make_release.py` 的 `required` |
| 音樂庫快取格式 | `src/aurora/library/store.py` 的 `_SCHEMA_VERSION` |
| 檔案關聯寫入的登錄檔位置 | `src/aurora/platform_win/fileassoc.py` |
| 安裝／解除安裝實際行為 | `packaging/install.ps1`、`packaging/uninstall.ps1` |

## 不變量

破壞這些會直接壞掉，而且**不一定會被現有測試抓到**。

1. **音訊只能走 `miniaudio.stream_file`。** `decode_file` 在 Windows 非 ASCII 路徑上回
   `MA_DOES_NOT_EXIST(-7)`，本倉庫路徑本身就含中文。`tests/test_engine.py` 有守門測試。
2. **背景執行緒不得碰 `QObject` 或 `QAbstractListModel`。** 背景只產生不可變的 `Track`
   放進佇列；模型更新一律由 `PlayerController._tick()` 在 Qt 主執行緒完成。
3. **同步關鍵路徑只解析「即將播放的那一首」。** 快取未命中的其他列先用
   `read_track_stub()`，其餘標籤／封面交給背景補齊。逐首同步解析等於讓 UI 卡住。
4. **`core/` 不得 import Qt。** 它是純邏輯層，`pyproject.toml` 對 `aurora.core.*` 開 mypy strict。
5. **數值常數集中在 `core/constants.py`。** 其他模組不得自行寫死。
6. **設定與快取寫入必須原子**（先寫暫存再 `os.replace`），且**壞掉的檔案一律退回預設**——
   快取失效只能變慢，絕不能讓播放器開不起來。
7. **改動 `Track` 欄位就要 bump `store.py` 的 `_SCHEMA_VERSION`**，讓舊快取被安全丟棄。
8. **`packaging/*.ps1` 必須存成 UTF-8 with BOM。** PowerShell 5.1 沒有 BOM 會用系統
   ANSI 代碼頁（繁中是 cp950）解讀，安裝腳本 100% 解析失敗。`make_release.py` 會擋。
9. **檔案關聯只寫 `HKCU`，而且是「加入開啟方式」不是搶佔預設。** 不提權、不碰 `HKLM`。
   Windows 10 之後不允許程式自行設為預設處理常式，別嘗試繞過。
10. **`QQuickStyle.setStyle("Basic")` 必須在載入 QML 之前執行。** 原生樣式會靜靜忽略
    所有自訂繪製，只在主控台留一行警告。

## 驗證契約

### 可用的 gate

全部從倉庫根目錄執行。PowerShell 是主要 shell。

```powershell
uv run ruff check .                       # lint
uv run mypy                               # 型別（core/ 為 strict）
uv run pytest                             # 單元與整合測試
$env:QT_QPA_PLATFORM = "offscreen"; uv run aurora --validate-qml   # QML 完整載入，不開音訊裝置
uv run python tools/build_exe.py --verify # 打包並在凍結環境中重跑 QML 驗證
uv run python tools/make_release.py       # 建置 + BOM 檢查 + 壓縮 + SHA256
```

**跑 `pytest` 之前**：測試素材由 `uv run python tools/make_test_audio.py` 產生到
`tests/_generated/`（需要 `ffmpeg`，且輸出被重導向時要加 `PYTHONUTF8=1`）。
素材不存在時相關測試會 **skip 而不是失敗** —— 看到大量 skip 表示你量到的是縮水的套件，
不要據此宣稱「全部通過」。目前的基準數字見 README 的「品質檢查」。

`-m "not audio"` 可排除會真的開啟音訊裝置的測試（預設會跑）。

### 依變更類型選 gate

| 變更範圍 | 必要 gate |
|---|---|
| 只改 Markdown／註解 | `pytest tests/test_docs_references.py` |
| `core/`、`library/`、`audio/` 的純邏輯 | `ruff` + `mypy` + 相關 `pytest` 檔 |
| `bridge/`（Qt 模型、執行緒、生命週期） | `ruff` + `mypy` + `pytest` + `--validate-qml` |
| `qml/`、著色器 | `--validate-qml`（Python gate 完全不覆蓋 QML，見子樹的 AGENTS.md） |
| `platform_win/`（Core Audio、登錄檔、檔案關聯） | `pytest` + **實機執行**；純測試無法證明登錄檔或裝置行為 |
| `aurora.spec`、`tools/build_exe.py`、相依變動 | `tools/build_exe.py --verify` |
| `packaging/`、發行流程 | `tools/make_release.py`（含 BOM 檢查） |
| 版本號 | 只改 `src/aurora/__init__.py`，然後跑 `make_release.py` |

不要為了改一個錯字就跑完整打包；也不要只用單元測試就宣稱打包版沒問題。

### 證據等級

結論必須標明證據強度，不要用「應該可以」「看起來沒問題」代替。

- **VERIFIED** —— 相關 gate 實際跑過且通過，附上輸出。
- **CODE-ONLY** —— 只做了程式碼推理，沒有執行任何 gate。
- **MANUAL-VERIFICATION-REQUIRED** —— 需要人在 Windows 上實際看到／聽到：
  GUI 外觀與動效、音訊裝置實際出聲、藍牙端點資訊、檔案關聯右鍵選單、
  安裝／解除安裝流程、打包版冷啟動。
- **BLOCKED** —— 缺少前置條件（例如沒有 ffmpeg、沒有音訊裝置、沒有打包產物）。

QML 的 `--validate-qml` 只證明「載得起來」，**不證明畫面正確**。

## 任務路由

「要改某個功能該動哪個檔」的完整對照表在 [ARCHITECTURE.md](ARCHITECTURE.md) 的「目錄與責任索引」。
高層次分層：`qml → bridge → audio/library/platform_win → core`，`core` 不反向依賴。

## 安全與破壞性邊界

- **只寫 `HKCU` 與使用者自己的資料夾。** 不碰 `HKLM`、不要求提權、不改系統設定。
- **不要在維護者機器上執行 `packaging/install.ps1` 來「驗證」它。** 它會真的安裝、
  建立捷徑並寫入解除安裝登錄項。安裝行為屬於 MANUAL-VERIFICATION-REQUIRED。
- **不要為了讓測試通過而放寬不變量**（例如改回 `decode_file`、把模型更新搬到背景執行緒、
  或拿掉原子寫入）。測試不過代表程式有問題，不是不變量有問題。
- `dist/`、`build/`、`tests/_generated/`、`.venv/` 都是產物，已在 `.gitignore` 中，不要提交。
- 發行壓縮檔會附 SHA256；不要手動修改壓縮檔後沿用舊的雜湊值。

## 變更紀律

- **範圍守住。** 讀到相鄰程式碼發現的問題，記錄下來回報，不要順手改掉。
- **文件語言維持繁體中文**，與既有 README／ARCHITECTURE／程式碼註解一致。
- **註解解釋「為什麼」。** 本倉庫的既有註解密度高且都在講權衡與踩過的坑；
  新增註解請沿用這個風格，不要寫覆述程式碼的廢話。
- Windows 專屬程式碼放 `platform_win/`；macOS／Linux 目前**沒有**平台層實作，
  不要在共用層假設它存在。
