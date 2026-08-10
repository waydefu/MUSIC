import QtQuick

/*!
    電影感疊加層：暗角 + 底片顆粒，一個著色器一次畫完。

    時間 uniform 用一條無限循環的 NumberAnimation 推進 ——
    宣告式、跑在 render thread，不需要 Timer 也不需要每幀執行 JavaScript。

    這裡曾經有掃描線，已移除：以正規化 uv 表示的固定頻率條紋，
    週期會隨視窗尺寸與 DPI 改變，接近像素格點時就變成整片斑馬紋。
    詳見 shaders/poststack.frag 的註解。
*/
Item {
    id: root

    property color tint: "#7B2FF7"
    property real bass: 0.0
    property bool grainEnabled: true
    property real vignetteStrength: 0.30
    property real grainStrength: 0.045

    // 這一層純粹是視覺疊加，絕不能吃掉底下元件的滑鼠事件
    enabled: false

    ShaderEffect {
        id: effect
        anchors.fill: parent
        fragmentShader: Qt.resolvedUrl("shaders/poststack.frag.qsb")

        property real time: 0.0
        property real vignette: root.vignetteStrength
        property real grain: root.grainEnabled ? root.grainStrength : 0.0
        property real pulse: root.bass
        property vector4d tint: Qt.vector4d(
            root.tint.r, root.tint.g, root.tint.b, 1.0)

        Behavior on vignette { NumberAnimation { duration: Motion.component } }
        Behavior on grain { NumberAnimation { duration: Motion.component } }
        Behavior on pulse { NumberAnimation { duration: Motion.short2 } }

        // 顆粒的種子必須**有界**。先前寫成 0 → 10000 歷時 10000 秒，
        // time 單調遞增到數千，著色器裡再乘上大常數就突破 float32 的有效位，
        // 雜湊退化成由上往下捲動的斑馬紋。改成 0 → 1024 每約 17 秒循環一次，
        // 平均每個畫面幀前進一格，數值永遠留在整數能精確表示的範圍內。
        NumberAnimation on time {
            running: root.grainEnabled && root.visible
            from: 0
            to: 1024
            duration: 1024 * 1000 / 60   // 每幀約前進 1
            loops: Animation.Infinite
        }
    }
}
