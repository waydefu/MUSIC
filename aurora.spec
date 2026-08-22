# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包設定。

**為什麼需要 spec 檔而不是一長串命令列參數**：光靠 ``--exclude-module``
擋不住所有東西。PySide6 的 hook 會把整包 Qt 的 DLL 與資源檔一起收進來，
其中 QtWebEngine 一項就佔 280 MB —— 而這是個音樂播放器，一行網頁程式碼都沒有。
唯一可靠的做法是在 Analysis 之後直接過濾 ``a.binaries`` 與 ``a.datas``。

實測（2026-08-10）未過濾前的組成：

    Qt6WebEngineCore.dll                        195.3 MB
    qtwebengine_devtools_resources.debug.pak     72.3 MB
    opengl32sw.dll                               19.7 MB   （D3D11 才是 Windows 預設後端）
    avcodec-61.dll                               13.3 MB   （Qt Multimedia 用，我們走 miniaudio）
    qtwebengine_devtools_resources.pak           11.1 MB
    icudtl.dat                                   10.0 MB   （WebEngine 的 ICU 資料）

``_cffi_backend`` 必須手動列為 hidden import：miniaudio 是動態載入它的，
PyInstaller 靜態分析找不到。
"""

from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - SPECPATH 由 PyInstaller 注入

# ---------------------------------------------------------------- 排除模組

EXCLUDED_MODULES = [
    # 網頁引擎：整包最大的贅重，完全用不到
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    # 3D 與圖表
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtQuick3D",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    # 音訊走 miniaudio，Qt Multimedia 整條連同 FFmpeg 後端都不需要
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    # 其餘用不到的 Qt 模組
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtTest",
    "PySide6.QtHelp",
    "PySide6.QtSql",
    "PySide6.QtNetworkAuth",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtSensors",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer",
    # 標準庫裡用不到又會拖大體積的
    "tkinter",
    "unittest",
    "pydoc_data",
    "lib2to3",
    "pytest",
    "setuptools",
]

# ---------------------------------------------------------------- 二進位過濾

#: 檔名含這些片段的 DLL/EXE 一律不收。比對不分大小寫。
UNWANTED_BINARIES = (
    "qt6webengine",
    "qtwebengineprocess",
    "qt6webchannel",
    "qt6websockets",
    "qt63d",
    "qt6quick3d",
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6multimedia",
    "qt6spatialaudio",
    "qt6pdf",
    "qt6designer",
    "qt6test",
    "qt6help",
    "qt6sql",
    "qt6networkauth",
    "qt6bluetooth",
    "qt6nfc",
    "qt6serial",
    "qt6remoteobjects",
    "qt6scxml",
    "qt6statemachine",
    "qt6sensors",
    "qt6positioning",
    "qt6location",
    "qt6texttospeech",
    "qt6httpserver",
    # Qt Multimedia 的 FFmpeg 後端
    "avcodec-",
    "avformat-",
    "avutil-",
    "avdevice-",
    "avfilter-",
    "swresample-",
    "swscale-",
    # Mesa 軟體 OpenGL 後備。Windows 上 Qt Quick 預設走 Direct3D 11，
    # 這個 19.7 MB 的檔案只有在完全沒有 GPU 驅動時才會派上用場。
    "opengl32sw.dll",
)

#: 資源檔同樣過濾。WebEngine 的 .pak 與 ICU 資料佔了近百 MB。
UNWANTED_DATA = (
    "qtwebengine",
    "icudtl.dat",
    "qt6webengine",
    # Qt 自帶的各語系翻譯只服務 Qt 內建對話框，本專案一個都沒用到
    "translations/qt_",
    "translations\\qt_",
    "qtbase_",
    "qtdeclarative_",
)


def _keep(entry: tuple, patterns: tuple[str, ...]) -> bool:
    name = str(entry[0]).replace("\\", "/").lower()
    return not any(pattern.replace("\\", "/") in name for pattern in patterns)


a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "aurora" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "data"), "data"),
        (str(ROOT / "src" / "aurora" / "qml"), "aurora/qml"),
    ],
    # aurora.platform._select() 是在函式內才 import 平台實作的（因為
    # platform_win 在模組層級就 import winreg，放模組層級會讓 macOS 炸），
    # 所以 PyInstaller 的靜態分析看不到它。不明列的話打包版會找不到
    # WindowsAdapter 而**靜默**退化成 NullAdapter —— 音質面板變成一片
    # 「未知」，卻不會有任何錯誤訊息。
    hiddenimports=["_cffi_backend", "aurora.platform.windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)

_before = (len(a.binaries), len(a.datas))
a.binaries = [item for item in a.binaries if _keep(item, UNWANTED_BINARIES)]
a.datas = [item for item in a.datas if _keep(item, UNWANTED_DATA)]
print(
    f"[aurora.spec] binaries {_before[0]} -> {len(a.binaries)}, "
    f"resources {_before[1]} -> {len(a.datas)}"
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AURORA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "data" / "aurora-icon.ico"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AURORA",
)
