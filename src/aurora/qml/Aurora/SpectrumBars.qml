import QtQuick
import QtQuick.Effects

/*!
    64 條頻譜。

    效能上的兩個關鍵決定：

    1. 資料來自 \c QAbstractListModel，delegate 綁的是 \c model.value ——
       走 C++ 屬性讀取，完全不跑 JavaScript。若改成綁一個 list property
       再用 \c bars[index] 取值，每秒會產生近四千次 JS 求值，
       而 Qt 效能指引明確要求動畫期間不要跑 JS。
    2. bloom 掛在**整排的 layer** 上，不是每根 bar 各掛一個 ——
       官方指引也說不要在 delegate 內用 ShaderEffect。
       整排一次離屏渲染，場景圖還能把 64 個矩形合批。

    平滑與峰值下墜已經在 Python 端算好（core/dsp.py），這裡只負責畫。
*/
Item {
    id: root

    property var model: null
    property color accent: "#7B2FF7"
    property color accent2: "#F76B2F"
    property bool bloomEnabled: true
    property real bloomStrength: 1.0
    /*! 顯示峰值標記。 */
    property bool showPeaks: true

    readonly property real barWidth: Math.max(2, (width - spacing * (count - 1)) / count)
    readonly property int count: 64
    property real spacing: 3

    Item {
        id: bars
        anchors.fill: parent
        layer.enabled: root.bloomEnabled
        layer.effect: MultiEffect {
            autoPaddingEnabled: false
            blurEnabled: true
            blurMax: 24
            blur: 0.55 * root.bloomStrength
            blurMultiplier: 0.6
            brightness: 0.28 * root.bloomStrength
            saturation: 0.30
        }

        Row {
            anchors.fill: parent
            spacing: root.spacing

            Repeater {
                model: root.model

                delegate: Item {
                    required property real value
                    required property real peak

                    width: root.barWidth
                    height: bars.height

                    // 主條。漸層從底部的主色過渡到頂端的次要色，
                    // 高度越高越亮 —— 這比整根同色更有層次。
                    Rectangle {
                        width: parent.width
                        radius: width / 2
                        anchors.bottom: parent.bottom
                        height: Math.max(width, parent.height * value)

                        gradient: Gradient {
                            GradientStop {
                                position: 0.0
                                color: Qt.rgba(root.accent.r, root.accent.g,
                                               root.accent.b, 0.55)
                            }
                            GradientStop {
                                position: 1.0
                                color: Qt.rgba(root.accent2.r, root.accent2.g,
                                               root.accent2.b, 0.60 + value * 0.40)
                            }
                        }
                    }

                    // 峰值標記
                    Rectangle {
                        visible: root.showPeaks && peak > 0.02
                        width: parent.width
                        height: 2
                        radius: 1
                        color: Qt.rgba(1, 1, 1, 0.55 + peak * 0.4)
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: Math.max(0, parent.height * peak - height)
                    }
                }
            }
        }
    }

    // 底部倒影，讓頻譜像是站在一面暗色鏡面上
    Item {
        anchors.top: bars.bottom
        anchors.left: bars.left
        anchors.right: bars.right
        height: bars.height * 0.28
        clip: true
        visible: !Motion.reduced
        opacity: 0.18

        Row {
            spacing: root.spacing
            Repeater {
                model: root.model
                delegate: Rectangle {
                    required property real value
                    width: root.barWidth
                    height: Math.max(1, bars.height * value * 0.28)
                    radius: width / 2
                    color: Qt.rgba(root.accent2.r, root.accent2.g, root.accent2.b, 0.5)
                }
            }
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.2) }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 1.0) }
            }
        }
    }
}
