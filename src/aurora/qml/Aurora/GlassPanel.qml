import QtQuick

/*!
    毛玻璃面板。半透明底 + 一圈內光邊 + 頂部高光，讓面板從模糊背景上浮起來。

    刻意不用 MultiEffect 對背景取樣做真實模糊：背景本來就已經是重度模糊的
    封面，再模糊一次視覺上幾乎沒有差別，卻要多一個離屏渲染目標。
*/
Rectangle {
    id: root

    /*! 主題強調色，用來染邊框與高光。 */
    property color tint: "#FFFFFF"
    /*! 面板底色的不透明度。 */
    property real depth: Motion.glassOpacity

    radius: Motion.panelRadius
    color: Qt.rgba(1, 1, 1, root.depth)
    border.width: 1
    border.color: Qt.rgba(
        root.tint.r, root.tint.g, root.tint.b, Motion.glassBorderOpacity)

    Behavior on border.color { ColorAnimation { duration: Motion.palette } }

    // 頂部高光：模擬光線從上方打下來的邊緣反射
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: parent.radius * 0.6
        height: 1
        color: Qt.rgba(1, 1, 1, 0.18)
    }

    // 底部一層極淡的暗邊，強化「厚度」
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: parent.radius * 0.6
        height: 1
        color: Qt.rgba(0, 0, 0, 0.22)
    }
}
