import QtQuick

/*! 音量滑桿。拖曳時把手放大並浮出百分比氣泡。 */
Row {
    id: root

    property real value: 0.8
    property bool muted: false
    property color accent: "#7B2FF7"

    signal volumeChanged(real value)
    signal muteToggled()

    spacing: 8

    IconButton {
        anchors.verticalCenter: parent.verticalCenter
        icon: root.muted || root.value <= 0.001 ? "mute" : "volume"
        color: "white"
        glow: root.accent
        flat: true
        width: 34
        height: 34
        iconScale: 0.85
        onClicked: root.muteToggled()
    }

    Item {
        id: slider
        width: 90
        height: 34
        anchors.verticalCenter: parent.verticalCenter

        readonly property bool active: hover.hovered || drag.active
        readonly property real shown: root.muted ? 0.0 : root.value

        Rectangle {
            id: track
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: slider.active ? 5 : 3
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.14)
            Behavior on height { NumberAnimation { duration: Motion.hover } }

            Rectangle {
                width: track.width * slider.shown
                height: parent.height
                radius: height / 2
                color: root.accent
                Behavior on width { NumberAnimation { duration: Motion.short2 } }
                Behavior on color { ColorAnimation { duration: Motion.palette } }
            }
        }

        Rectangle {
            x: track.width * slider.shown - width / 2
            anchors.verticalCenter: track.verticalCenter
            width: slider.active ? 12 : 8
            height: width
            radius: width / 2
            color: "white"
            Behavior on width { NumberAnimation { duration: Motion.hover } }
            Behavior on x { NumberAnimation { duration: Motion.short2 } }
        }

        Rectangle {
            visible: opacity > 0.01
            opacity: slider.active ? 1.0 : 0.0
            x: Math.max(0, Math.min(slider.width - width,
                                    track.width * slider.shown - width / 2))
            y: -22
            width: 38
            height: 20
            radius: 5
            color: Qt.rgba(0, 0, 0, 0.72)
            Behavior on opacity { NumberAnimation { duration: Motion.hover } }
            Text {
                anchors.centerIn: parent
                text: Math.round(slider.shown * 100) + "%"
                color: "white"
                font.pixelSize: (10) * Appearance.fontScale
            }
        }

        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }

        DragHandler {
            id: drag
            target: null
            yAxis.enabled: false
            onCentroidChanged: {
                if (active) {
                    root.volumeChanged(Math.max(0, Math.min(1,
                        drag.centroid.position.x / track.width)));
                }
            }
        }

        TapHandler {
            onTapped: (point) => root.volumeChanged(
                Math.max(0, Math.min(1, point.position.x / track.width)))
        }
    }
}
