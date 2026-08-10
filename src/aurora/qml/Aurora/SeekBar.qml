import QtQuick

/*!
    進度條。滑過時變粗並浮出時間預覽氣泡，拖曳時把手放大。

    刻意不用 QtQuick.Controls 的 Slider：它的樣式覆寫成本比自己畫還高，
    而且我們要的 hover 預覽與發光把手都不在它的模型裡。
*/
Item {
    id: root

    property real progress: 0.0
    property real duration: 0.0
    property color accent: "#7B2FF7"
    property color accent2: "#F76B2F"

    signal seekRequested(real fraction)

    implicitHeight: 28

    readonly property real _hoverFraction:
        Math.max(0, Math.min(1, (hover.point.position.x - track.x) / track.width))
    readonly property bool _active: hover.hovered || drag.active

    function _clock(seconds) {
        if (!isFinite(seconds) || seconds < 0) {
            return "0:00";
        }
        const total = Math.floor(seconds);
        const secs = total % 60;
        return Math.floor(total / 60) + ":" + (secs < 10 ? "0" : "") + secs;
    }

    // 軌道
    Rectangle {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: root._active ? 6 : 4
        radius: height / 2
        color: Qt.rgba(1, 1, 1, 0.14)

        Behavior on height {
            NumberAnimation { duration: Motion.hover; easing.type: Easing.OutQuad }
        }

        // 已播放部分
        Rectangle {
            width: track.width * root.progress
            height: parent.height
            radius: height / 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: root.accent }
                GradientStop { position: 1.0; color: root.accent2 }
            }
        }

        // hover 位置的預覽填色
        Rectangle {
            visible: hover.hovered && !drag.active
            x: 0
            width: track.width * root._hoverFraction
            height: parent.height
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.12)
        }
    }

    // 把手：發光圓點
    Rectangle {
        id: knob
        x: track.width * root.progress - width / 2
        anchors.verticalCenter: track.verticalCenter
        width: root._active ? 14 : 10
        height: width
        radius: width / 2
        color: "white"
        scale: drag.active ? 1.2 : 1.0

        Behavior on width {
            NumberAnimation { duration: Motion.hover; easing.type: Easing.OutQuad }
        }
        Behavior on scale {
            NumberAnimation {
                duration: Motion.press
                easing.type: Easing.OutBack
                easing.overshoot: Motion.overshoot
            }
        }

        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 12
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.5)
            opacity: root._active ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: Motion.hover } }
        }
    }

    // 時間預覽氣泡
    Rectangle {
        id: bubble
        visible: opacity > 0.01
        opacity: hover.hovered && !drag.active ? 1.0 : 0.0
        x: Math.max(0, Math.min(root.width - width,
                                track.width * root._hoverFraction - width / 2))
        y: -height - 8
        width: preview.width + 16
        height: preview.height + 8
        radius: 6
        color: Qt.rgba(0, 0, 0, 0.72)
        border.width: 1
        border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.4)

        Behavior on opacity { NumberAnimation { duration: Motion.hover } }

        Text {
            id: preview
            anchors.centerIn: parent
            text: root._clock(root._hoverFraction * root.duration)
            color: "white"
            font.pixelSize: 11
            font.letterSpacing: 0.5
        }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }

    DragHandler {
        id: drag
        target: null
        xAxis.enabled: true
        yAxis.enabled: false
        onCentroidChanged: {
            if (active) {
                root.seekRequested(Math.max(0, Math.min(1,
                    (drag.centroid.position.x - track.x) / track.width)));
            }
        }
    }

    TapHandler {
        onTapped: (point) => {
            root.seekRequested(Math.max(0, Math.min(1,
                (point.position.x - track.x) / track.width)));
        }
    }
}
