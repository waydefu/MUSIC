import QtQuick

/*! 同步歌詞面板。點選任一行會請 LyricsController 跳轉到該句。 */
Item {
    id: root

    property var controller: null
    property color accent: "#7B2FF7"
    property bool open: false

    visible: opacity > 0.01
    opacity: open ? 1.0 : 0.0
    x: open ? 0 : -parent.width * 0.08 * Motion.travel

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
            text: Strings.lyrics
            color: "white"
            font.pixelSize: 13
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Text {
            anchors.verticalCenter: header.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 18
            text: root.controller && root.controller.hasWordTiming ? "同步" : "LRC"
            color: Qt.rgba(1, 1, 1, 0.42)
            font.pixelSize: 10
            font.letterSpacing: 0.8
        }

        Column {
            anchors.centerIn: parent
            width: parent.width - 52
            spacing: 8
            visible: !root.controller || !root.controller.hasLyrics

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Strings.noLyrics
                color: Qt.rgba(1, 1, 1, 0.60)
                font.pixelSize: 16
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                text: Strings.noLyricsHint
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
            clip: true
            spacing: 6
            model: root.controller ? root.controller.model : null
            currentIndex: root.controller ? root.controller.activeIndex : -1
            highlightRangeMode: ListView.ApplyRange
            preferredHighlightBegin: height * 0.36
            preferredHighlightEnd: height * 0.64

            delegate: Item {
                id: lyricRow
                required property int index
                required property string text

                readonly property bool active: lyricRow.index === list.currentIndex
                width: list.width
                height: lyricText.implicitHeight + 16

                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: lyricRow.active
                           ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.16)
                           : Qt.rgba(1, 1, 1, lyricHover.hovered ? 0.06 : 0.0)
                    Behavior on color { ColorAnimation { duration: Motion.hover } }
                }

                Text {
                    id: lyricText
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.margins: 12
                    text: lyricRow.text
                    wrapMode: Text.Wrap
                    color: lyricRow.active ? "white" : Qt.rgba(1, 1, 1, 0.48)
                    font.pixelSize: lyricRow.active ? 18 : 15
                    font.weight: lyricRow.active ? Font.DemiBold : Font.Normal
                    Behavior on color { ColorAnimation { duration: Motion.component } }
                    Behavior on font.pixelSize { NumberAnimation { duration: Motion.component } }
                }

                HoverHandler { id: lyricHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    onTapped: {
                        if (root.controller)
                            root.controller.seekToLine(lyricRow.index);
                    }
                }
            }

            onCurrentIndexChanged: {
                if (currentIndex >= 0)
                    positionViewAtIndex(currentIndex, ListView.Center);
            }
        }
    }
}
