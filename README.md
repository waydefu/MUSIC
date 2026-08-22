# AURORA 極光播放器

<p align="center">
  <img src="data/aurora-icon.png" width="128" alt="AURORA 應用程式圖示">
</p>

AURORA 是一款以封面、即時頻譜與沉浸式動效為核心的桌面音樂播放器。介面使用 PySide6／Qt Quick 製作，播放層採用 miniaudio，並提供來源音質、頻譜截止、疑似假無損、削波與音訊端點分析。

> Windows 提供 EXE 發行包；macOS 可從原始碼執行。Windows EXE 無法直接在 macOS 執行，macOS 尚未提供 app bundle、簽章或正式安裝包。

## 主要功能

- MP3、FLAC、WAV、OGG、OGA 播放
- 中文與其他非 ASCII 音樂路徑
- 拖入歌曲或整個音樂資料夾
- 以根目錄及子資料夾自動建立音樂庫歌單
- 大型播放清單立即開啟，標籤與封面會在背景補齊並持久化快取
- 音樂庫、播放清單、歌曲搜尋與清單返回導覽
- 播放、暫停、上一首、下一首、拖曳進度、隨機與循環播放
- 可移動的迷你播放器
- 真正覆蓋桌面的全螢幕模式
- 電影模式與不透明專屬啟動動畫
- 封面主色抽取、動態背景、即時頻譜、粒子與後製效果
- 可調整介面字體大小，設定於下次啟動時保留
- 同名 `.lrc` 歌詞載入與時間同步
- 音質面板：來源格式、取樣率、位元深度、頻譜截止、削波與疑似轉檔提示
- 音訊端點資訊：Windows Core Audio 與 macOS Core Audio
- Windows 藍牙編碼能力推導（macOS 藍牙 codec 目前不做推定）

## 使用方式

### 加入音樂

可將單一歌曲、多首歌曲或資料夾拖入播放器，也可以按左下角的資料夾按鈕選擇固定音樂目錄。

加入大型目錄時，AURORA 會保留資料夾結構：

- 根目錄中的歌曲歸入根目錄歌單。
- 每個含有歌曲的子資料夾會成為獨立歌單。
- 在「音樂庫」點擊資料夾即可進入該歌單，不會自動播放第一首。
- 歌單頁左上角的返回按鈕可回到音樂庫。

播放清單上方可搜尋歌曲；搜尋會比對標題、演出者、專輯與檔案資訊。

### 快捷鍵

| 快捷鍵 | 功能 |
|---|---|
| `Space` | 播放／暫停 |
| `←` / `→` | 後退／前進 5 秒 |
| `Ctrl+←` / `Ctrl+→` | 上一首／下一首 |
| `↑` / `↓` | 音量增加／減少 5% |
| `M` | 靜音 |
| `Ctrl+M` | 切換迷你模式 |
| `L` | 歌詞面板 |
| `Ctrl+L` | 音樂庫 |
| `Ctrl+O` | 選擇音樂資料夾 |
| `P` | 播放清單 |
| `I` | 音質面板 |
| `E` | 音效（等化器／空間音效） |
| `Ctrl+,` | 設定 |
| `C` | 電影模式 |
| `F11` | 全螢幕 |
| `Esc` | 離開全螢幕或關閉目前面板 |

## 安裝（一般使用者）

到 [Releases](https://github.com/waydefu/MUSIC/releases) 下載
`AURORA-<版本>-windows-x64.zip`，**完整解壓縮**後雙擊「安裝.bat」。

不需要 Python、Qt 或 VC++ 可轉散發套件 —— 全部都包在裡面，也不需要
系統管理員權限。安裝腳本會做四件事：複製程式、建立開始功能表與桌面捷徑、
註冊音訊檔的「開啟方式」、登錄解除安裝資訊（之後可從「設定 → 應用程式」移除）。

> 一定要先解壓縮再執行。直接在壓縮檔裡點 `AURORA.exe` 會失敗 ——
> 它需要旁邊的 `_internal` 資料夾。

| | |
|---|---|
| 程式位置 | `%LOCALAPPDATA%\Programs\AURORA` |
| 設定與播放清單 | `%APPDATA%\Aurora` |
| 系統需求 | Windows 10 1809 以上或 Windows 11，64 位元 |
| 磁碟空間 | 約 200 MB |

### 設為預設播放器

安裝後 AURORA 已經在「開啟方式」清單裡。要設成預設：在音樂檔上按右鍵 →
**開啟方式** → **選擇其他應用程式** → 選「AURORA 極光播放器」→ 按**一律**。

Windows 10 之後不允許程式自行把自己設成預設處理常式（`UserChoice` 有雜湊
保護），這是系統刻意的防護，任何程式都繞不過去。所以這一步必須由使用者確認。

### 解除安裝

**設定 → 應用程式 → 已安裝的應用程式 → AURORA 極光播放器**，
或執行安裝目錄裡的 `uninstall.ps1`。設定與播放清單預設保留，
加 `-Purge` 可一併清除。

## 從原始碼執行

### 環境需求

- Windows x64，或 macOS（僅從原始碼執行）
- Python 3.11
- [uv](https://docs.astral.sh/uv/)

目前主要驗證環境為 Windows 11 23H2（build 22631）與 macOS；macOS 尚未提供可安裝的打包版。

```text
git clone https://github.com/waydefu/MUSIC.git
cd MUSIC
uv sync --dev
uv run aurora
```

只驗證 QML 能否完整載入、不開啟音訊裝置：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run aurora --validate-qml
```

macOS 的 zsh／bash 可改為：

```sh
QT_QPA_PLATFORM=offscreen uv run aurora --validate-qml
```

#### macOS：`.venv` 被標示為隱藏時

若倉庫位於 iCloud 同步的「桌面」或「文件」資料夾，macOS 可能替 `.venv`
內的 editable `.pth` 檔加上 hidden flag；Python 會略過該檔，導致
`uv run aurora` 找不到 `aurora`。只在遇到這個錯誤時，改用非點開頭的環境名稱：

```sh
export UV_PROJECT_ENVIRONMENT=venv
uv sync --dev
uv run aurora
```

離屏驗證則為：

```sh
QT_QPA_PLATFORM=offscreen UV_PROJECT_ENVIRONMENT=venv uv run aurora --validate-qml
```

## 建置 Windows EXE

```powershell
uv sync --dev
uv run python tools/build_exe.py
```

輸出位置：

```text
dist/AURORA/AURORA.exe
```

建置腳本使用 PyInstaller `onedir` 模式，會一併收集 Qt QML、應用程式圖示、miniaudio 與 `_cffi_backend`。請勿刪除 EXE 旁的 `_internal` 目錄，否則程式無法啟動。

## 品質檢查

```powershell
uv run python tools/make_test_audio.py   # 只需跑一次，產生測試素材
uv run ruff check .
uv run mypy
uv run pytest
$env:QT_QPA_PLATFORM = "offscreen"
uv run aurora --validate-qml
```

這些檢查**也會由 GitHub Actions 自動跑**（Windows 與 macOS 兩個 job，
見 `.github/workflows/ci.yml`），本機執行只是為了快速回饋。

macOS 的 mypy 要排除 Windows 專屬模組；以這行取代上面的 `uv run mypy`：

```sh
uv run mypy --exclude 'platform_win' --follow-imports=silent
```

目前品質基準（2026-08-22 於 Windows 實測）：

- Ruff：通過
- mypy：44 個來源檔通過
- pytest：366 個測試通過、1 個跳過（`test_macos_platform.py` 的 Core Audio
  測試只在 macOS 上跑，在 Windows 跳過是正確的）
- QML 離屏載入：通過
- Windows 打包版冷啟動：通過

CI 蓋不到、只能在實機做的：實際出聲的音訊測試、GUI 外觀、打包驗證，
以及 callback 效能的權威數字（`tools/bench_callback.py --device`）。

測試素材由 `tools/make_test_audio.py` 產生到 `tests/_generated/`（需要 `ffmpeg`，
不進版控）。**素材不存在時相關測試會 skip 而不是失敗** —— 此時 `pytest` 會顯示
311 passed、56 skipped，那不是完整的套件。

標記為 `audio` 的三個測試會實際開啟音訊裝置（預設會跑，`-m "not audio"` 可排除）。
`platform_win` 的測試則以 `sys.platform` 判斷，非 Windows 環境自動跳過。

## 音訊與音質分析說明

- 播放路徑使用 miniaudio `stream_file`，可處理中文路徑。
- 專案刻意不使用 miniaudio `decode_file`，因為它在 Windows 非 ASCII 路徑上不可靠。
- 即時頻譜使用 64 個頻帶與峰值保持顯示。
- 頻譜截止只是一種來源品質推估，不等同編碼器提供的絕對證明。
- 無損容器若量測到過低的高頻截止，介面會標示為疑似由有損來源轉檔。
- 藍牙編碼資訊來自 Windows 端點、裝置列舉與登錄資料推導，無法取得時會清楚標示為推定或未知。

## 專案結構

完整的模組責任、依賴方向、執行緒邊界與「點歌到出聲」時序請見 [ARCHITECTURE.md](ARCHITECTURE.md)。

```text
src/aurora/
├── audio/         # 播放引擎、頻譜與音質分析
├── bridge/        # Python/QML 控制器、Qt 模型與背景 metadata 協調
├── core/          # 設定、常數與共用資料型別
├── library/       # 音樂掃描、metadata、封面與快取
├── platform/      # 跨平台能力契約與各平台 adapter
├── platform_win/  # Windows Core Audio 與藍牙實作細節
└── qml/           # 主介面、面板、圖示與動效

tests/             # 單元、整合及 Windows 音訊測試
tools/             # EXE 建置與開發工具
packaging/         # 安裝／解除安裝腳本與發行說明
data/              # 應用程式圖示與資料資源
```

程式協作 agent 的作業規範（驗證契約、不變量、安全邊界）見 [AGENTS.md](AGENTS.md)。

### 點歌載入效能

播放清單還原與資料夾歌單採兩階段載入：主執行緒先用持久化快取或輕量檔案資訊建立清單，只同步解析即將播放的一首；其餘歌曲的標籤、時長與封面由背景執行緒分批補齊。載入成本因此不再隨歷史播放清單長度線性阻塞 UI，外部從檔案總管開歌也會先建立音訊串流，再處理非關鍵的音樂庫列舉。

## 已知平台限制

- Windows 的藍牙編碼資訊依賴 Core Audio、Windows Registry 與 Win32 API；macOS 目前不推定藍牙 codec，會降級為未知。
- macOS 可從原始碼執行，但尚無 app bundle、簽章、正式安裝包或檔案關聯；檔案關聯需未來在 bundle 的 `Info.plist` 宣告。
- Linux 尚未提供平台介面實作或正式安裝包。
- 音質推估會受到母帶、濾波器、取樣率與編碼器設定影響，結果應視為分析提示。

## 授權

本專案採 **GNU General Public License v3.0**，全文見 [LICENSE](LICENSE)。

選 GPL 不是偏好而是相依關係決定的。播放器直接使用 `mutagen` 讀取標籤，
而它是 GPL-2.0-or-later；Qt 綁定 `PySide6` 則是 LGPL-3.0 / GPL-2.0 / GPL-3.0
三擇一。把這些一起打包成執行檔散布時，整體必須以 GPL 相容的條款釋出，
GPL-3.0 是唯一同時滿足兩者的乾淨選擇。

| 相依套件 | 授權 |
|---|---|
| PySide6 / shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| mutagen | GPL-2.0-or-later |
| miniaudio | MIT |
| numpy | BSD-3-Clause 等 |

這代表：你可以自由使用、修改與再散布，但**改作後的版本也必須以 GPL 釋出並附上原始碼**。
如果需要用在不能開源的專案裡，得先把 `mutagen` 換成授權寬鬆的替代品
（例如 MIT 的 `tinytag`），並改用 PySide6 的商業授權。

## 專案連結

- GitHub：<https://github.com/waydefu/MUSIC>
- 預設分支：`main`
- Releases：<https://github.com/waydefu/MUSIC/releases>
