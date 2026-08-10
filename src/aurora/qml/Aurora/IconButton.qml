import QtQuick
import QtQuick.Shapes

/*!
    向量圖示按鈕。圖形用 Shape 畫，不載入任何圖檔 ——
    打包時少一堆資源，而且可以無級縮放與隨主題染色。

    動效遵守 NN/g 的 0.1 秒界線：hover 與 press 的回饋都在 100–150ms 內完成，
    使用者感受得到「是我點的」而不是「畫面自己在動」。
*/
Item {
    id: root

    /*! 圖示種類：play / pause / prev / next / shuffle / repeat / repeatOne /
        volume / mute / folder / list / lyrics / info / settings / close / minimise / mini / cinema / fullscreen / back */
    property string icon: "play"
    property color color: "#FFFFFF"
    property color glow: "#FFFFFF"
    property real iconScale: 1.0
    property bool active: false
    property bool flat: false
    property string tooltip: ""

    signal clicked()

    implicitWidth: 44
    implicitHeight: 44

    // 圓形底：hover 時亮起 + 微微擴散
    Rectangle {
        id: pad
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        radius: width / 2
        transformOrigin: Item.Center
        color: root.active
               ? Qt.rgba(root.glow.r, root.glow.g, root.glow.b, 0.22)
               : Qt.rgba(1, 1, 1, hover.hovered ? 0.13 : 0.0)
        visible: !root.flat || root.active || hover.hovered
        scale: hover.hovered ? 1.0 : 0.86

        Behavior on color { ColorAnimation { duration: Motion.hover } }
        Behavior on scale {
            NumberAnimation {
                duration: Motion.hover
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Motion.standard
            }
        }
    }

    // 啟用狀態的外光暈
    Rectangle {
        anchors.centerIn: pad
        width: pad.width + 10
        height: pad.height + 10
        radius: width / 2
        transformOrigin: Item.Center
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(root.glow.r, root.glow.g, root.glow.b, 0.45)
        opacity: root.active ? 1.0 : 0.0
        scale: root.active ? 1.0 : 0.8
        Behavior on opacity { NumberAnimation { duration: Motion.icon } }
        Behavior on scale {
            NumberAnimation {
                duration: Motion.icon
                easing.type: Easing.OutBack
                easing.overshoot: Motion.overshoot
            }
        }
    }

    Item {
        id: glyph
        anchors.centerIn: parent
        width: 20 * root.iconScale
        height: 20 * root.iconScale
        transformOrigin: Item.Center
        scale: mouse.pressed ? 0.88 : (hover.hovered ? 1.10 : 1.0)
        opacity: root.active ? 1.0 : (hover.hovered ? 1.0 : 0.82)

        Behavior on scale {
            NumberAnimation {
                duration: mouse.pressed ? Motion.press : Motion.hover
                easing.type: Easing.OutQuad
            }
        }
        Behavior on opacity { NumberAnimation { duration: Motion.hover } }

        // 播放 / 暫停：兩個圖形疊著，用透明度與縮放互相接手，
        // 比真正的路徑變形便宜得多，視覺效果幾乎一樣
        Shape {
            anchors.fill: parent
            visible: root.icon === "play" || root.icon === "pause"
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M4,2 L17,10 L4,18 Z" }
            }
        }
        Row {
            anchors.centerIn: parent
            spacing: 5
            visible: root.icon === "pause"
            Repeater {
                model: 2
                Rectangle {
                    width: 5
                    height: 18
                    radius: 1.5
                    color: root.color
                }
            }
        }

        // 上一首 / 下一首
        Shape {
            anchors.fill: parent
            visible: root.icon === "prev" || root.icon === "next"
            rotation: root.icon === "prev" ? 180 : 0
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M3,3 L13,10 L3,17 Z M14,3 L17,3 L17,17 L14,17 Z" }
            }
        }

        // 隨機
        Shape {
            anchors.fill: parent
            visible: root.icon === "shuffle"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M2,5 L6,5 Q10,5 12,10 Q14,15 18,15" }
            }
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M2,15 L6,15 Q8,15 9.5,12" }
            }
            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M15,12 L19,15 L15,18 Z M15,2 L19,5 L15,8 Z" }
            }
        }

        // 循環 / 單曲循環
        Shape {
            anchors.fill: parent
            visible: root.icon === "repeat" || root.icon === "repeatOne"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M5,6 L14,6 Q17,6 17,9 L17,11" }
            }
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M15,14 L6,14 Q3,14 3,11 L3,9" }
            }
            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M3,7 L6,3 L6,11 Z M17,13 L14,17 L14,9 Z" }
            }
        }
        Text {
            anchors.centerIn: parent
            visible: root.icon === "repeatOne"
            text: "1"
            font.pixelSize: (9) * Appearance.fontScale
            font.bold: true
            color: root.color
        }

        // 資料夾
        Shape {
            anchors.fill: parent
            visible: root.icon === "folder"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.6
                fillColor: "transparent"
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M2,6 L8,6 L10,8 L18,8 L18,16 L2,16 Z" }
            }
        }

        // 清單 / 歌詞 / 資訊：用三條長度不同的橫線表達
        Column {
            anchors.centerIn: parent
            spacing: 4
            visible: root.icon === "list" || root.icon === "lyrics"
            Repeater {
                model: root.icon === "lyrics" ? [18, 12, 16] : [18, 18, 18]
                Rectangle {
                    width: modelData
                    height: 2
                    radius: 1
                    color: root.color
                }
            }
        }

        // 音質資訊：圓框加驚嘆點
        Shape {
            anchors.fill: parent
            visible: root.icon === "info"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                PathAngleArc {
                    centerX: 10; centerY: 10
                    radiusX: 8; radiusY: 8
                    startAngle: 0; sweepAngle: 360
                }
            }
        }
        Column {
            anchors.centerIn: parent
            spacing: 2
            visible: root.icon === "info"
            Rectangle { width: 2; height: 2; radius: 1; color: root.color }
            Rectangle { width: 2; height: 7; radius: 1; color: root.color }
        }

        Shape {
            anchors.fill: parent
            visible: root.icon === "settings"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.7
                fillColor: "transparent"
                PathAngleArc {
                    centerX: 10; centerY: 10
                    radiusX: 5.5; radiusY: 5.5
                    startAngle: 0; sweepAngle: 360
                }
            }
            ShapePath {
                strokeColor: root.color
                strokeWidth: 2.4
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M10,1.8 L10,4 M10,16 L10,18.2 M1.8,10 L4,10 M16,10 L18.2,10 M4.2,4.2 L5.7,5.7 M14.3,14.3 L15.8,15.8 M15.8,4.2 L14.3,5.7 M5.7,14.3 L4.2,15.8" }
            }
        }

        // 視窗控制
        Shape {
            anchors.fill: parent
            visible: root.icon === "close"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.6
                capStyle: ShapePath.RoundCap
                PathSvg { path: "M5,5 L15,15 M15,5 L5,15" }
            }
        }
        Rectangle {
            anchors.centerIn: parent
            visible: root.icon === "minimise"
            width: 11; height: 1.6; radius: 1
            color: root.color
        }
        Shape {
            anchors.fill: parent
            visible: root.icon === "mini"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.6
                fillColor: "transparent"
                PathSvg { path: "M4,11 L4,16 L12,16 L12,11 Z M8,4 L16,4 L16,9 L12,9" }
            }
        }
        Shape {
            anchors.fill: parent
            visible: root.icon === "cinema"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M2,4 L18,4 L18,7 L2,7 Z M2,13 L18,13 L18,16 L2,16 Z" }
            }
        }
        Shape {
            anchors.fill: parent
            visible: root.icon === "fullscreen"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.7
                fillColor: "transparent"
                capStyle: ShapePath.SquareCap
                PathSvg { path: "M3,8 L3,3 L8,3 M12,3 L17,3 L17,8 M17,12 L17,17 L12,17 M8,17 L3,17 L3,12" }
            }
        }
        Shape {
            anchors.fill: parent
            visible: root.icon === "back"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.8
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M11,4 L5,10 L11,16 M5,10 L17,10" }
            }
        }

        // 音量 / 靜音
        Shape {
            anchors.fill: parent
            visible: root.icon === "volume" || root.icon === "mute"
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: root.color
                strokeWidth: -1
                PathSvg { path: "M3,7.5 L6,7.5 L10,4 L10,16 L6,12.5 L3,12.5 Z" }
            }
            ShapePath {
                strokeColor: root.color
                strokeWidth: 1.6
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathSvg {
                    path: root.icon === "mute"
                          ? "M13,7 L18,13 M18,7 L13,13"
                          : "M13,7 Q15.5,10 13,13 M15.5,4.5 Q19.5,10 15.5,15.5"
                }
            }
        }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }

    MouseArea {
        id: mouse
        anchors.fill: parent
        onClicked: root.clicked()
    }
}
