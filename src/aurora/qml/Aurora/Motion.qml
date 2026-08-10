pragma Singleton
import QtQuick

/*!
    動效 token 的單一真相來源。**任何元件都不准自己寫死時長或曲線。**

    數值取自兩份權威資料：

    Material Design 3 — Easing and duration tokens
        提供 easing 的 cubic-bezier 與 duration 級距。M3 特別指出
        micro-interaction 不可用 emphasized 曲線：它前段慢，在 50–100ms
        的尺度上會被感知成遲鈍。

    Nielsen Norman Group — Response Time Limits
        0.1 秒是「直接操控感」的界線，動畫必須在使用者動作後 100ms 內開始；
        介面動畫落在 200–500ms，小元件偏低端、大範圍位移偏高端。
*/
QtObject {
    id: motion

    // ---------------------------------------------------------------- 開關

    /*! 由 Main.qml 綁到 MotionController.reduceMotion。
        開啟時保留淡入淡出，但移除位移、彈跳與粒子 —— 這是 Apple HIG
        與 M3 共同的硬性要求，不是選配。 */
    property bool reduced: false

    /*! 位移類動畫的距離倍率。減少動態時歸零，元件不必各自寫 if。 */
    readonly property real travel: reduced ? 0.0 : 1.0

    // ---------------------------------------------------------------- 時長

    // M3 duration tokens
    readonly property int short1: 50
    readonly property int short2: 100
    readonly property int short3: 150
    readonly property int short4: 200
    readonly property int medium1: 250
    readonly property int medium2: 300
    readonly property int medium3: 350
    readonly property int medium4: 400
    readonly property int long1: 450
    readonly property int long2: 500
    readonly property int long3: 550
    readonly property int long4: 600
    readonly property int extraLong2: 800
    readonly property int extraLong4: 1000

    // 語意別名 —— 元件用這些，不用上面的原始 token
    readonly property int press: reduced ? short2 : short2       // 按下回饋
    readonly property int hover: reduced ? short2 : short3       // 滑過
    readonly property int icon: reduced ? short3 : medium1       // 圖示變形
    readonly property int component: reduced ? short4 : medium2  // 元件轉場
    readonly property int panel: reduced ? medium1 : medium4     // 面板開合
    readonly property int scene: reduced ? medium2 : long2       // 換歌、模式切換
    readonly property int palette: reduced ? medium2 : long4     // 主色過場
    readonly property int backdrop: reduced ? medium3 : 700      // 背景交叉溶接
    readonly property int intro: reduced ? medium4 : 900         // 啟動進場

    /*! 清單項目逐項淡入的錯開間隔。 */
    readonly property int stagger: reduced ? 0 : 30

    // ---------------------------------------------------------------- 曲線

    // M3 easing tokens，格式為 easing.bezierCurve 要的 [cx1,cy1,cx2,cy2,endx,endy]
    readonly property var standard: [0.2, 0.0, 0.0, 1.0, 1.0, 1.0]
    readonly property var standardDecelerate: [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    readonly property var standardAccelerate: [0.3, 0.0, 1.0, 1.0, 1.0, 1.0]
    readonly property var emphasizedDecelerate: [0.05, 0.7, 0.1, 1.0, 1.0, 1.0]
    readonly property var emphasizedAccelerate: [0.3, 0.0, 0.8, 0.15, 1.0, 1.0]

    /*! 彈性回彈的過衝量。減少動態時不彈。 */
    readonly property real overshoot: reduced ? 0.0 : 1.45

    // ---------------------------------------------------------------- 視覺常數

    readonly property real cornerRadius: 18
    readonly property real panelRadius: 14
    readonly property real cardRadius: 12
    readonly property real glassOpacity: 0.10
    readonly property real glassBorderOpacity: 0.16
    readonly property real windowMargin: 24

    /*! 封面 3D 傾斜的最大角度。 */
    readonly property real tiltDegrees: reduced ? 0.0 : 6.0
    /*! 音量驅動的封面呼吸幅度。 */
    readonly property real breathe: reduced ? 0.0 : 0.02
    /*! 鼓點衝擊的瞬間放大量。 */
    readonly property real punch: reduced ? 0.0 : 0.04
}
