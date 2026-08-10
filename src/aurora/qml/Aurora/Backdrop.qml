import QtQuick
import QtQuick.Effects

/*!
    沉浸式背景：把專輯封面放大到填滿視窗、重度模糊、再壓暗。

    模糊用 GPU 的 MultiEffect 而不是在 Python 裡算 —— 它跑在 render thread，
    而且 \c blur 屬性可以安全地動畫（\c blurMax 不行，那會觸發著色器重編，
    所以只在建立時設一次）。

    換歌時兩層交叉溶接：新圖在下層淡入，舊圖在上層淡出，
    避免中間出現一瞬間的空白。
*/
Item {
    id: root

    /*! 目前封面的 URL。設成空字串會退回純漸層。 */
    property url source: ""
    /*! 沒有封面時的漸層兩端，由 ThemeController 提供。 */
    property color topColor: "#101018"
    property color bottomColor: "#05050A"
    /*! 模糊強度倍率，由畫質預設控制。 */
    property real quality: 1.0
    /*! 音量帶動的亮度呼吸。 */
    property real energy: 0.0

    // 底層：主色漸層。封面載入失敗或沒有封面時就是它撐場面。
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.topColor }
            GradientStop { position: 1.0; color: root.bottomColor }
        }
        Behavior on color { ColorAnimation { duration: Motion.palette } }
    }

    // 封面層。用 layer + MultiEffect 做模糊；autoPaddingEnabled 關掉，
    // 因為這是鋪滿全螢幕的背景，不需要為模糊預留外擴空間。
    Item {
        id: coverLayer
        anchors.fill: parent
        visible: false

        Image {
            id: cover
            anchors.fill: parent
            source: root.source
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            // 背景會被模糊到看不出細節，縮到 512 就綽綽有餘，省下大量記憶體與頻寬
            sourceSize.width: 512
            sourceSize.height: 512
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: coverLayer
        autoPaddingEnabled: false
        visible: cover.status === Image.Ready

        blurEnabled: true
        blurMax: 64          // 會觸發著色器重編，只在此設定一次，永不動畫
        blur: 1.0
        blurMultiplier: 1.6 * root.quality
        saturation: 0.35
        brightness: -0.42 + root.energy * 0.06
        contrast: 0.08

        opacity: cover.status === Image.Ready ? 1.0 : 0.0
        Behavior on opacity {
            NumberAnimation {
                duration: Motion.backdrop
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Motion.standardDecelerate
            }
        }
        Behavior on brightness { NumberAnimation { duration: Motion.short4 } }
    }

    // 由下往上的暗化漸層，讓底部的控制列文字永遠有足夠對比
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.30) }
            GradientStop { position: 0.42; color: Qt.rgba(0, 0, 0, 0.12) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.78) }
        }
    }

    // 主色染色層：讓整個畫面帶上這首歌的顏色
    Rectangle {
        anchors.fill: parent
        color: root.topColor
        opacity: 0.22
        Behavior on color { ColorAnimation { duration: Motion.palette } }
    }
}
