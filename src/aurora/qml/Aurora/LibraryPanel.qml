import QtQuick

Item {
    id: root

    property var controller: null
    property color accent: "#7B2FF7"
    property bool open: false

    signal pickFolderRequested()
    signal activated(string folder)

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
            text: Strings.library
            color: "white"
            font.pixelSize: 13
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: header.verticalCenter
            text: "+ 資料夾"
            color: root.accent
            font.pixelSize: 11
            font.weight: Font.DemiBold
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.pickFolderRequested() }
        }

        Column {
            anchors.centerIn: parent
            width: parent.width - 48
            spacing: 8
            visible: list.count === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "尚未加入音樂資料夾"
                color: Qt.rgba(1, 1, 1, 0.60)
                font.pixelSize: 16
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                text: "加入後，每個子資料夾都會成為一張歌單"
                color: Qt.rgba(1, 1, 1, 0.34)
                font.pixelSize: 11
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }

        ListView {
            id: list
            anchors.top: header.bottom
            anchors.topMargin: 12
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 12
            anchors.bottomMargin: 16
            model: root.controller ? root.controller.libraryPlaylists : []
            clip: true
            spacing: 4

            delegate: Item {
                id: entry
                required property var modelData
                width: list.width
                height: 58
                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: Qt.rgba(1, 1, 1, hover.hovered ? 0.08 : 0.035)
                    Behavior on color { ColorAnimation { duration: Motion.hover } }
                }
                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 12
                    spacing: 3
                    Text {
                        width: parent.width
                        text: entry.modelData.label
                        color: "white"
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: entry.modelData.count + " 首 · " + entry.modelData.path
                        color: Qt.rgba(1, 1, 1, 0.42)
                        font.pixelSize: 10
                        elide: Text.ElideMiddle
                    }
                }
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.activated(entry.modelData.path) }
            }
        }
    }
}
