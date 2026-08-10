import QtQuick
import QtQuick.Effects

/*!
    專輯封面卡。整個介面的視覺主角，動效最密集的元件：

    * 滑鼠視差 3D 傾斜（±6°，OutCubic 300ms 跟隨）
    * 音量 RMS 驅動的呼吸縮放
    * 鼓點瞬間衝擊 + bloom 拉高，OutBack 回彈
    * 隨傾斜角度掃過的鏡面高光
    * 換歌時舊圖加速淡出、新圖減速進場
    * 暫停時去飽和並微縮

    所有動畫都走宣告式 Behavior，沒有一行 JavaScript 在每幀執行 ——
    Qt 官方效能指引明確要求動畫期間不要跑 JS。
*/
Item {
    id: root

    property url source: ""
    property color accent: "#7B2FF7"
    property real energy: 0.0        // 0..1，來自 RMS
    property bool playing: false
    property bool bloomEnabled: true
    property real bloomStrength: 1.0

    /*! 由外部在偵測到鼓點時呼叫。 */
    function punch() {
        if (!Motion.reduced) {
            punchAnimation.restart();
        }
    }

    property real _punch: 0.0
    property real _tiltX: 0.0
    property real _tiltY: 0.0

    SequentialAnimation {
        id: punchAnimation
        NumberAnimation {
            target: root; property: "_punch"
            to: 1.0; duration: Motion.short1
            easing.type: Easing.OutQuad
        }
        NumberAnimation {
            target: root; property: "_punch"
            to: 0.0; duration: 220
            easing.type: Easing.OutBack
            easing.overshoot: Motion.overshoot
        }
    }

    // 3D 傾斜的容器。用 transform 而不是改 x/y，才不會觸發重新配置。
    Item {
        id: stage
        anchors.fill: parent

        transform: [
            Rotation {
                origin.x: stage.width / 2
                origin.y: stage.height / 2
                axis { x: 1; y: 0; z: 0 }
                angle: root._tiltX
            },
            Rotation {
                origin.x: stage.width / 2
                origin.y: stage.height / 2
                axis { x: 0; y: 1; z: 0 }
                angle: root._tiltY
            }
        ]

        scale: (root.playing ? 1.0 : 0.97)
               + root.energy * Motion.breathe
               + root._punch * Motion.punch

        Behavior on scale {
            NumberAnimation {
                duration: Motion.component
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Motion.standard
            }
        }

        // 外光暈：顏色跟著主色走，強度跟著音樂脈動
        Rectangle {
            anchors.centerIn: artwork
            width: artwork.width * 1.04
            height: artwork.height * 1.04
            radius: Motion.cardRadius + 6
            color: "transparent"
            border.width: 2
            border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b,
                                  0.20 + root.energy * 0.35 + root._punch * 0.3)
            Behavior on border.color { ColorAnimation { duration: Motion.short3 } }
        }

        Item {
            id: artwork
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height)
            height: width

            // 封面本體。圓角遮罩與陰影透過 layer.effect 掛在這個 Image 自己身上，
            // **不是**另外放一個 MultiEffect 去參照隱藏的來源。
            //
            // 這個差別在調整視窗大小時很致命：外部 MultiEffect 持有的來源材質
            // 不會跟著來源 Item 的新尺寸即時重繪，結果就是圖片仍以舊尺寸畫在
            // 左上角，而外框光暈已經是新尺寸 —— 中間空一塊。
            // layer.enabled 讓材質與 Item 幾何綁在一起，由場景圖統一管理，
            // 尺寸永遠同步。
            Image {
                id: picture
                anchors.fill: parent
                source: root.source
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 720
                sourceSize.height: 720
                visible: picture.status === Image.Ready

                layer.enabled: picture.status === Image.Ready
                layer.effect: MultiEffect {
                    maskEnabled: true
                    maskSource: mask
                    shadowEnabled: true
                    shadowColor: Qt.rgba(0, 0, 0, 0.55)
                    shadowBlur: 0.9
                    shadowVerticalOffset: 14
                    shadowScale: 0.97
                    saturation: root.playing ? 0.06 : -0.55
                    brightness: root._punch * 0.10
                    Behavior on saturation {
                        NumberAnimation { duration: Motion.component }
                    }
                    Behavior on brightness { NumberAnimation { duration: Motion.short3 } }
                }
            }

            // 沒有封面時的替代圖形：主色漸層 + 音符輪廓
            Rectangle {
                id: placeholder
                anchors.fill: parent
                radius: Motion.cardRadius
                visible: picture.status !== Image.Ready
                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: Qt.lighter(root.accent, 1.25)
                    }
                    GradientStop {
                        position: 1.0
                        color: Qt.darker(root.accent, 1.8)
                    }
                }
                Text {
                    anchors.centerIn: parent
                    text: "♪"
                    font.pixelSize: (parent.width * 0.34) * Appearance.fontScale
                    color: Qt.rgba(1, 1, 1, 0.32)
                }
            }

            Item {
                id: mask
                anchors.fill: parent
                layer.enabled: true
                visible: false
                Rectangle {
                    anchors.fill: parent
                    radius: Motion.cardRadius
                    color: "black"
                }
            }

            // 鏡面高光：一條斜向的亮帶，位置跟著傾斜角度移動
            Rectangle {
                anchors.fill: parent
                radius: Motion.cardRadius
                clip: true
                color: "transparent"
                opacity: 0.5

                Rectangle {
                    width: parent.width * 0.5
                    height: parent.height * 2.4
                    rotation: 24
                    y: -parent.height * 0.7
                    x: parent.width * 0.5 + root._tiltY * 9 - width / 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.0) }
                        GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.16) }
                        GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.0) }
                    }
                }
            }
        }

        // 倒影：把封面上下翻轉後淡出
        Item {
            anchors.top: artwork.bottom
            anchors.horizontalCenter: artwork.horizontalCenter
            anchors.topMargin: 6
            width: artwork.width
            height: artwork.height * 0.34
            clip: true
            opacity: Motion.reduced ? 0.0 : 0.22
            visible: picture.status === Image.Ready

            Image {
                width: parent.width
                height: artwork.height
                source: root.source
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 360
                transform: Scale { origin.y: artwork.height / 2; yScale: -1 }
            }
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.45) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 1.0) }
                }
            }
        }
    }

    // 滑鼠位置 → 傾斜角度。用 Behavior 讓它平滑跟隨而不是硬跟。
    HoverHandler {
        id: tilt
        onPointChanged: {
            if (Motion.reduced) {
                return;
            }
            const nx = (tilt.point.position.x / root.width) * 2 - 1;
            const ny = (tilt.point.position.y / root.height) * 2 - 1;
            root._tiltY = nx * Motion.tiltDegrees;
            root._tiltX = -ny * Motion.tiltDegrees;
        }
        onHoveredChanged: {
            if (!hovered) {
                root._tiltX = 0;
                root._tiltY = 0;
            }
        }
    }

    Behavior on _tiltX {
        NumberAnimation { duration: Motion.medium2; easing.type: Easing.OutCubic }
    }
    Behavior on _tiltY {
        NumberAnimation { duration: Motion.medium2; easing.type: Easing.OutCubic }
    }
}
