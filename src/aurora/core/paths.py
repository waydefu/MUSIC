"""路徑解析：原始碼、Windows onedir 與 macOS app bundle 都能找到資源。

PyInstaller 的 frozen runtime 會以 ``sys._MEIPASS`` 指向收集資源的根目錄；
onefile 是臨時解壓目錄，onedir 則是 bundle 內部目錄。資源路徑不能寫死成
專案相對路徑，且使用者設定永遠不能寫進唯讀的應用程式 bundle。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aurora import APP_NAME


def _meipass() -> str | None:
    """PyInstaller frozen 資源根目錄；非打包環境下不存在。"""
    return getattr(sys, "_MEIPASS", None)


def is_frozen() -> bool:
    """是否跑在 PyInstaller 打包出來的 EXE 或 app bundle 裡。"""
    return bool(getattr(sys, "frozen", False)) and _meipass() is not None


def resource_root() -> Path:
    """唯讀資源（data/、qml/、shaders/）的根目錄。"""
    bundle = _meipass()
    if bundle is not None:
        return Path(bundle)
    # src/aurora/core/paths.py → 專案根目錄
    return Path(__file__).resolve().parents[3]


def data_file(name: str) -> Path:
    """``data/`` 底下的一個資料檔。"""
    if is_frozen():
        return resource_root() / "data" / name

    project_data = Path(__file__).resolve().parents[3] / "data" / name
    if project_data.is_file():
        return project_data
    return Path(__file__).resolve().parents[2] / "data" / name


def qml_root() -> Path:
    """QML 來源目錄。打包後會被放進 ``aurora/qml``。"""
    if is_frozen():
        return resource_root() / "aurora" / "qml"
    return Path(__file__).resolve().parents[1] / "qml"


def app_data_dir() -> Path:
    """使用者資料目錄。呼叫時確保目錄存在。

    Windows 沿用 ``%APPDATA%\\Aurora``；macOS 則遵循平台慣例，放在
    ``~/Library/Application Support/Aurora``。其餘平台保留既有的 Windows
    相容 fallback，避免未支援的平台因為設定路徑而無法啟動。
    """
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    directory = root / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_file() -> Path:
    return app_data_dir() / "config.json"


def library_file() -> Path:
    return app_data_dir() / "library.json"


def hrtf_file() -> Path:
    """使用者自備的實測 HRTF 資料。

    **刻意放在使用者資料目錄而不是打包進去。** HRTF 資料集有各自的授權
    （SADIE II 是 Apache-2.0，但不是每一套都可以再散布），而且多數使用者
    根本不會用到 —— 為它加執行期相依或撐大 bundle 都不划算。
    檔案不存在時 HRTF renderer 自動退回合成頭模型，不是錯誤狀態。

    由 ``tools/import_hrtf.py`` 從資料集的 WAV 轉出來。

    **這是舊版的單檔位置。** 現在可以放多組（見 :func:`hrtf_dir`），
    這個路徑保留是為了讓已經匯入過的使用者不會突然失去他的資料。
    """
    return app_data_dir() / "hrtf.npz"


def hrtf_dir() -> Path:
    """使用者的 HRTF profile 資料夾，一個 ``.npz`` 就是一組耳朵。

    **為什麼要多組。** HRTF 是「某一個人的頭與耳朵」的量測，別人的資料
    套在自己身上不一定合 —— SADIE II 自己的聽感研究裡沒有任何受試者把
    自己的 HRTF 評為最喜歡，81% 反而偏好 KU100 這顆刻意做成平均人類的
    假人頭。所以正確的做法不是猜一組最好的，是讓使用者盲聽自己挑。

    呼叫時**不**建立目錄：沒有這個資料夾是正常狀態（代表還沒匯入過），
    建立空目錄只會讓人以為東西壞了。
    """
    return app_data_dir() / "hrtf"


def covers_dir() -> Path:
    directory = app_data_dir() / "covers"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
