"""AURORA 的 Qt 應用程式進入點。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

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


def _save_window_geometry(config: Config, engine: QQmlApplicationEngine) -> None:
    if not engine.rootObjects():
        return
    window = engine.rootObjects()[0]
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

    player.start()

    def shutdown() -> None:
        _save_window_geometry(config, engine)
        player.shutdown()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
