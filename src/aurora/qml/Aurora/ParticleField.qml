import QtQuick
import QtQuick.Particles

/*!
    背景粒子：緩慢上浮的微光塵埃，發射率隨音量、顏色隨主色。

    Qt 官方對粒子的警告是「系統不會幫你把參數限制在硬體撐得住的範圍」，
    所以發射率刻意保守（最多每秒約 40 顆），而且只在電影畫質下啟用。

    這一層完全不接受輸入事件，純粹是氣氛。
*/
Item {
    id: root

    property color accent: "#7B2FF7"
    property real energy: 0.0
    property bool active: true

    enabled: false

    ParticleSystem {
        id: system
        running: root.active && root.visible
        paused: !root.active
    }

    ImageParticle {
        system: system
        // 內建的軟邊圓點，不需要外部圖檔
        source: "qrc:///particleresources/glowdot.png"
        color: root.accent
        colorVariation: 0.35
        alpha: 0.0
        entryEffect: ImageParticle.Fade
        Behavior on color { ColorAnimation { duration: Motion.palette } }
    }

    Emitter {
        system: system
        anchors.fill: parent
        // 只從畫面下緣三分之一發射，讓塵埃像是從地板浮起來
        y: parent.height * 0.55
        height: parent.height * 0.45

        emitRate: root.active ? 6 + root.energy * 34 : 0
        lifeSpan: 7000
        lifeSpanVariation: 2500
        size: 5
        sizeVariation: 4
        endSize: 1

        velocity: AngleDirection {
            angle: 268          // 幾乎正上方
            angleVariation: 26
            magnitude: 14
            magnitudeVariation: 12
        }
    }

    // 亂流讓上浮路徑不是筆直的，看起來像真的空氣流動
    Turbulence {
        system: system
        anchors.fill: parent
        strength: 9
        enabled: !Motion.reduced
    }

    // 輕微的橫向游移，避免所有粒子同步
    Wander {
        system: system
        anchors.fill: parent
        xVariance: 24
        pace: 12
    }
}
