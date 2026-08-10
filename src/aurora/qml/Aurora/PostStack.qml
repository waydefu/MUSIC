import QtQuick

/*!
    電影感疊加層：暗角 + 底片顆粒 + 掃描線，一個著色器一次畫完。

    時間 uniform 用一條無限循環的 NumberAnimation 推進 ——
    宣告式、跑在 render thread，不需要 Timer 也不需要每幀執行 JavaScript。
*/
Item {
    id: root

    property color tint: "#7B2FF7"
    property real bass: 0.0
    property bool grainEnabled: true
    property real vignetteStrength: 0.30
    property real grainStrength: 0.045
    property real scanlineStrength: 0.010

    // 這一層純粹是視覺疊加，絕不能吃掉底下元件的滑鼠事件
    enabled: false

    ShaderEffect {
        id: effect
        anchors.fill: parent
        fragmentShader: Qt.resolvedUrl("shaders/poststack.frag.qsb")

        property real time: 0.0
        property real vignette: root.vignetteStrength
        property real grain: root.grainEnabled ? root.grainStrength : 0.0
        property real scanline: root.grainEnabled ? root.scanlineStrength : 0.0
        property real pulse: root.bass
        property vector4d tint: Qt.vector4d(
            root.tint.r, root.tint.g, root.tint.b, 1.0)

        Behavior on vignette { NumberAnimation { duration: Motion.component } }
        Behavior on grain { NumberAnimation { duration: Motion.component } }
        Behavior on pulse { NumberAnimation { duration: Motion.short2 } }

        NumberAnimation on time {
            running: root.grainEnabled && root.visible
            from: 0
            to: 10000
            duration: 10000000   // 效果上等同永不結束
            loops: Animation.Infinite
        }
    }
}
