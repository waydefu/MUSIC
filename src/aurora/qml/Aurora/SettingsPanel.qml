import QtQuick
import QtQuick.Controls

Item {
    id: root

    property var controller: null
    property color accent: "#7B2FF7"
    property bool open: false

    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    x: open ? 0 : parent.width * 0.08 * Motion.travel

    Behavior on opacity { NumberAnimation { duration: Motion.panel } }
    Behavior on x {
        NumberAnimation {
            duration: Motion.panel
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Motion.emphasizedDecelerate
        }
    }

    GlassPanel {
        anchors.fill: parent
        tint: root.accent

        Text {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: 18
            text: Strings.settings
            color: "white"
            font.pixelSize: 13 * Appearance.fontScale
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Column {
            anchors.top: header.bottom
            anchors.topMargin: 24
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            spacing: 10

            Text {
                text: "介面字體大小"
                color: "white"
                font.pixelSize: 15 * Appearance.fontScale
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "調整後立即套用到播放器的文字，設定會在下次開啟時保留。"
                color: Qt.rgba(1, 1, 1, 0.46)
                font.pixelSize: 11 * Appearance.fontScale
                wrapMode: Text.WordWrap
            }

            Item {
                width: parent.width
                height: 36

                Text {
                    id: smallLabel
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "A"
                    color: Qt.rgba(1, 1, 1, 0.58)
                    font.pixelSize: 11 * Appearance.fontScale
                }
                Slider {
                    id: fontSlider
                    anchors.left: smallLabel.right
                    anchors.leftMargin: 12
                    anchors.right: currentLabel.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    from: 0.8
                    to: 1.35
                    stepSize: 0.05
                    snapMode: Slider.SnapAlways
                    live: true
                    value: Appearance.fontScale
                    onValueChanged: {
                        Appearance.fontScale = value;
                        if (root.controller && Math.abs(root.controller.fontScale - value) > 0.001) {
                            root.controller.setFontScale(value);
                        }
                    }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle {
                        x: fontSlider.leftPadding
                        y: fontSlider.topPadding + fontSlider.availableHeight / 2 - height / 2
                        width: fontSlider.availableWidth
                        height: 4
                        radius: 2
                        color: Qt.rgba(1, 1, 1, 0.14)
                        Rectangle {
                            width: fontSlider.visualPosition * parent.width
                            height: parent.height
                            radius: 2
                            color: root.accent
                        }
                    }
                    handle: Rectangle {
                        x: fontSlider.leftPadding + fontSlider.visualPosition * (fontSlider.availableWidth - width)
                        y: fontSlider.topPadding + fontSlider.availableHeight / 2 - height / 2
                        width: 16
                        height: 16
                        radius: 8
                        color: "white"
                        border.width: 3
                        border.color: root.accent
                    }
                }
                Text {
                    id: currentLabel
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: Math.round(Appearance.fontScale * 100) + "%"
                    color: "white"
                    font.pixelSize: 12 * Appearance.fontScale
                    font.family: "Consolas"
                }
            }

            Text {
                text: "80%"
                color: Qt.rgba(1, 1, 1, 0.30)
                font.pixelSize: 10 * Appearance.fontScale
            }
        }
    }
}
