# QML 子樹 — Agent 附加規則

只寫這棵子樹與根目錄 [AGENTS.md](../../../AGENTS.md) 的**差異**。根目錄的不變量在這裡同樣適用。

## 為什麼這棵子樹要單獨說明

**Python 的 gate 完全不覆蓋 QML。** `ruff`、`mypy`、`pytest` 一行 QML 都不看。
改了這裡而只跑 Python 測試，等於什麼都沒驗證。

唯一的自動化 gate 是：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"; uv run aurora --validate-qml
```

它會實例化所有控制器、載入 `Main.qml` 與全部 import，然後結束。
**它只證明「載得起來」，不證明畫面正確。** 版面、動效、顏色、互動一律屬於
MANUAL-VERIFICATION-REQUIRED，需要人在 Windows 上實際看畫面。

## 註冊與檔案配置

- 新增元件必須同時寫進 `Aurora/qmldir`，否則 `import Aurora` 找不到它，
  而且失敗訊息只會出現在 QML 警告裡。
- 三個 singleton：`Motion`（動效 token）、`Appearance`（字體縮放）、`Strings`（文案）。
  singleton 在 `qmldir` 要用 `singleton` 關鍵字宣告。
- `Main.qml` 是視窗根；`Aurora/` 是元件庫；`Aurora/shaders/` 是著色器。

## 這棵子樹的真相來源

| 事實 | 來源 | 規則 |
|---|---|---|
| 動畫時長與曲線 | `Aurora/Motion.qml` | 元件**不准**自己寫死時長或 easing |
| 使用者可見文案 | `Aurora/Strings.qml` | 不要把中文字串直接寫在元件裡 |
| 字體縮放 | `Aurora/Appearance.qml` | 由設定持久化，元件讀 `Appearance.fontScale` |
| 配色 | `player.theme`（Python 側 `bridge/theme.py`） | 主色由封面抽取，**沒有** QML 端的調色盤檔案 |

## Python ↔ QML 的介面

`__main__.py` 只注入兩個 context property：`player`（`PlayerController`）與
`motion`（`MotionController`）。QML 透過它們的 `Property` / `Signal` / `Slot` 取值與呼叫。

- 不要在 QML 裡新增對 Python 的隱性依賴：需要新資料就在 bridge 層加 `Property` 並帶 `notify`。
- 播放清單、頻譜、歌詞都是 `QAbstractListModel`，由主執行緒更新（根 AGENTS.md 不變量 2）。

## 著色器

`shaders/*.frag` 是 GLSL 原始碼，`shaders/*.frag.qsb` 是編譯產物，
**兩者都進版控** —— 打包時 `aurora.spec` 收的是 `.qsb`，而 `build_exe.py` 會檢查它存在。

改了 `.frag` 之後一定要重新編譯並一起提交：

```powershell
uv run python tools/build_shaders.py
```

編譯器是 PySide6 自帶的 `pyside6-qsb`，不需要另外安裝 Qt SDK。
Qt 6 的 `ShaderEffect` 不吃原始 GLSL，只吃 `.qsb` 容器；Windows 預設後端是 Direct3D 11，
所以 HLSL 是必要的轉譯目標（目標清單在 `tools/build_shaders.py` 的 `TARGETS`）。

## 已知陷阱

- **樣式**：`QQuickStyle.setStyle("Basic")` 已在 `__main__.py` 設定。原生樣式會靜默忽略
  自訂繪製，只留一行 "does not support customization" 警告。不要改掉。
- **圓角**：用 `layer` + `MultiEffect` 遮罩做，不是 `clip`。Qt 的 clip 是矩形裁切，對圓角無效。
- **無邊框視窗**：`Main.qml` 把 `maximumWidth/Height` 夾在 `Screen.desktopAvailable*`。
  QML 的尺寸是**邏輯**像素，在 125% 縮放下邏輯桌面遠小於實體解析度；
  一旦底部控制列掉出螢幕，使用者連把視窗拖回來都做不到。不要放寬這個夾限。
- **`reduceMotion`**：開啟時必須移除位移、彈跳與粒子，只保留淡入淡出。這是無障礙硬性要求。
