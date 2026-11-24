"""Offscreen keyboard/accessibility smoke test for the production IconButton.

Run in a separate QGuiApplication process, never inside the QCoreApplication
unit-test process. This checks interaction semantics, not pixel-identical
appearance, GPU shaders, or platform accessibility integration.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from aurora.core.paths import qml_root

QML = b"""
import QtQuick
import QtQuick.Window
import Aurora

Window {
    id: window
    width: 320
    height: 240
    visible: true
    property int activations: 0

    IconButton {
        objectName: "testButton"
        anchors.centerIn: parent
        width: 44
        height: 44
        icon: "play"
        tooltip: "Play"
        onClicked: window.activations++
    }
}
"""


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(qml_root()))
    warnings: list[object] = []
    engine.warnings.connect(warnings.extend)
    engine.loadData(QML, QUrl.fromLocalFile(str(qml_root() / "InteractionHarness.qml")))
    roots = engine.rootObjects()
    if not roots or not isinstance(roots[0], QQuickWindow):
        raise RuntimeError(f"Cannot load interaction harness: {warnings}")
    window = roots[0]
    button = window.findChild(QQuickItem, "testButton")
    if button is None:
        raise RuntimeError("IconButton not found")
    try:
        app.processEvents()
        QTest.qWait(100)
        assert button.property("activeFocusOnTab"), "IconButton must be in keyboard tab order"
        button.forceActiveFocus()
        app.processEvents()
        assert button.hasActiveFocus(), "IconButton must accept keyboard focus"
        for count, key in enumerate((Qt.Key.Key_Space, Qt.Key.Key_Return), start=1):
            QTest.keyClick(window, key)
            app.processEvents()
            assert window.property("activations") == count, "Key must activate exactly once"

        button.setEnabled(False)
        QTest.keyClick(window, Qt.Key.Key_Space)
        app.processEvents()
        assert window.property("activations") == 2, "Disabled button must not activate"
        assert not warnings, f"QML runtime warnings: {warnings}"
    finally:
        window.close()
        app.processEvents()
    print("QML keyboard interaction gate PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

