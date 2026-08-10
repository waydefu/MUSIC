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
    property string currentPath: ""
    property color accent: "#7B2FF7"
    property bool open: false
    property bool canGoBack: false

    signal activated(int row)
    signal removed(int row)
    signal searchChanged(string query)
    signal backRequested()

    function clearSearch() {
        searchInput.text = "";
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
            anchors.topMargin: 18
            anchors.leftMargin: root.canGoBack ? 54 : 18
            text: Strings.playlist
            color: "white"
            font.pixelSize: (13) * Appearance.fontScale
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        IconButton {
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: header.verticalCenter
            visible: root.canGoBack
            icon: "back"
            flat: true
            width: 30; height: 30; iconScale: 0.72
            color: "white"; glow: root.accent
            onClicked: root.backRequested()
        }

        Text {
            anchors.verticalCenter: header.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 18
            text: list.count + " 首"
            color: Qt.rgba(1, 1, 1, 0.4)
            font.pixelSize: (11) * Appearance.fontScale
        }

        Rectangle {
            id: searchBox
            anchors.top: header.bottom
            anchors.topMargin: 12
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 14
            height: 34
            radius: 8
            color: Qt.rgba(1, 1, 1, 0.075)
            border.width: searchInput.activeFocus ? 1 : 0
            border.color: root.accent
            HoverHandler { cursorShape: Qt.IBeamCursor }
            Text {
                anchors.left: parent.left; anchors.leftMargin: 11
                anchors.verticalCenter: parent.verticalCenter
                text: "⌕"; color: root.accent; font.pixelSize: 19 * Appearance.fontScale
            }
            TextInput {
                id: searchInput
                anchors.left: parent.left; anchors.leftMargin: 35
                anchors.right: clearSearch.left; anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                color: "white"; font.pixelSize: 12 * Appearance.fontScale; clip: true; selectByMouse: true
                onTextChanged: root.searchChanged(text)
                Keys.onEscapePressed: {
                    if (text.length > 0) { text = ""; event.accepted = true; }
                }
            }
            Text {
                anchors.left: searchInput.left; anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text.length === 0
                text: "搜尋歌曲、演出者或專輯"
                color: Qt.rgba(1, 1, 1, 0.34); font.pixelSize: 12 * Appearance.fontScale
            }
            Text {
                id: clearSearch
                anchors.right: parent.right; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text.length > 0
                text: "×"; color: Qt.rgba(1, 1, 1, 0.65); font.pixelSize: 18 * Appearance.fontScale
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: searchInput.text = "" }
            }
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
                font.pixelSize: (15) * Appearance.fontScale
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.emptyPlaylistHint
                color: Qt.rgba(1, 1, 1, 0.3)
                font.pixelSize: (11) * Appearance.fontScale
                font.letterSpacing: 0.8
            }
        }

        ListView {
            id: list
            anchors.top: searchBox.bottom
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
                required property string path
                required property string title
                required property string artist
                required property string duration
                required property bool lossless

                readonly property bool isCurrent: path === root.currentPath

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
                        font.pixelSize: (13) * Appearance.fontScale
                        font.weight: row.isCurrent ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                        Behavior on color { ColorAnimation { duration: Motion.hover } }
                    }
                    Text {
                        width: parent.width
                        text: row.artist
                        color: Qt.rgba(1, 1, 1, 0.42)
                        font.pixelSize: (11) * Appearance.fontScale
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
                            font.pixelSize: (9) * Appearance.fontScale
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.duration
                        color: Qt.rgba(1, 1, 1, 0.42)
                        font.pixelSize: (11) * Appearance.fontScale
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
