# AURORA 極光播放器

<p align="center">
  <img src="data/aurora-icon.png" width="128" alt="AURORA 應用程式圖示">
</p>

AURORA 是一款以封面、即時頻譜與沉浸式動效為核心的 Windows 桌面音樂播放器。介面使用 PySide6／Qt Quick 製作，播放層採用 miniaudio，並提供來源音質、頻譜截止、疑似假無損、削波與 Windows 音訊端點分析。

> 目前版本僅支援 Windows。Windows EXE 無法直接在 macOS 執行；MacBook 版本需要另外實作 macOS 音訊端點層，並在 macOS 上打包與測試。

## 主要功能

- MP3、FLAC、WAV、OGG、OGA 播放
- 中文與其他非 ASCII 音樂路徑
- 拖入歌曲或整個音樂資料夾
- 以根目錄及子資料夾自動建立音樂庫歌單
- 音樂庫、播放清單、歌曲搜尋與清單返回導覽
- 播放、暫停、上一首、下一首、拖曳進度、隨機與循環播放
- 可移動的迷你播放器
- 真正覆蓋桌面的全螢幕模式
- 電影模式與不透明專屬啟動動畫
- 封面主色抽取、動態背景、即時頻譜、粒子與後製效果
- 可調整介面字體大小，設定於下次啟動時保留
- 同名 `.lrc` 歌詞載入與時間同步
- 音質面板：來源格式、取樣率、位元深度、頻譜截止、削波與疑似轉檔提示
- Windows Core Audio 端點與藍牙編碼能力推導

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
| `Ctrl+,` | 設定 |
| `C` | 電影模式 |
| `F11` | 全螢幕 |
| `Esc` | 離開全螢幕或關閉目前面板 |

## 從原始碼執行

### 環境需求

- Windows x64
- Python 3.11
- [uv](https://docs.astral.sh/uv/)

目前主要驗證環境為 Windows 11 23H2（build 22631）。

```powershell
git clone https://github.com/waydefu/MUSIC.git
Set-Location MUSIC
uv sync --dev
uv run aurora
```

只驗證 QML 能否完整載入、不開啟音訊裝置：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run aurora --validate-qml
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
uv run ruff check .
uv run mypy
uv run pytest
$env:QT_QPA_PLATFORM = "offscreen"
uv run aurora --validate-qml
```

目前品質基準：

- Ruff：通過
- mypy：31 個來源檔通過
- pytest：182 個測試通過
- QML 離屏載入：通過
- Windows 打包版冷啟動：通過

部分標記為 `win` 或 `audio` 的測試會使用 Windows 音訊子系統或實際音訊裝置。

## 音訊與音質分析說明

- 播放路徑使用 miniaudio `stream_file`，可處理中文路徑。
- 專案刻意不使用 miniaudio `decode_file`，因為它在 Windows 非 ASCII 路徑上不可靠。
- 即時頻譜使用 64 個頻帶與峰值保持顯示。
- 頻譜截止只是一種來源品質推估，不等同編碼器提供的絕對證明。
- 無損容器若量測到過低的高頻截止，介面會標示為疑似由有損來源轉檔。
- 藍牙編碼資訊來自 Windows 端點、裝置列舉與登錄資料推導，無法取得時會清楚標示為推定或未知。

## 專案結構

```text
src/aurora/
├── audio/         # 播放引擎、頻譜與音質分析
├── bridge/        # Python 與 QML 之間的控制器與模型
├── core/          # 設定、常數與共用資料型別
├── library/       # 音樂掃描、metadata、封面與快取
├── platform_win/  # Windows Core Audio 與藍牙資訊
└── qml/           # 主介面、面板、圖示與動效

tests/             # 單元、整合及 Windows 音訊測試
tools/             # EXE 建置與開發工具
data/              # 應用程式圖示與資料資源
```

## 已知平台限制

- 目前音訊端點與藍牙裝置分析依賴 Windows Core Audio、Windows Registry 與 Win32 API。
- macOS 與 Linux 尚未提供平台介面實作及正式安裝包。
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
- 開發分支：`codex/aurora-player-ui`
- Pull Request：<https://github.com/waydefu/MUSIC/pull/1>
