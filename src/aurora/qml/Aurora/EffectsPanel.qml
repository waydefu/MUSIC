import QtQuick
import QtQuick.Controls

/*! 等化器與空間音效的操作面板。

    版面刻意跟著 SettingsPanel 走（GlassPanel + 標題 + Column），
    這樣使用者換面板時不需要重新認識介面。

    兩件事值得在畫面上講清楚，因為它們違反直覺：

    * **拉高不會變大聲。** 自動餘裕會把整條曲線降低相同的量。不講的話
      使用者會以為滑桿壞了。所以 headroom 直接顯示出來。
    * **開啟會有延遲。** FIR 與 STFT 都有固有延遲。既然已經有一等公民的
      latency 帳，就誠實秀給使用者看。
*/
Item {
    id: root

    property var controller: null
    property color accent: "#7B2FF7"
    property bool open: false

    readonly property var gains: controller ? controller.bandGains : []
    readonly property var labels: controller ? controller.bandLabels : []
    readonly property real limit: controller ? controller.gainLimit : 12

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
            text: Strings.effects
            color: "white"
            font.pixelSize: 13 * Appearance.fontScale
            font.letterSpacing: 2.2
            font.weight: Font.DemiBold
        }

        Text {
            id: latencyBadge
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 18
            visible: root.controller && root.controller.latencyMs > 0.01
            text: Strings.addedLatency + " " + (root.controller ? root.controller.latencyMs.toFixed(1) : "0") + " ms"
            color: Qt.rgba(1, 1, 1, 0.6)
            font.pixelSize: 12 * Appearance.fontScale
        }

        // 內容比面板高時要能捲動，而不是溢出到面板外面。
        // 十段推桿加上兩段說明本來就接近極限，字級拉到 135% 一定會超過。
        // 做法沿用 QualityPanel。
        Flickable {
            id: scroll
            anchors.top: header.bottom
            anchors.topMargin: 16
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 20
            contentWidth: width
            contentHeight: content.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: content
                width: scroll.width
                spacing: 14

                // ---------------------------------------------------- 等化器

                Item {
                    width: parent.width
                    height: 30

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        text: Strings.equalizer
                        color: "white"
                        font.pixelSize: 15 * Appearance.fontScale
                        font.weight: Font.DemiBold
                    }

                    Row {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 12

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Strings.resetEq
                            color: resetHover.hovered ? root.accent : Qt.rgba(1, 1, 1, 0.6)
                            font.pixelSize: 13 * Appearance.fontScale
                            HoverHandler { id: resetHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                onTapped: if (root.controller) root.controller.resetEq()
                            }
                        }

                        Switch {
                            anchors.verticalCenter: parent.verticalCenter
                            checked: root.controller ? root.controller.eqEnabled : false
                            onToggled: if (root.controller) root.controller.setEqEnabled(checked)
                        }
                    }
                }

                // 十段推桿。垂直排列，形狀本身就說明了它是等化器。
                Row {
                    id: bandRow
                    width: parent.width
                    height: 214
                    spacing: 0
                    opacity: (root.controller && root.controller.eqEnabled) ? 1.0 : 0.4

                    Behavior on opacity { NumberAnimation { duration: Motion.panel } }

                    Repeater {
                        model: root.labels

                        Item {
                            required property int index
                            required property string modelData

                            width: bandRow.width / Math.max(1, root.labels.length)
                            height: bandRow.height

                            Slider {
                                id: bandSlider
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.top: parent.top
                                width: 26
                                height: parent.height - 44
                                orientation: Qt.Vertical
                                from: -root.limit
                                to: root.limit
                                enabled: root.controller ? root.controller.eqEnabled : false
                                value: index < root.gains.length ? root.gains[index] : 0

                                onMoved: if (root.controller) root.controller.setBandGain(index, value)

                                // 自訂軌道與旋鈕。Basic 樣式的預設旋鈕在十根並排時
                                // 幾乎會互相碰到，行程也看不出來。
                                background: Item {
                                    anchors.fill: parent

                                    Rectangle {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        y: bandSlider.topPadding
                                        width: 4
                                        height: bandSlider.availableHeight
                                        radius: 2
                                        color: Qt.rgba(1, 1, 1, 0.14)
                                    }
                                    // 0 dB 的刻度線。沒有它就看不出中點在哪。
                                    Rectangle {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        y: bandSlider.topPadding + bandSlider.availableHeight / 2
                                        width: 12
                                        height: 1
                                        color: Qt.rgba(1, 1, 1, 0.28)
                                    }
                                    // 從中點往旋鈕方向的染色，一眼看出拉高還是壓低。
                                    Rectangle {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 4
                                        radius: 2
                                        color: root.accent
                                        opacity: bandSlider.enabled ? 0.85 : 0.3
                                        y: Math.min(bandSlider.handle.y + bandSlider.handle.height / 2,
                                                    bandSlider.topPadding + bandSlider.availableHeight / 2)
                                        height: Math.abs(bandSlider.handle.y + bandSlider.handle.height / 2
                                                         - (bandSlider.topPadding + bandSlider.availableHeight / 2))
                                    }
                                }

                                handle: Rectangle {
                                    x: bandSlider.leftPadding + bandSlider.availableWidth / 2 - width / 2
                                    y: bandSlider.topPadding + bandSlider.visualPosition
                                       * (bandSlider.availableHeight - height)
                                    width: 18
                                    height: 18
                                    radius: 9
                                    color: bandSlider.pressed ? root.accent : "white"
                                    opacity: bandSlider.enabled ? 1.0 : 0.35
                                    border.width: 1
                                    border.color: Qt.rgba(0, 0, 0, 0.25)
                                }
                            }

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.top: bandSlider.bottom
                                anchors.topMargin: 4
                                text: modelData
                                color: Qt.rgba(1, 1, 1, 0.62)
                                font.pixelSize: 12 * Appearance.fontScale
                            }

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                text: (bandSlider.value >= 0 ? "+" : "") + bandSlider.value.toFixed(0)
                                color: Math.abs(bandSlider.value) < 0.5
                                       ? Qt.rgba(1, 1, 1, 0.35) : root.accent
                                font.pixelSize: 12 * Appearance.fontScale
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                // 自動餘裕。這一行的存在理由是「解釋為什麼拉高沒有變大聲」。
                Item {
                    width: parent.width
                    height: headroomText.implicitHeight
                    visible: root.controller && root.controller.headroomDb < -0.05

                    Text {
                        anchors.left: parent.left
                        text: Strings.headroom
                        color: Qt.rgba(1, 1, 1, 0.6)
                        font.pixelSize: 12.5 * Appearance.fontScale
                    }
                    Text {
                        id: headroomText
                        anchors.right: parent.right
                        text: (root.controller ? root.controller.headroomDb.toFixed(1) : "0") + " dB"
                        color: root.accent
                        font.pixelSize: 12.5 * Appearance.fontScale
                        font.weight: Font.DemiBold
                    }
                }

                Text {
                    width: parent.width
                    text: Strings.equalizerHint
                    color: Qt.rgba(1, 1, 1, 0.42)
                    font.pixelSize: 12.5 * Appearance.fontScale
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Qt.rgba(1, 1, 1, 0.08)
                }

                // ---------------------------------------------------- 空間音效

                Item {
                    width: parent.width
                    height: 30

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        text: Strings.spatial
                        color: "white"
                        font.pixelSize: 15 * Appearance.fontScale
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: Math.round(spatialSlider.value * 100) + "%"
                        color: spatialSlider.value > 0.005 ? root.accent : Qt.rgba(1, 1, 1, 0.3)
                        font.pixelSize: 13 * Appearance.fontScale
                        font.weight: Font.DemiBold
                    }
                }

                Slider {
                    id: spatialSlider
                    width: parent.width
                    from: 0.0
                    to: 1.0
                    value: root.controller ? root.controller.spatialAmount : 0.0
                    onMoved: if (root.controller) root.controller.setSpatialAmount(value)
                }

                Text {
                    width: parent.width
                    text: Strings.spatialHint
                    color: Qt.rgba(1, 1, 1, 0.42)
                    font.pixelSize: 12.5 * Appearance.fontScale
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    visible: root.controller ? root.controller.limiterEngaged : false
                    text: Strings.limiterEngaged
                    color: "#F2B33D"
                    font.pixelSize: 12.5 * Appearance.fontScale
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
