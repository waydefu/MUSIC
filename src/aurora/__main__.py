"""AURORA 的 Qt 應用程式進入點。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QPoint, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from aurora.bridge.motion import MotionController
from aurora.bridge.player import PlayerController
from aurora.core.config import Config, load_config
from aurora.core.paths import data_file, qml_root


def _configure_engine(
    engine: QQmlApplicationEngine,
    player: PlayerController,
    motion: MotionController,
) -> None:
    engine.addImportPath(str(qml_root()))
    context = engine.rootContext()
    context.setContextProperty("player", player)
    context.setContextProperty("motion", motion)
    engine.load(QUrl.fromLocalFile(str(qml_root() / "Main.qml")))


#: 與 Main.qml 的 minimumWidth / minimumHeight 保持一致。
_MIN_WIDTH = 880
_MIN_HEIGHT = 560


def _restore_window_geometry(config: Config, engine: QQmlApplicationEngine) -> None:
    """把上次的視窗大小與位置套回去，並夾限在螢幕可用範圍內。

    兩件事以前都沒做：

    **沒有還原。** 只在關閉時存、從不讀，每次開啟都回到 Main.qml 寫死的
    1180x760，使用者調過的大小完全留不住。

    **沒有夾限。** 這才是「視窗放大就被截掉」的真正原因。Qt 是 DPI 感知的，
    QML 的尺寸單位是**邏輯**像素；在 125% 縮放的 1920x1080 螢幕上，
    邏輯桌面其實只有 1536x864。視窗一旦高過 864，底部的播放控制列就整個
    掉到螢幕外，而且因為視窗無邊框，使用者連拖回來都很難。
    實測就是這個情況：1442x887 的視窗，底部 23 px 永遠看不到。

    夾限之後，視窗永遠至少完整落在某一個螢幕的工作區內。
    """
    if not engine.rootObjects():
        return
    window = engine.rootObjects()[0]
    geometry = config.window

    screen = None
    if geometry.is_placed:
        screen = QGuiApplication.screenAt(QPoint(geometry.x + 60, geometry.y + 20))
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()

    width = max(_MIN_WIDTH, min(geometry.width, available.width()))
    height = max(_MIN_HEIGHT, min(geometry.height, available.height()))
    window.setProperty("width", width)
    window.setProperty("height", height)

    if not geometry.is_placed:
        return
    x = min(max(geometry.x, available.left()), available.right() - width + 1)
    y = min(max(geometry.y, available.top()), available.bottom() - height + 1)
    window.setProperty("x", x)
    window.setProperty("y", y)


def _save_window_geometry(config: Config, engine: QQmlApplicationEngine) -> None:
    if not engine.rootObjects():
        return
    window = engine.rootObjects()[0]
    # 迷你模式與全螢幕的尺寸是暫時的，存起來會讓下次開啟變成小視窗
    if bool(window.property("miniMode")) or bool(window.property("fullScreen")):
        return
    config.window.x = int(window.property("x"))
    config.window.y = int(window.property("y"))
    config.window.width = int(window.property("width"))
    config.window.height = int(window.property("height"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AURORA 極光播放器")
    parser.add_argument(
        "--validate-qml",
        action="store_true",
        help="只載入並驗證 QML，不開啟音訊裝置。",
    )
    options = parser.parse_args(argv)

    # Qt Quick Controls 在 Windows 上預設走原生樣式，而原生樣式**不允許**
    # 覆寫 background / handle 之類的內部項目 —— 自訂寫了也會被靜靜忽略，
    # 只在主控台留下一行 "The current style does not support customization"。
    # Basic 樣式沒有這個限制，是自繪介面的正確選擇。必須在載入 QML 前設定。
    QQuickStyle.setStyle("Basic")

    app = QGuiApplication(sys.argv[:1])
    app.setWindowIcon(QIcon(str(data_file("aurora-icon.png"))))
    config = load_config()
    player = PlayerController(config)
    motion = MotionController(config)
    engine = QQmlApplicationEngine()
    qml_warnings: list[object] = []
    engine.warnings.connect(qml_warnings.append)
    _configure_engine(engine, player, motion)

    if not engine.rootObjects():
        for warning in qml_warnings:
            print(warning, file=sys.stderr)
        return 1
    if options.validate_qml:
        app.processEvents()
        return 0

    _restore_window_geometry(config, engine)
    player.start()

    def shutdown() -> None:
        _save_window_geometry(config, engine)
        player.shutdown()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
