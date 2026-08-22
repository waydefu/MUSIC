import QtQuick

/*!
    文字太長時緩慢往復捲動的跑馬燈。裝得下就完全不動 ——
    不必要的動態是干擾，Apple HIG 與 NN/g 都這麼說。

    **關掉動態時要改用刪節號，不能只是硬切。** 兩側的淡出遮罩是在說
    「還有更多，等它捲過來」；但 reduce motion 開啟時它永遠不會捲，
    這時淡出就變成了謊言，使用者只會覺得字被切壞了。所以不捲的時候
    改用 ElideRight —— 刪節號誠實地表示「就到這裡，沒有下文」。
*/
Item {
    id: root

    property string text: ""
    property color color: "white"
    property alias font: label.font
    property int gap: 48

    readonly property bool overflowing: label.implicitWidth > width
    /*! 是否真的會捲動。裝不下**且**沒有關掉動態時才成立。 */
    readonly property bool scrolling: overflowing && !Motion.reduced

    clip: true
    implicitHeight: label.implicitHeight

    Text {
        id: label
        text: root.text
        color: root.color
        // 會捲就讓它自然長；不捲就夾在容器寬度內並顯示刪節號。
        width: root.scrolling ? implicitWidth : root.width
        elide: root.scrolling ? Text.ElideNone : Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter

        SequentialAnimation on x {
            running: root.overflowing && !Motion.reduced
            loops: Animation.Infinite
            PauseAnimation { duration: 1800 }
            NumberAnimation {
                to: root.width - label.implicitWidth - root.gap
                duration: Math.max(2600, label.implicitWidth * 14)
                easing.type: Easing.InOutSine
            }
            PauseAnimation { duration: 1200 }
            NumberAnimation {
                to: 0
                duration: Math.max(2600, label.implicitWidth * 14)
                easing.type: Easing.InOutSine
            }
        }

        // 不捲動時固定貼齊左緣
        Binding on x {
            when: !root.overflowing || Motion.reduced
            value: 0
        }
    }

    // 兩側淡出遮罩，讓文字是「淡出」而不是被硬切
    Rectangle {
        anchors.right: parent.right
        width: 32
        height: parent.height
        visible: root.scrolling
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.55) }
        }
    }
}
