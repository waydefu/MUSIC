"""路徑解析：打包前後都要能找到資料檔與使用者設定。

PyInstaller 的 onefile 模式會把 ``datas`` 解壓到臨時目錄並設 ``sys._MEIPASS``，
所以資源路徑不能寫死成專案相對路徑。這個模組是唯一處理這件事的地方。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aurora import APP_NAME


def _meipass() -> str | None:
    """PyInstaller onefile 解壓目錄。非打包環境下這個屬性不存在。"""
    return getattr(sys, "_MEIPASS", None)


def is_frozen() -> bool:
    """是否跑在 PyInstaller 打包出來的 EXE 裡。"""
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
    return resource_root() / "data" / name


def qml_root() -> Path:
    """QML 來源目錄。打包後會被放進 ``aurora/qml``。"""
    if is_frozen():
        return resource_root() / "aurora" / "qml"
    return Path(__file__).resolve().parents[1] / "qml"


def app_data_dir() -> Path:
    """``%APPDATA%\\Aurora``。呼叫時確保目錄存在。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    directory = root / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_file() -> Path:
    return app_data_dir() / "config.json"


def library_file() -> Path:
    return app_data_dir() / "library.json"


def covers_dir() -> Path:
    directory = app_data_dir() / "covers"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
