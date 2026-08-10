import QtQuick

/*! 可追溯的訊號鏈與頻譜量測結果。所有判斷均由 QualityController 提供。 */
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
            text: Strings.quality
            color: "white"
            font.pixelSize: (13) * Appearance.fontScale
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: header.verticalCenter
            text: root.controller ? "★".repeat(root.controller.stars) : ""
            color: root.accent
            font.pixelSize: (15) * Appearance.fontScale
            font.letterSpacing: 1
        }

        Flickable {
            id: scroll
            anchors.top: header.bottom
            anchors.topMargin: 12
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 14
            anchors.bottomMargin: 16
            contentWidth: width
            contentHeight: content.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: content
                width: scroll.width
                spacing: 12

                Rectangle {
                    width: parent.width
                    height: deviceColumn.implicitHeight + 24
                    radius: 10
                    color: Qt.rgba(1, 1, 1, 0.055)

                    Column {
                        id: deviceColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 12
                        spacing: 4
                        Text {
                            width: parent.width
                            text: root.controller ? root.controller.deviceName : "—"
                            color: "white"
                            font.pixelSize: (15) * Appearance.fontScale
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            text: root.controller
                                  ? root.controller.transportLabel + " · " + root.controller.endpointFormat
                                  : "—"
                            color: Qt.rgba(1, 1, 1, 0.48)
                            font.pixelSize: (11) * Appearance.fontScale
                        }
                    }
                }

                Text {
                    text: Strings.signalChain
                    color: Qt.rgba(1, 1, 1, 0.58)
                    font.pixelSize: (10) * Appearance.fontScale
                    font.letterSpacing: 1.2
                    font.weight: Font.DemiBold
                }

                Repeater {
                    model: root.controller ? root.controller.stages : []
                    delegate: Rectangle {
                        required property var modelData
                        width: content.width
                        height: stageRow.implicitHeight + 16
                        radius: 8
                        color: modelData.warn
                               ? Qt.rgba(1, 0.34, 0.25, 0.13)
                               : Qt.rgba(1, 1, 1, 0.045)

                        Row {
                            id: stageRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 10
                            spacing: 8
                            Rectangle {
                                width: 6; height: 6; radius: 3
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData.warn ? "#FF7668" : root.accent
                            }
                            Column {
                                width: parent.width - 14
                                spacing: 2
                                Text {
                                    width: parent.width
                                    text: modelData.label
                                    color: "white"
                                    font.pixelSize: (12) * Appearance.fontScale
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: modelData.detail + " · " + modelData.badge
                                    color: Qt.rgba(1, 1, 1, 0.45)
                                    font.pixelSize: (11) * Appearance.fontScale
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }

                Text {
                    visible: root.controller && root.controller.measurementProgress !== ""
                    text: root.controller ? root.controller.measurementProgress : ""
                    color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.86)
                    font.pixelSize: (11) * Appearance.fontScale
                }

                Repeater {
                    model: root.controller ? root.controller.warnings : []
                    delegate: Rectangle {
                        required property string modelData
                        width: content.width
                        height: warning.implicitHeight + 18
                        radius: 8
                        color: Qt.rgba(1, 0.34, 0.25, 0.15)
                        Text {
                            id: warning
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 10
                            text: modelData
                            color: "#FFB1A8"
                            font.pixelSize: (11) * Appearance.fontScale
                            wrapMode: Text.Wrap
                        }
                    }
                }

                Column {
                    width: parent.width
                    spacing: 5
                    visible: root.controller && root.controller.codecReasons.length > 0
                    Text {
                        text: Strings.codecReasons
                        color: Qt.rgba(1, 1, 1, 0.58)
                        font.pixelSize: (10) * Appearance.fontScale
                        font.letterSpacing: 1.2
                        font.weight: Font.DemiBold
                    }
                    Repeater {
                        model: root.controller ? root.controller.codecReasons : []
                        delegate: Text {
                            required property string modelData
                            width: parent.width
                            text: "• " + modelData
                            color: Qt.rgba(1, 1, 1, 0.42)
                            font.pixelSize: (11) * Appearance.fontScale
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
