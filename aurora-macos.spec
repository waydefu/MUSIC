"""Apple Silicon macOS 個人使用版的 PyInstaller 打包設定。

這份 spec 與 Windows 的 ``aurora.spec`` 刻意分開：兩個平台的 Qt 二進位名稱、
bundle 佈局與圖示格式不同，macOS 的變更不應影響已驗證的 Windows EXE 流程。
"""

import runpy
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - SPECPATH 由 PyInstaller 注入
VERSION = str(runpy.run_path(ROOT / "src" / "aurora" / "__init__.py")["__version__"])

# ---------------------------------------------------------------- 排除模組

EXCLUDED_MODULES = [
    # 平台分支：macOS bundle 不應分析或攜帶 winreg／COM 實作。
    "aurora.platform.windows",
    "aurora.platform_win",
    # 網頁引擎
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
    # 音訊走 miniaudio，Qt Multimedia 不需要
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    # 其餘未使用的 Qt 模組
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
    # 標準庫／開發工具
    "tkinter",
    "unittest",
    "pydoc_data",
    "lib2to3",
    "pytest",
    "setuptools",
]

# ---------------------------------------------------------------- 收集後過濾

# PySide6 hook 會先收進整套 Qt；模組 excludes 不足以移除所有 framework、
# plugin 與 QML 資源，所以 Analysis 後仍要依 bundle 內的目的路徑過濾。
UNWANTED_BINARIES = (
    "qtwebengine",
    "qtwebchannel",
    "qtwebsockets",
    "qt3d",
    "qtquick3d",
    "qtcharts",
    "qtdatavisualization",
    "qtgraphs",
    "qtmultimedia",
    "qtspatialaudio",
    "qtpdf",
    "qtdesigner",
    "qttest",
    "qthelp",
    "qtsql",
    "qtnetworkauth",
    "qtbluetooth",
    "qtnfc",
    "qtserial",
    "qtremoteobjects",
    "qtscxml",
    "qtstatemachine",
    "qtsensors",
    "qtpositioning",
    "qtlocation",
    "qttexttospeech",
    "qthttpserver",
)

UNWANTED_DATA = (
    "qtwebengine",
    "qtmultimedia",
    "qtquick3d",
    "translations/qt_",
    "qtbase_",
    "qtdeclarative_",
)


def _keep(entry: tuple, patterns: tuple[str, ...]) -> bool:
    name = str(entry[0]).replace("\\", "/").lower()
    return not any(pattern in name for pattern in patterns)


a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "aurora" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "data"), "data"),
        (str(ROOT / "src" / "aurora" / "qml"), "aurora/qml"),
    ],
    # miniaudio 會動態載入兩個 native extension；平台 selector 的失敗又會
    # 安靜降級，因此三者都明列，並由 build_app.py 再做 frozen 守門。
    hiddenimports=["_cffi_backend", "_miniaudio", "aurora.platform.macos"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)

_before = (len(a.binaries), len(a.datas))
a.binaries = [item for item in a.binaries if _keep(item, UNWANTED_BINARIES)]
# macOS framework 不是只有 Mach-O 本體，還包含 Info.plist 與 PyInstaller
# 建立的 SYMLINK entries。只過濾 binaries 會留下斷掉的 framework 外殼，
# 因此 datas 必須同時套用 binary 與 data 模式。
a.datas = [
    item
    for item in a.datas
    if _keep(item, UNWANTED_BINARIES) and _keep(item, UNWANTED_DATA)
]
print(
    f"[aurora-macos.spec] binaries {_before[0]} -> {len(a.binaries)}, "
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
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "data" / "aurora-icon.icns"),
)

# COLLECT 是 onedir 的來源目錄；BUNDLE 會把它完整複製進自含式 .app。
# 名稱刻意避開 dist/AURORA，讓 macOS 建置不覆蓋 Windows onedir 產物。
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AURORA-macos",
)

app = BUNDLE(  # noqa: F821
    coll,
    name="AURORA.app",
    icon=str(ROOT / "data" / "aurora-icon.icns"),
    bundle_identifier="io.github.waydefu.aurora",
    version=VERSION,
    info_plist={
        "CFBundleVersion": VERSION,
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
    },
)
