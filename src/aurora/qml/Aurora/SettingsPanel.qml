import QtQuick
import QtQuick.Controls

Item {
    id: root

    property var controller: null
    property color accent: "#7B2FF7"
    property bool open: false

    function applyFontScale(requestedScale) {
        const bounded = Math.max(0.8, Math.min(1.35, requestedScale));
        const normalized = Math.round(bounded * 20) / 20;
        fontSlider.value = normalized;
        Appearance.fontScale = normalized;
        if (root.controller && Math.abs(root.controller.fontScale - normalized) > 0.001) {
            root.controller.setFontScale(normalized);
        }
    }

    Component.onCompleted: {
        const initialScale = root.controller ? root.controller.fontScale : Appearance.fontScale;
        root.applyFontScale(initialScale);
    }

    Connections {
        target: root.controller
        function onFontScaleChanged() {
            const savedScale = root.controller.fontScale;
            fontSlider.value = savedScale;
            Appearance.fontScale = savedScale;
        }
    }

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

            Item {
                width: parent.width
                height: Math.max(scaleTitle.implicitHeight, currentLabel.implicitHeight)

                Text {
                    id: scaleTitle
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "介面字體大小"
                    color: "white"
                    font.pixelSize: 15 * Appearance.fontScale
                    font.weight: Font.DemiBold
                }
                Text {
                    id: currentLabel
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: Math.round(fontSlider.value * 100) + "%"
                    color: root.accent
                    font.pixelSize: 13 * Appearance.fontScale
                    font.family: "Consolas"
                    font.weight: Font.DemiBold
                }
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
                height: 40

                Rectangle {
                    id: decreaseButton
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    height: 34
                    radius: 17
                    color: decreaseHover.hovered
                           ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.22)
                           : Qt.rgba(1, 1, 1, 0.08)
                    border.width: 1
                    border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.55)

                    Rectangle {
                        anchors.centerIn: parent
                        width: 12
                        height: 2
                        radius: 1
                        color: "white"
                    }
                    HoverHandler { id: decreaseHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: root.applyFontScale(fontSlider.value - 0.05) }
                }

                Slider {
                    id: fontSlider
                    anchors.left: decreaseButton.right
                    anchors.leftMargin: 12
                    anchors.right: increaseButton.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    from: 0.8
                    to: 1.35
                    stepSize: 0.05
                    snapMode: Slider.SnapAlways
                    live: true
                    value: 1.0
                    onMoved: root.applyFontScale(value)
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

                Rectangle {
                    id: increaseButton
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    height: 34
                    radius: 17
                    color: increaseHover.hovered
                           ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.22)
                           : Qt.rgba(1, 1, 1, 0.08)
                    border.width: 1
                    border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.55)

                    Item {
                        anchors.centerIn: parent
                        width: 12
                        height: 12
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width
                            height: 2
                            radius: 1
                            color: "white"
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: 2
                            height: parent.height
                            radius: 1
                            color: "white"
                        }
                    }
                    HoverHandler { id: increaseHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: root.applyFontScale(fontSlider.value + 0.05) }
                }
            }

            Row {
                width: parent.width
                spacing: 8

                Repeater {
                    model: [0.8, 1.0, 1.2, 1.35]

                    Rectangle {
                        required property real modelData
                        width: (parent.width - parent.spacing * 3) / 4
                        height: 32
                        radius: 8
                        readonly property bool selected:
                            Math.abs(fontSlider.value - modelData) < 0.001
                        color: selected
                               ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.28)
                               : Qt.rgba(1, 1, 1, presetHover.hovered ? 0.11 : 0.055)
                        border.width: 1
                        border.color: selected
                                      ? root.accent
                                      : Qt.rgba(1, 1, 1, 0.12)

                        Text {
                            anchors.centerIn: parent
                            text: Math.round(parent.modelData * 100) + "%"
                            color: parent.selected ? "white" : Qt.rgba(1, 1, 1, 0.62)
                            font.pixelSize: 10 * Appearance.fontScale
                            font.family: "Consolas"
                            font.weight: parent.selected ? Font.DemiBold : Font.Normal
                        }
                        HoverHandler { id: presetHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: root.applyFontScale(parent.modelData) }
                    }
                }
            }
        }
    }
}
