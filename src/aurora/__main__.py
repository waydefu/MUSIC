"""AURORA 的 Qt 應用程式進入點。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QUrl
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


def _restore_window_geometry(config: Config, engine: QQmlApplicationEngine) -> None:
    """把上次的視窗大小與位置套回去。

    先前只有存、沒有讀，所以每次開啟都回到 Main.qml 寫死的 1180x760，
    使用者調過的大小完全留不住。

    位置要驗證還在某個螢幕上：外接螢幕拔掉後，舊座標會讓視窗開在
    看不見的地方，使用者只會覺得「程式打不開」。
    """
    if not engine.rootObjects():
        return
    window = engine.rootObjects()[0]
    geometry = config.window

    window.setProperty("width", geometry.width)
    window.setProperty("height", geometry.height)

    if not geometry.is_placed:
        return
    for screen in QGuiApplication.screens():
        available = screen.availableGeometry()
        # 只要標題列還看得到就算有效，不必整個視窗都在螢幕內
        if available.contains(geometry.x + 60, geometry.y + 20):
            window.setProperty("x", geometry.x)
            window.setProperty("y", geometry.y)
            return


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
