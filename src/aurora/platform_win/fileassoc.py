"""把 AURORA 註冊成音訊檔的開啟方式。

全部寫在 ``HKEY_CURRENT_USER`` 底下 —— 只影響目前這個使用者，不需要
系統管理員權限，解除註冊也是刪掉自己建的那幾個鍵而已。

註冊的內容分三層：

``HKCU\\Software\\Classes\\AURORA.AudioFile``
    ProgID 本體：顯示名稱、圖示、以及 ``shell\\open\\command``。
``HKCU\\Software\\Classes\\.mp3\\OpenWithProgids``
    讓 AURORA 出現在檔案總管的「開啟方式」清單裡。這是**加入**而不是
    搶佔 —— 其他播放器原本的關聯不會被動到。
``HKCU\\Software\\AURORA\\Capabilities`` + ``RegisteredApplications``
    讓 AURORA 出現在 Windows 的「預設應用程式」設定頁面。

關於「設為預設」：Windows 10 之後**不允許**程式自行把自己設成預設處理常式，
那是刻意的防呆設計，任何宣稱做得到的方法都是在鑽漏洞而且會被系統重設。
所以這裡只做到「隨時可以用 AURORA 開啟」，要不要當預設由使用者在
Windows 設定裡自己決定，:func:`open_default_apps_settings` 會幫他開到那一頁。
"""

from __future__ import annotations

import subprocess
import sys
import winreg
from contextlib import suppress
from pathlib import Path

from aurora import APP_DISPLAY_NAME
from aurora.core.constants import AUDIO_EXTENSIONS

#: ProgID。加上廠商前綴避免與其他程式相撞。
PROG_ID = "AURORA.AudioFile"
_APP_KEY = r"Software\AURORA"
_CAPABILITIES_KEY = rf"{_APP_KEY}\Capabilities"
_REGISTERED_APPS = r"Software\RegisteredApplications"
_CLASSES = r"Software\Classes"


def executable_path() -> str:
    """要寫進註冊表的執行檔路徑。

    打包後 ``sys.executable`` 就是 AURORA.exe；開發模式下它是 python.exe，
    這時要連同 ``-m aurora`` 一起寫進命令列，否則關聯會叫起一個空的直譯器。
    """
    return str(Path(sys.executable).resolve())


def _open_command() -> str:
    executable = executable_path()
    if Path(executable).name.lower().startswith("aurora"):
        return f'"{executable}" "%1"'
    return f'"{executable}" -m aurora "%1"'


def _set(key_path: str, name: str | None, value: str) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register_file_types() -> bool:
    """建立 ProgID 與副檔名關聯。回傳是否全部成功。

    只做「可以用 AURORA 開啟」，不搶其他程式的既有關聯。
    """
    executable = executable_path()
    icon = f"{executable},0"

    try:
        # ProgID 本體
        _set(rf"{_CLASSES}\{PROG_ID}", None, f"{APP_DISPLAY_NAME} 音訊檔")
        _set(rf"{_CLASSES}\{PROG_ID}\DefaultIcon", None, icon)
        _set(rf"{_CLASSES}\{PROG_ID}\shell\open\command", None, _open_command())
        # 讓「開啟方式」選單顯示得體的名稱
        _set(rf"{_CLASSES}\{PROG_ID}\shell\open", "FriendlyAppName", APP_DISPLAY_NAME)

        # 每個副檔名掛上 OpenWithProgids —— 這是「加入選項」而非「奪取關聯」
        for extension in sorted(AUDIO_EXTENSIONS):
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, rf"{_CLASSES}\{extension}\OpenWithProgids"
            ) as key:
                winreg.SetValueEx(key, PROG_ID, 0, winreg.REG_NONE, b"")

        # 讓 AURORA 出現在 Windows 的「預設應用程式」頁面
        _set(_CAPABILITIES_KEY, "ApplicationName", APP_DISPLAY_NAME)
        _set(
            _CAPABILITIES_KEY,
            "ApplicationDescription",
            "本機音樂播放器，支援 MP3、FLAC、WAV、OGG，並顯示實際輸出音質。",
        )
        _set(_CAPABILITIES_KEY, "ApplicationIcon", icon)
        for extension in sorted(AUDIO_EXTENSIONS):
            _set(rf"{_CAPABILITIES_KEY}\FileAssociations", extension, PROG_ID)

        _set(_REGISTERED_APPS, "AURORA", _CAPABILITIES_KEY)
    except OSError:
        return False

    _notify_shell()
    return True


def unregister_file_types() -> bool:
    """移除所有註冊過的鍵。留下乾淨的系統。"""
    try:
        for extension in sorted(AUDIO_EXTENSIONS):
            _delete_value(rf"{_CLASSES}\{extension}\OpenWithProgids", PROG_ID)
        _delete_value(_REGISTERED_APPS, "AURORA")
        _delete_tree(rf"{_CLASSES}\{PROG_ID}")
        _delete_tree(_APP_KEY)
    except OSError:
        return False
    _notify_shell()
    return True


def is_registered() -> bool:
    try:
        # QueryValue（不帶 Ex）讀的就是預設值，不必傳 None 當名稱
        command = winreg.QueryValue(
            winreg.HKEY_CURRENT_USER, rf"{_CLASSES}\{PROG_ID}\shell\open\command"
        )
    except OSError:
        return False
    # 執行檔搬過家的話要視為未註冊，否則關聯會指向不存在的路徑
    return executable_path().lower() in str(command).lower()


def open_default_apps_settings() -> bool:
    """開啟 Windows 的「預設應用程式」設定頁。

    Windows 10 之後只有使用者能指定預設處理常式，程式不行。
    我們能做的就是把他直接帶到那一頁。
    """
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "ms-settings:defaultapps"], shell=False)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- 內部


def _delete_value(key_path: str, name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _delete_tree(key_path: str) -> None:
    """遞迴刪除。winreg.DeleteKey 不會刪有子鍵的鍵，得自己走一遍。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except FileNotFoundError:
        return

    for child in children:
        _delete_tree(rf"{key_path}\{child}")
    with suppress(FileNotFoundError):
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)


def _notify_shell() -> None:
    """通知檔案總管關聯變了，否則要重開機才會生效。"""
    try:
        import ctypes

        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except (OSError, AttributeError):
        pass
