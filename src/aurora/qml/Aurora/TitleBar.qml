import QtQuick

/*!
    自訂標題列。拖曳與縮放一律走 \c Window.startSystemMove / startSystemResize ——
    那是 Qt 提供的原生路徑，能拿到 Windows 的 Aero Snap 與流暢縮放，
    比自己算滑鼠位移好太多。
*/
Item {
    id: root

    property color accent: "#7B2FF7"
    property string presetLabel: "電影"
    property real fps: 0
    property bool showFps: false

    signal minimiseRequested()
    signal miniModeRequested()
    signal closeRequested()
    signal cinemaToggled()
    signal fullscreenToggled()
    signal presetCycled()

    implicitHeight: 46

    // 這裡刻意**沒有**拖曳處理。先前用 Window.window.startSystemMove() 從元件
    // 內部反向抓視窗，解析不到時只會靜靜失敗，結果整個主視窗都拖不動。
    // 拖曳改由 Main.qml 的全視窗拖曳面負責 —— 它在內容下方，按鈕與清單會
    // 先吃掉事件，只有空白處才會落到它身上。

    Row {
        anchors.left: parent.left
        anchors.leftMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10

        // 品牌標記：一個隨主色呼吸的小圓點
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 9; height: 9; radius: 4.5
            color: root.accent
            Behavior on color { ColorAnimation { duration: Motion.palette } }

            SequentialAnimation on opacity {
                running: !Motion.reduced
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 1500; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 1500; easing.type: Easing.InOutSine }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: Strings.appName
            color: "white"
            font.pixelSize: (13) * Appearance.fontScale
            font.letterSpacing: 3.4
            font.weight: Font.DemiBold
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: Strings.appSubtitle
            color: Qt.rgba(1, 1, 1, 0.42)
            font.pixelSize: (11) * Appearance.fontScale
            font.letterSpacing: 1.2
        }
    }

    Row {
        id: windowActions
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.showFps
            text: root.fps.toFixed(0) + " fps"
            color: root.fps < 45 ? "#FF7A6B" : Qt.rgba(1, 1, 1, 0.45)
            font.pixelSize: (10) * Appearance.fontScale
            rightPadding: 8
        }

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: label.width + 18
            height: 22
            radius: 11
            color: Qt.rgba(1, 1, 1, presetHover.hovered ? 0.16 : 0.08)
            Behavior on color { ColorAnimation { duration: Motion.hover } }

            Text {
                id: label
                anchors.centerIn: parent
                text: root.presetLabel
                color: Qt.rgba(1, 1, 1, 0.8)
                font.pixelSize: (10) * Appearance.fontScale
                font.letterSpacing: 0.8
            }
            HoverHandler { id: presetHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: root.presetCycled() }
        }

        Item { width: 8; height: 1 }

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "cinema"; flat: true; width: 34; height: 34; iconScale: 0.8
            color: "white"; glow: root.accent
            onClicked: root.cinemaToggled()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "fullscreen"; flat: true; width: 34; height: 34; iconScale: 0.8
            color: "white"; glow: root.accent
            onClicked: root.fullscreenToggled()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "mini"; flat: true; width: 34; height: 34; iconScale: 0.8
            color: "white"; glow: root.accent
            onClicked: root.miniModeRequested()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "minimise"; flat: true; width: 34; height: 34; iconScale: 0.8
            color: "white"; glow: root.accent
            onClicked: root.minimiseRequested()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "close"; flat: true; width: 34; height: 34; iconScale: 0.8
            color: "white"; glow: "#FF5F57"
            onClicked: root.closeRequested()
        }
    }
}
