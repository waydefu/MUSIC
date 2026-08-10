import QtQuick
import QtQuick.Shapes

/*!
    播放控制列。中央的播放鍵較大並帶主色光暈，是視線的落點。

    播放／暫停不做真正的路徑變形，而是讓兩個圖形以縮放＋旋轉＋透明度
    互相接手 —— 視覺上同樣連續，但成本是路徑插值的一小部分，
    而且完全走宣告式 Behavior，不需要每幀跑 JavaScript。
*/
Row {
    id: root

    property bool playing: false
    property bool shuffle: false
    property string repeatMode: "off"
    property color accent: "#7B2FF7"
    property real energy: 0.0

    signal previousRequested()
    signal playToggled()
    signal nextRequested()
    signal shuffleToggled()
    signal repeatCycled()

    spacing: 10

    IconButton {
        anchors.verticalCenter: parent.verticalCenter
        icon: "shuffle"
        color: root.shuffle ? root.accent : "white"
        glow: root.accent
        active: root.shuffle
        flat: true
        width: 38; height: 38
        iconScale: 0.8
        onClicked: root.shuffleToggled()
    }

    IconButton {
        anchors.verticalCenter: parent.verticalCenter
        icon: "prev"
        color: "white"
        glow: root.accent
        flat: true
        width: 44; height: 44
        onClicked: root.previousRequested()
    }

    Item {
        id: playButton
        width: 62
        height: 62
        anchors.verticalCenter: parent.verticalCenter

        // 隨音量脈動的光暈環
        Rectangle {
            anchors.centerIn: parent
            width: parent.width + 8 + root.energy * 14
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 1.5
            border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b,
                                  0.18 + root.energy * 0.32)
            visible: root.playing && !Motion.reduced
            Behavior on width { NumberAnimation { duration: Motion.short3 } }
        }

        Rectangle {
            id: disc
            anchors.fill: parent
            radius: width / 2
            scale: press.pressed ? 0.93 : (playHover.hovered ? 1.05 : 1.0)
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.lighter(root.accent, 1.35) }
                GradientStop { position: 1.0; color: Qt.darker(root.accent, 1.15) }
            }

            Behavior on scale {
                NumberAnimation {
                    duration: press.pressed ? Motion.press : Motion.hover
                    easing.type: Easing.OutBack
                    easing.overshoot: Motion.overshoot
                }
            }

            // 播放三角形
            Shape {
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: 2
                width: 22; height: 24
                preferredRendererType: Shape.CurveRenderer

                opacity: root.playing ? 0.0 : 1.0
                scale: root.playing ? 0.55 : 1.0
                rotation: root.playing ? -90 : 0

                Behavior on opacity { NumberAnimation { duration: Motion.icon } }
                Behavior on rotation { NumberAnimation { duration: Motion.icon } }
                Behavior on scale {
                    NumberAnimation {
                        duration: Motion.icon
                        easing.type: Easing.OutBack
                        easing.overshoot: Motion.overshoot
                    }
                }

                ShapePath {
                    fillColor: "white"
                    strokeWidth: -1
                    PathSvg { path: "M2,1 L21,12 L2,23 Z" }
                }
            }

            // 暫停雙豎線
            Row {
                anchors.centerIn: parent
                spacing: 6
                opacity: root.playing ? 1.0 : 0.0
                scale: root.playing ? 1.0 : 0.55
                rotation: root.playing ? 0 : 90

                Behavior on opacity { NumberAnimation { duration: Motion.icon } }
                Behavior on rotation { NumberAnimation { duration: Motion.icon } }
                Behavior on scale {
                    NumberAnimation {
                        duration: Motion.icon
                        easing.type: Easing.OutBack
                        easing.overshoot: Motion.overshoot
                    }
                }

                Repeater {
                    model: 2
                    Rectangle { width: 6; height: 22; radius: 2; color: "white" }
                }
            }

            HoverHandler { id: playHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { id: press; onTapped: root.playToggled() }
        }
    }

    IconButton {
        anchors.verticalCenter: parent.verticalCenter
        icon: "next"
        color: "white"
        glow: root.accent
        flat: true
        width: 44; height: 44
        onClicked: root.nextRequested()
    }

    IconButton {
        anchors.verticalCenter: parent.verticalCenter
        icon: root.repeatMode === "one" ? "repeatOne" : "repeat"
        color: root.repeatMode === "off" ? "white" : root.accent
        glow: root.accent
        active: root.repeatMode !== "off"
        flat: true
        width: 38; height: 38
        iconScale: 0.8
        onClicked: root.repeatCycled()
    }
}
