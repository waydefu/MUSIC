import QtQuick
import QtQuick.Window
import QtQuick.Effects
import QtQuick.Dialogs
import Aurora

/*!
    主視窗。

    圓角是用 layer + MultiEffect 的遮罩做的，不是 clip ——
    Qt 的 clip 是矩形裁切（scissor rect），對圓角無效。遮罩還順便給了
    抗鋸齒邊緣與整個視窗的投影。

    層次由下而上：模糊封面背景 → 粒子 → 內容 → 電影感疊加層。
*/
Window {
    id: window

    width: 1180
    height: 760
    minimumWidth: 880
    minimumHeight: 560
    visible: true
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: Strings.appName + " " + Strings.appSubtitle

    readonly property color accent: player.theme.accent
    readonly property color accent2: player.theme.accent2
    property bool introDone: false

    // 投影需要的外緣留白
    readonly property int shadowMargin: 22

    // 進場動畫不能是內容可見性的唯一前提。若某張顯示卡的 effect 初始化
    // 較慢或某個繫結失敗，視窗仍必須立即有可操作的內容。
    Component.onCompleted: introAnimation.start()

    Binding {
        target: Motion
        property: "reduced"
        value: motion.reduceMotion
    }

    // ------------------------------------------------------------ 遮罩

    Item {
        id: maskSource
        anchors.fill: shell
        visible: false
        layer.enabled: true
        Rectangle {
            anchors.fill: parent
            radius: Motion.cornerRadius
            color: "black"
        }
    }

    Item {
        id: shell
        anchors.fill: parent
        anchors.margins: window.shadowMargin
        opacity: 1
        scale: 1

        // 這層遮罩在部分 D3D11 驅動上會讓整個 Window 只剩黑色／透明，
        // 因此不把裝飾性後製放在內容可見性的關鍵路徑上。
        layer.enabled: false
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: maskSource
            shadowEnabled: true
            shadowColor: Qt.rgba(0, 0, 0, 0.7)
            shadowBlur: 1.0
            shadowVerticalOffset: 10
            autoPaddingEnabled: true
        }

        // -------------------------------------------------------- 背景

        Backdrop {
            anchors.fill: parent
            source: player.coverUrl
            topColor: player.theme.bgTop
            bottomColor: player.theme.bgBottom
            quality: motion.blurQuality
            energy: audio.energy
        }

        ParticleField {
            anchors.fill: parent
            accent: window.accent
            energy: audio.energy
            active: motion.particlesEnabled
            visible: motion.particlesEnabled
        }

        // -------------------------------------------------------- 內容

        Item {
            id: content
            anchors.fill: parent

            TitleBar {
                id: titleBar
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: 10
                accent: window.accent
                presetLabel: motion.presetLabel
                fps: motion.fps
                showFps: motion.showFps
                onMinimiseRequested: window.showMinimized()
                onCloseRequested: window.close()
                onPresetCycled: motion.cyclePreset()
                onCinemaToggled: window.cinema = !window.cinema
                onMiniModeRequested: toast.show("迷你模式即將登場")
            }

            // 左側：封面與曲目資訊
            Item {
                id: stage
                anchors.top: titleBar.bottom
                anchors.left: parent.left
                anchors.bottom: bottomBar.top
                anchors.leftMargin: Motion.windowMargin + 8
                anchors.topMargin: 4
                anchors.bottomMargin: 8
                width: Math.min(parent.width * 0.46, 460)

                CoverCard {
                    id: coverCard
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    width: Math.min(parent.width, parent.height * 0.62)
                    height: width
                    source: player.coverUrl
                    accent: window.accent
                    energy: audio.energy
                    playing: player.playing
                    bloomEnabled: motion.bloomEnabled
                    bloomStrength: motion.bloomStrength
                }

                Column {
                    anchors.top: coverCard.bottom
                    anchors.topMargin: 34
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: 6

                    MarqueeText {
                        width: parent.width
                        text: player.title
                        color: "white"
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.3
                    }

                    Text {
                        width: parent.width
                        text: player.artist + (player.album ? " · " + player.album : "")
                        color: Qt.rgba(1, 1, 1, 0.62)
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    // 音質小徽章
                    Row {
                        spacing: 8
                        topPadding: 8

                        Rectangle {
                            visible: player.hasTrack
                            width: sourceLabel.width + 18
                            height: 24
                            radius: 12
                            color: Qt.rgba(1, 1, 1, 0.09)
                            border.width: 1
                            border.color: Qt.rgba(window.accent.r, window.accent.g,
                                                  window.accent.b, 0.35)
                            Text {
                                id: sourceLabel
                                anchors.centerIn: parent
                                text: player.sourceSummary
                                color: Qt.rgba(1, 1, 1, 0.82)
                                font.pixelSize: 11
                                font.letterSpacing: 0.4
                            }
                        }

                        Rectangle {
                            id: codecBadge
                            width: codecRow.width + 18
                            height: 24
                            radius: 12
                            color: player.quality.isHandsFree
                                   ? Qt.rgba(1, 0.35, 0.28, 0.20)
                                   : Qt.rgba(1, 1, 1, 0.09)
                            border.width: 1
                            border.color: player.quality.isHandsFree
                                          ? Qt.rgba(1, 0.45, 0.35, 0.65)
                                          : Qt.rgba(window.accent.r, window.accent.g,
                                                    window.accent.b, 0.35)

                            // 通話模式是嚴重的音質問題，用脈動強制吸引注意
                            SequentialAnimation on opacity {
                                running: player.quality.isHandsFree && !Motion.reduced
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.45; duration: 700
                                                  easing.type: Easing.InOutSine }
                                NumberAnimation { to: 1.0; duration: 700
                                                  easing.type: Easing.InOutSine }
                            }

                            Row {
                                id: codecRow
                                anchors.centerIn: parent
                                spacing: 5
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: player.quality.codecName
                                    color: "white"
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: player.quality.codecBadge
                                    color: Qt.rgba(1, 1, 1, 0.55)
                                    font.pixelSize: 9
                                }
                            }

                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: window.qualityOpen = !window.qualityOpen }
                        }
                    }
                }
            }

            // 右側：頻譜 / 歌詞 / 清單
            Item {
                id: rightPane
                anchors.top: titleBar.bottom
                anchors.left: stage.right
                anchors.right: parent.right
                anchors.bottom: bottomBar.top
                anchors.margins: 8
                anchors.rightMargin: Motion.windowMargin
                anchors.bottomMargin: 8

                SpectrumBars {
                    id: spectrum
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: parent.height * 0.20
                    height: parent.height * 0.34
                    model: player.spectrum
                    accent: window.accent
                    accent2: window.accent2
                    bloomEnabled: motion.bloomEnabled
                    bloomStrength: motion.bloomStrength
                    opacity: window.lyricsOpen || window.playlistOpen || window.libraryOpen ? 0.25 : 1.0
                    Behavior on opacity { NumberAnimation { duration: Motion.panel } }
                }

                LyricsPanel {
                    anchors.fill: parent
                    controller: player.lyrics
                    accent: window.accent
                    open: window.lyricsOpen
                }

                PlaylistPanel {
                    anchors.fill: parent
                    model: player.playlist
                    currentIndex: player.index
                    accent: window.accent
                    open: window.playlistOpen
                    onActivated: (row) => player.playIndex(row)
                    onRemoved: (row) => player.removeAt(row)
                }

                LibraryPanel {
                    anchors.fill: parent
                    controller: player
                    accent: window.accent
                    open: window.libraryOpen
                    onPickFolderRequested: libraryFolderDialog.open()
                    onActivated: (folder) => player.playLibraryPlaylist(folder)
                }

                QualityPanel {
                    anchors.fill: parent
                    controller: player.quality
                    accent: window.accent
                    open: window.qualityOpen
                }
            }

            // 底部控制列
            Item {
                id: bottomBar
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: Motion.windowMargin
                height: 108

                SeekBar {
                    id: seek
                    anchors.top: parent.top
                    anchors.left: timeLeft.right
                    anchors.right: timeRight.left
                    anchors.margins: 12
                    progress: player.progress
                    duration: player.duration
                    accent: window.accent
                    accent2: window.accent2
                    onSeekRequested: (fraction) => player.seekFraction(fraction)
                }

                Text {
                    id: timeLeft
                    anchors.left: parent.left
                    anchors.verticalCenter: seek.verticalCenter
                    text: player.positionText
                    color: Qt.rgba(1, 1, 1, 0.75)
                    font.pixelSize: 11
                    font.family: "Consolas"
                }
                Text {
                    id: timeRight
                    anchors.right: parent.right
                    anchors.verticalCenter: seek.verticalCenter
                    text: player.durationText
                    color: Qt.rgba(1, 1, 1, 0.45)
                    font.pixelSize: 11
                    font.family: "Consolas"
                }

                TransportControls {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    playing: player.playing
                    shuffle: player.shuffle
                    repeatMode: player.repeatMode
                    accent: window.accent
                    energy: audio.energy
                    onPlayToggled: player.togglePlay()
                    onPreviousRequested: player.playPrevious()
                    onNextRequested: player.playNext()
                    onShuffleToggled: player.toggleShuffle()
                    onRepeatCycled: player.cycleRepeat()
                }

                VolumeControl {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 14
                    value: player.volume
                    muted: player.muted
                    accent: window.accent
                    onVolumeChanged: (value) => player.setVolume(value)
                    onMuteToggled: player.toggleMute()
                }

                Row {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 14
                    spacing: 2

                    IconButton {
                        icon: "folder"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.libraryOpen
                        onClicked: window.togglePanel("library")
                    }
                    IconButton {
                        icon: "list"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.playlistOpen
                        onClicked: window.togglePanel("playlist")
                    }
                    IconButton {
                        icon: "lyrics"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.lyricsOpen
                        onClicked: window.togglePanel("lyrics")
                    }
                    IconButton {
                        icon: "info"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.qualityOpen
                        onClicked: window.togglePanel("quality")
                    }
                }
            }
        }

        // -------------------------------------------------------- 電影感疊加

        PostStack {
            anchors.fill: parent
            tint: window.accent
            bass: audio.bass
            grainEnabled: motion.grainEnabled
            vignetteStrength: window.cinema ? 0.46 : 0.30
        }

        // 電影模式的上下遮幅
        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: window.cinema ? parent.height * 0.09 : 0
            color: "black"
            Behavior on height {
                NumberAnimation {
                    duration: Motion.scene
                    easing.type: Easing.BezierSpline
                    easing.bezierCurve: Motion.emphasizedDecelerate
                }
            }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: window.cinema ? parent.height * 0.09 : 0
            color: "black"
            Behavior on height {
                NumberAnimation {
                    duration: Motion.scene
                    easing.type: Easing.BezierSpline
                    easing.bezierCurve: Motion.emphasizedDecelerate
                }
            }
        }

        // -------------------------------------------------------- 提示

        Toast {
            id: toast
            anchors.top: parent.top
            anchors.topMargin: 56
            anchors.left: parent.left
            anchors.right: parent.right
            accent: window.accent
        }

        // 拖放
        DropArea {
            anchors.fill: parent
            onDropped: (drop) => {
                if (drop.hasUrls) {
                    player.addUrls(drop.urls);
                    drop.accept();
                }
            }

            Rectangle {
                anchors.fill: parent
                visible: parent.containsDrag
                color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.12)
                border.width: 2
                border.color: window.accent
                radius: Motion.cornerRadius

                Text {
                    anchors.centerIn: parent
                    text: Strings.dropHere
                    color: "white"
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    // ------------------------------------------------------------ 狀態

    property bool playlistOpen: false
    property bool libraryOpen: false
    property bool lyricsOpen: false
    property bool qualityOpen: false
    property bool cinema: false

    function togglePanel(name) {
        const wasOpen = (name === "playlist" && playlistOpen)
                     || (name === "library" && libraryOpen)
                     || (name === "lyrics" && lyricsOpen)
                     || (name === "quality" && qualityOpen);
        playlistOpen = !wasOpen && name === "playlist";
        libraryOpen = !wasOpen && name === "library";
        lyricsOpen = !wasOpen && name === "lyrics";
        qualityOpen = !wasOpen && name === "quality";
    }

    FileDialog {
        id: libraryFolderDialog
        title: "選擇音樂資料夾"
        fileMode: FileDialog.OpenDirectory
        onAccepted: player.addLibraryFolder(selectedFile)
    }

    // 音樂能量的單一來源。所有視覺元件都綁這裡，共用同一個節拍。
    // 數值由 PlayerController 每個 UI 幀更新一次。
    QtObject {
        id: audio
        readonly property real energy: player.energy
        readonly property real bass: player.bass
    }

    Connections {
        target: player
        function onBeat() {
            coverCard.punch();
        }
        function onToast(message) {
            toast.show(message, false);
        }
    }

    Connections {
        target: player.quality
        function onDeviceChanged(name) {
            toast.show("輸出裝置：" + name, false);
        }
        function onHfpWarning(active) {
            if (active) {
                toast.show(Strings.handsFreeWarning, true);
            }
        }
    }

    Connections {
        target: motion
        function onDegraded(label) {
            toast.show("偵測到掉幀，畫質已降為「" + label + "」", false);
        }
    }

    // ------------------------------------------------------------ 啟動進場

    ParallelAnimation {
        id: introAnimation
        NumberAnimation {
            target: shell; property: "opacity"
            from: 0; to: 1; duration: Motion.intro
            easing.type: Easing.OutExpo
        }
        NumberAnimation {
            target: shell; property: "scale"
            from: 0.94; to: 1.0; duration: Motion.intro
            easing.type: Easing.OutExpo
        }
        onFinished: window.introDone = true
    }

    // ------------------------------------------------------------ 快捷鍵

    Shortcut { sequence: "Space"; onActivated: player.togglePlay() }
    Shortcut { sequence: "Right"; onActivated: player.nudge(5) }
    Shortcut { sequence: "Left"; onActivated: player.nudge(-5) }
    Shortcut { sequence: "Ctrl+Right"; onActivated: player.playNext() }
    Shortcut { sequence: "Ctrl+Left"; onActivated: player.playPrevious() }
    Shortcut { sequence: "Up"; onActivated: player.bumpVolume(0.05) }
    Shortcut { sequence: "Down"; onActivated: player.bumpVolume(-0.05) }
    Shortcut { sequence: "M"; onActivated: player.toggleMute() }
    Shortcut { sequence: "L"; onActivated: window.togglePanel("lyrics") }
    Shortcut { sequence: "Ctrl+L"; onActivated: window.togglePanel("library") }
    Shortcut { sequence: "Ctrl+O"; onActivated: libraryFolderDialog.open() }
    Shortcut { sequence: "P"; onActivated: window.togglePanel("playlist") }
    Shortcut { sequence: "I"; onActivated: window.togglePanel("quality") }
    Shortcut { sequence: "C"; onActivated: window.cinema = !window.cinema }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (window.cinema) {
                window.cinema = false;
            } else {
                window.playlistOpen = false;
                window.libraryOpen = false;
                window.lyricsOpen = false;
                window.qualityOpen = false;
            }
        }
    }

    // 邊緣拖曳縮放。startSystemResize 走原生路徑，能拿到 Aero Snap。
    Repeater {
        model: [
            { e: Qt.LeftEdge,  x: 0, y: 0, w: 6, h: 1, cur: Qt.SizeHorCursor },
            { e: Qt.RightEdge, x: 1, y: 0, w: 6, h: 1, cur: Qt.SizeHorCursor },
            { e: Qt.TopEdge,   x: 0, y: 0, w: 1, h: 6, cur: Qt.SizeVerCursor },
            { e: Qt.BottomEdge, x: 0, y: 1, w: 1, h: 6, cur: Qt.SizeVerCursor }
        ]
        Item {
            required property var modelData
            x: modelData.x === 1 ? window.width - modelData.w : 0
            y: modelData.y === 1 ? window.height - modelData.h : 0
            width: modelData.w === 1 ? window.width : modelData.w
            height: modelData.h === 1 ? window.height : modelData.h

            HoverHandler { cursorShape: modelData.cur }
            TapHandler {
                gesturePolicy: TapHandler.DragThreshold
                onPressedChanged: {
                    if (pressed) {
                        window.startSystemResize(modelData.e);
                    }
                }
            }
        }
    }
}
