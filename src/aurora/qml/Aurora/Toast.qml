import QtQuick

/*! 從頂端滑入的短暫提示。訊息用佇列，避免連續事件互相蓋掉。 */
Item {
    id: root

    property color accent: "#7B2FF7"
    property int holdMs: 2600

    property var _queue: []
    property string _current: ""
    property bool _warning: false

    function show(message, warning) {
        _queue.push({ text: message, warning: warning === true });
        if (!bubble.visible) {
            _next();
        }
    }

    function _next() {
        if (_queue.length === 0) {
            _current = "";
            return;
        }
        const item = _queue.shift();
        _current = item.text;
        _warning = item.warning;
        sequence.restart();
    }

    implicitHeight: bubble.height

    Rectangle {
        id: bubble
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(root.width - 40, message.implicitWidth + 34)
        height: 38
        radius: 19
        visible: opacity > 0.01
        opacity: 0
        y: -height

        color: Qt.rgba(0.04, 0.04, 0.06, 0.88)
        border.width: 1
        border.color: root._warning
                      ? Qt.rgba(1, 0.45, 0.35, 0.6)
                      : Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.45)

        Row {
            anchors.centerIn: parent
            spacing: 8

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 6; height: 6; radius: 3
                color: root._warning ? "#FF7A6B" : root.accent

                SequentialAnimation on scale {
                    running: root._warning && bubble.visible && !Motion.reduced
                    loops: Animation.Infinite
                    NumberAnimation { to: 1.7; duration: 480; easing.type: Easing.OutQuad }
                    NumberAnimation { to: 1.0; duration: 480; easing.type: Easing.InQuad }
                }
            }

            Text {
                id: message
                anchors.verticalCenter: parent.verticalCenter
                text: root._current
                color: "white"
                font.pixelSize: (12) * Appearance.fontScale
                elide: Text.ElideRight
                width: Math.min(implicitWidth, root.width - 80)
            }
        }
    }

    SequentialAnimation {
        id: sequence

        ParallelAnimation {
            NumberAnimation {
                target: bubble; property: "opacity"
                to: 1.0; duration: Motion.component
            }
            NumberAnimation {
                target: bubble; property: "y"
                to: 0; duration: Motion.component
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Motion.emphasizedDecelerate
            }
        }
        PauseAnimation { duration: root.holdMs }
        ParallelAnimation {
            NumberAnimation {
                target: bubble; property: "opacity"
                to: 0.0; duration: Motion.short4
            }
            NumberAnimation {
                target: bubble; property: "y"
                to: -bubble.height * 0.6; duration: Motion.short4
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Motion.emphasizedAccelerate
            }
        }
        ScriptAction { script: root._next() }
    }
}
