import QtQuick

/*!
    播放清單。從右側滑入，項目逐項錯開淡入。

    stagger 用 delegate 自己的 index 算延遲，不需要外部協調 ——
    每個項目一進場就知道自己該等多久。
*/
Item {
    id: root

    property var model: null
    property int currentIndex: -1
    property color accent: "#7B2FF7"
    property bool open: false

    signal activated(int row)
    signal removed(int row)

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
            text: Strings.playlist
            color: "white"
            font.pixelSize: 13
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Text {
            anchors.verticalCenter: header.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 18
            text: list.count + " 首"
            color: Qt.rgba(1, 1, 1, 0.4)
            font.pixelSize: 11
        }

        // 空狀態
        Column {
            anchors.centerIn: parent
            spacing: 8
            visible: list.count === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.emptyPlaylist
                color: Qt.rgba(1, 1, 1, 0.55)
                font.pixelSize: 15
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.emptyPlaylistHint
                color: Qt.rgba(1, 1, 1, 0.3)
                font.pixelSize: 11
                font.letterSpacing: 0.8
            }
        }

        ListView {
            id: list
            anchors.top: header.bottom
            anchors.topMargin: 12
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 8
            anchors.bottomMargin: 12
            model: root.model
            clip: true
            spacing: 2
            currentIndex: root.currentIndex

            delegate: Item {
                id: row
                required property int index
                required property string title
                required property string artist
                required property string duration
                required property bool lossless

                readonly property bool isCurrent: index === root.currentIndex

                width: list.width
                height: 52

                // 逐項錯開淡入
                opacity: 0
                x: 18 * Motion.travel
                Component.onCompleted: entry.start()

                SequentialAnimation {
                    id: entry
                    // 只讓前 20 項錯開 —— 上千首的清單不該讓最後一項等好幾秒
                    PauseAnimation {
                        duration: Math.min(row.index, 20) * Motion.stagger
                    }
                    ParallelAnimation {
                        NumberAnimation {
                            target: row; property: "opacity"; to: 1
                            duration: Motion.component
                            easing.type: Easing.OutQuad
                        }
                        NumberAnimation {
                            target: row; property: "x"; to: 0
                            duration: Motion.component
                            easing.type: Easing.BezierSpline
                            easing.bezierCurve: Motion.emphasizedDecelerate
                        }
                    }
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 2
                    radius: 8
                    color: row.isCurrent
                           ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.16)
                           : Qt.rgba(1, 1, 1, hover.hovered ? 0.07 : 0.0)
                    Behavior on color { ColorAnimation { duration: Motion.hover } }
                }

                // 目前播放項的左側光條，帶微脈動
                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: 3
                    height: row.isCurrent ? 30 : 0
                    radius: 1.5
                    color: root.accent

                    Behavior on height {
                        NumberAnimation {
                            duration: Motion.component
                            easing.type: Easing.OutBack
                            easing.overshoot: Motion.overshoot
                        }
                    }
                    SequentialAnimation on opacity {
                        running: row.isCurrent && !Motion.reduced
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.45; duration: 900
                                          easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 900
                                          easing.type: Easing.InOutSine }
                    }
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 18 + (hover.hovered ? 4 : 0)
                    anchors.right: meta.left
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Behavior on anchors.leftMargin {
                        NumberAnimation { duration: Motion.hover }
                    }

                    Text {
                        width: parent.width
                        text: row.title
                        color: row.isCurrent ? root.accent : "white"
                        font.pixelSize: 13
                        font.weight: row.isCurrent ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                        Behavior on color { ColorAnimation { duration: Motion.hover } }
                    }
                    Text {
                        width: parent.width
                        text: row.artist
                        color: Qt.rgba(1, 1, 1, 0.42)
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }

                Row {
                    id: meta
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: row.lossless
                        width: 34; height: 16; radius: 8
                        color: Qt.rgba(1, 1, 1, 0.10)
                        Text {
                            anchors.centerIn: parent
                            text: "無損"
                            color: Qt.rgba(1, 1, 1, 0.6)
                            font.pixelSize: 9
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.duration
                        color: Qt.rgba(1, 1, 1, 0.42)
                        font.pixelSize: 11
                        font.family: "Consolas"
                        visible: !hover.hovered
                    }

                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: hover.hovered
                        icon: "close"
                        flat: true
                        width: 26; height: 26; iconScale: 0.6
                        color: Qt.rgba(1, 1, 1, 0.7)
                        glow: "#FF5F57"
                        onClicked: root.removed(row.index)
                    }
                }

                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.activated(row.index) }
            }
        }
    }
}
