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
    minimumWidth: miniMode ? 360 : 880
    minimumHeight: miniMode ? 150 : 560

    // 視窗絕不能大過桌面可用範圍。這是無邊框視窗特有的陷阱：
    // 一旦底部的播放控制列掉到螢幕外，使用者連把視窗拖回來都很困難。
    // 在 125% 縮放的 1920x1080 螢幕上，邏輯桌面只有 1536x864，
    // 而 QML 的尺寸單位正是邏輯像素 —— 很容易不知不覺就超出。
    maximumWidth: fullScreen ? Screen.width : Screen.desktopAvailableWidth
    maximumHeight: fullScreen ? Screen.height : Screen.desktopAvailableHeight
    visible: true
    color: introDone ? "transparent" : "#06110C"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: Strings.appName + " " + Strings.appSubtitle

    readonly property color accent: player.theme.accent
    readonly property color accent2: player.theme.accent2
    property bool introDone: false

    // 投影需要的外緣留白
    readonly property int shadowMargin: 22

    // 進場動畫不能是內容可見性的唯一前提。若某張顯示卡的 effect 初始化
    // 較慢或某個繫結失敗，視窗仍必須立即有可操作的內容。
    Component.onCompleted: {
        Appearance.fontScale = player.fontScale;
        if (player.miniMode) {
            miniMode = true;
            width = 540;
            height = 180;
        }
        introAnimation.start();
    }

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
        anchors.margins: window.fullScreen || window.miniMode ? 0 : window.shadowMargin
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
            visible: !window.miniMode

            // 標題列的拖曳面。
            //
            // 兩個細節決定了它能不能用：
            //
            // 1. **用 MouseArea 而不是 TapHandler。** Qt Quick 的 PointerHandler
            //    即使被上層元件蓋住也照樣收得到事件；試過整個視窗鋪一層
            //    TapHandler 拖曳面，結果播放清單、進度條、音量滑桿全被吃掉，
            //    完全無法捲動或拖曳。MouseArea 會被上層接受事件的元件攔下。
            // 2. **宣告在 TitleBar 之前**，所以標題列上的按鈕位於它之上，
            //    點按鈕不會變成拖視窗。
            //
            // startSystemMove() 直接用 window 這個 id 呼叫。先前寫在 TitleBar.qml
            // 裡透過 Window.window 附加屬性反向抓視窗，解析不到時只是靜靜失敗，
            // 症狀就是「整個主視窗都拖不動」而且毫無錯誤訊息。
            MouseArea {
                anchors.fill: titleBar
                onPressed: window.startSystemMove()
            }

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
                onFullscreenToggled: window.toggleFullscreen()
                onMiniModeRequested: window.toggleMiniMode()
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
                        font.pixelSize: (26) * Appearance.fontScale
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.3
                    }

                    Text {
                        width: parent.width
                        text: player.artist + (player.album ? " · " + player.album : "")
                        color: Qt.rgba(1, 1, 1, 0.62)
                        font.pixelSize: (13) * Appearance.fontScale
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
                                font.pixelSize: (11) * Appearance.fontScale
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
                                    font.pixelSize: (11) * Appearance.fontScale
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: player.quality.codecBadge
                                    color: Qt.rgba(1, 1, 1, 0.55)
                                    font.pixelSize: (9) * Appearance.fontScale
                                }
                            }

                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: window.togglePanel("quality") }
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
                    opacity: window.lyricsOpen || window.playlistOpen || window.libraryOpen || window.qualityOpen || window.settingsOpen
                             ? 0.25 : 1.0
                    Behavior on opacity { NumberAnimation { duration: Motion.panel } }
                }

                LyricsPanel {
                    anchors.fill: parent
                    controller: player.lyrics
                    accent: window.accent
                    open: window.lyricsOpen
                }

                PlaylistPanel {
                    id: playlistPanel
                    anchors.fill: parent
                    model: player.filteredPlaylist
                    currentPath: player.currentPath
                    accent: window.accent
                    open: window.playlistOpen
                    canGoBack: window.playlistFromLibrary
                    onActivated: (row) => player.playFilteredIndex(row)
                    onRemoved: (row) => player.removeFilteredAt(row)
                    onSearchChanged: (query) => player.setPlaylistSearch(query)
                    onBackRequested: window.returnToLibrary()
                }

                LibraryPanel {
                    anchors.fill: parent
                    controller: player
                    accent: window.accent
                    open: window.libraryOpen
                    onPickFolderRequested: libraryFolderDialog.open()
                    onActivated: (folder) => window.openLibraryPlaylist(folder)
                }

                QualityPanel {
                    anchors.fill: parent
                    controller: player.quality
                    accent: window.accent
                    open: window.qualityOpen
                }

                EffectsPanel {
                    anchors.fill: parent
                    controller: player.audiofx
                    accent: window.accent
                    open: window.effectsOpen
                }

                SettingsPanel {
                    anchors.fill: parent
                    controller: player
                    accent: window.accent
                    open: window.settingsOpen
                }
            }

            // 底部控制列
            Item {
                id: bottomBar
                // objectName 讓診斷工具能精準定位這些關鍵元件。
                // QML 的 id 在執行期取不到，型別名稱又會被混淆，
                // 沒有 objectName 就只能從截圖猜版面問題。
                objectName: "bottomBar"
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: Motion.windowMargin
                anchors.bottomMargin: window.cinema
                                      ? Motion.windowMargin + shell.height * 0.09
                                      : Motion.windowMargin
                height: 108

                Behavior on anchors.bottomMargin {
                    NumberAnimation {
                        duration: Motion.scene
                        easing.type: Easing.BezierSpline
                        easing.bezierCurve: Motion.emphasizedDecelerate
                    }
                }

                SeekBar {
                    id: seek
                    objectName: "seekBar"
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
                    font.pixelSize: (11) * Appearance.fontScale
                    font.family: "Consolas"
                }
                Text {
                    id: timeRight
                    anchors.right: parent.right
                    anchors.verticalCenter: seek.verticalCenter
                    text: player.durationText
                    color: Qt.rgba(1, 1, 1, 0.45)
                    font.pixelSize: (11) * Appearance.fontScale
                    font.family: "Consolas"
                }

                TransportControls {
                    objectName: "transport"
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
                        onClicked: {
                            window.playlistFromLibrary = false;
                            window.togglePanel("library");
                        }
                    }
                    IconButton {
                        icon: "list"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.playlistOpen
                        onClicked: {
                            window.playlistFromLibrary = false;
                            window.togglePanel("playlist");
                        }
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
                    IconButton {
                        icon: "equalizer"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.effectsOpen
                        onClicked: window.togglePanel("effects")
                    }
                    IconButton {
                        icon: "settings"; flat: true; width: 38; height: 38; iconScale: 0.8
                        color: "white"; glow: window.accent
                        active: window.settingsOpen
                        onClicked: window.togglePanel("settings")
                    }
                }
            }
        }

        // -------------------------------------------------------- 電影感疊加

        Item {
            id: miniPlayer
            anchors.fill: parent
            anchors.margins: 12
            visible: window.miniMode

            // 整個迷你播放器的空白、封面與文字區都可拖動視窗。
            // 這個 MouseArea 刻意放在最底層；後方宣告的操作按鈕會優先
            // 接收點擊，因此拖曳不會吞掉播放或關閉事件。
            MouseArea {
                id: miniWindowDragSurface
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                cursorShape: Qt.SizeAllCursor
                onPressed: (mouse) => {
                    if (!window.startSystemMove()) {
                        mouse.accepted = false;
                    }
                }
            }

            Rectangle {
                id: miniCover
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(116, parent.height)
                height: width
                radius: 12
                color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.20)
                border.width: 1
                border.color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.55)
                Image {
                    anchors.fill: parent; anchors.margins: 2
                    source: player.coverUrl; fillMode: Image.PreserveAspectCrop
                    asynchronous: true; visible: source !== ""
                }
                Text {
                    anchors.centerIn: parent; visible: player.coverUrl === ""
                    text: "♫"; color: Qt.rgba(1, 1, 1, 0.70); font.pixelSize: 38
                }
            }

            Row {
                id: miniActions
                anchors.top: parent.top
                anchors.right: parent.right
                spacing: 2
                z: 3
                IconButton {
                    icon: "fullscreen"; flat: true; width: 30; height: 30; iconScale: 0.64
                    color: "white"; glow: window.accent; onClicked: window.toggleMiniMode()
                }
                IconButton {
                    icon: "close"; flat: true; width: 30; height: 30; iconScale: 0.64
                    color: "white"; glow: "#FF5F57"; onClicked: window.close()
                }
            }

            Item {
                id: miniDragArea
                anchors.top: parent.top
                anchors.left: miniCover.right
                anchors.leftMargin: 14
                anchors.right: miniActions.left
                anchors.rightMargin: 8
                height: 38
                z: 1
            }

            Text {
                anchors.top: parent.top
                anchors.left: miniDragArea.left
                anchors.right: miniDragArea.right
                anchors.topMargin: 3
                text: player.title
                color: "white"
                font.pixelSize: 16 * Appearance.fontScale
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                z: 2
            }
            Text {
                anchors.top: parent.top
                anchors.topMargin: 39
                anchors.left: miniDragArea.left
                anchors.right: parent.right
                text: player.artist + (player.album ? " · " + player.album : "")
                color: Qt.rgba(1, 1, 1, 0.55)
                font.pixelSize: 11 * Appearance.fontScale
                elide: Text.ElideRight
            }
            Item {
                anchors.left: miniDragArea.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 48
                Row {
                    anchors.centerIn: parent
                    spacing: 12
                    Item {
                        width: 36; height: 40
                        IconButton {
                            anchors.centerIn: parent
                            icon: "prev"; flat: true; width: 36; height: 36; iconScale: 0.72
                            color: "white"; glow: window.accent; onClicked: player.playPrevious()
                        }
                    }
                    Item {
                        width: 40; height: 40
                        IconButton {
                            anchors.centerIn: parent
                            icon: player.playing ? "pause" : "play"; flat: false; width: 40; height: 40
                            color: "white"; glow: window.accent; onClicked: player.togglePlay()
                        }
                    }
                    Item {
                        width: 36; height: 40
                        IconButton {
                            anchors.centerIn: parent
                            icon: "next"; flat: true; width: 36; height: 36; iconScale: 0.72
                            color: "white"; glow: window.accent; onClicked: player.playNext()
                        }
                    }
                }
            }
        }

        PostStack {
            anchors.fill: parent
            tint: window.accent
            bass: audio.bass
            grainEnabled: motion.grainEnabled
            vignetteStrength: window.cinema ? 0.46 : 0.30
            visible: !window.miniMode
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

        Item {
            id: startup
            anchors.fill: parent
            z: 100
            visible: !window.introDone
            opacity: 1
            Rectangle { anchors.fill: parent; color: "#06110C" }
            Item {
                id: startupMark
                anchors.centerIn: parent
                width: window.miniMode ? 112 : 180
                height: width
                scale: 0.72; opacity: 0
                Rectangle {
                    anchors.centerIn: parent
                    width: window.miniMode ? 76 : 128
                    height: width; radius: width / 2
                    color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.12)
                    border.width: 1
                    border.color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.80)
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: window.miniMode ? 58 : 96
                    height: width; radius: width / 2
                    color: Qt.rgba(window.accent.r, window.accent.g, window.accent.b, 0.16)
                }
                Text {
                    anchors.centerIn: parent; text: "♫"; color: "white"
                    font.pixelSize: window.miniMode ? 34 : 54
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.bottom; anchors.topMargin: window.miniMode ? 4 : 16
                    text: Strings.appName; color: "white"; font.pixelSize: 18
                    font.letterSpacing: 7; font.weight: Font.DemiBold
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.bottom; anchors.topMargin: 44
                    visible: !window.miniMode
                    text: Strings.appSubtitle; color: Qt.rgba(1, 1, 1, 0.46); font.pixelSize: 11
                    font.letterSpacing: 2
                }
            }
        }

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
                    font.pixelSize: (window.miniMode ? 13 : 18) * Appearance.fontScale
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    // ------------------------------------------------------------ 狀態

    /*! 右側面板一次只開一個。狀態存在設定檔裡，所以下次開啟會回到同一個面板。
        五個布林值全部由這一個字串推導 —— 布林值可以組合出「兩個都開」
        這種不存在的狀態，單一字串則從結構上就不可能。 */
    property string openPanel: player.openPanel

    readonly property bool playlistOpen: openPanel === "playlist"
    readonly property bool libraryOpen: openPanel === "library"
    readonly property bool lyricsOpen: openPanel === "lyrics"
    readonly property bool qualityOpen: openPanel === "quality"
    readonly property bool effectsOpen: openPanel === "effects"
    readonly property bool settingsOpen: openPanel === "settings"

    onOpenPanelChanged: player.setOpenPanel(openPanel)

    property bool cinema: false
    property bool fullScreen: false
    property bool miniMode: false
    property bool playlistFromLibrary: false
    property int normalWidth: 1180
    property int normalHeight: 760
    //: 進迷你模式前開著的面板，回來時要還原。
    property string panelBeforeMini: "playlist"

    function toggleFullscreen() {
        if (miniMode) { toggleMiniMode(); }
        const next = visibility !== Window.FullScreen;
        fullScreen = next;
        visibility = next ? Window.FullScreen : Window.Windowed;
    }

    onVisibilityChanged: {
        if (visibility !== Window.FullScreen) { fullScreen = false; }
    }

    function toggleMiniMode() {
        if (miniMode) {
            miniMode = false;
            width = normalWidth;
            height = normalHeight;
            // 迷你模式沒有側邊面板的空間，所以進去時收起了；回到一般模式
            // 就該回到原本的樣子，而不是留給使用者一個空盪盪的右半邊。
            openPanel = panelBeforeMini;
        } else {
            if (fullScreen) { toggleFullscreen(); }
            cinema = false;
            panelBeforeMini = openPanel;
            openPanel = "";
            normalWidth = width; normalHeight = height;
            miniMode = true; width = 540; height = 180;
        }
        player.setMiniMode(miniMode);
    }

    function togglePanel(name) {
        openPanel = (openPanel === name) ? "" : name;
    }

    function openLibraryPlaylist(folder) {
        player.loadLibraryPlaylist(folder);
        playlistPanel.clearSearch();
        playlistFromLibrary = true;
        openPanel = "playlist";
    }

    function returnToLibrary() {
        openPanel = "library";
        playlistFromLibrary = false;
    }

    // Qt 6 的 FileDialog 沒有 OpenDirectory 這個 fileMode（只有 OpenFile /
    // OpenFiles / SaveFile），指定它會得到 undefined，對話框於是以「選檔案」
    // 模式開啟，根本選不到資料夾。選資料夾在 Qt 6 是獨立的 FolderDialog。
    FolderDialog {
        id: libraryFolderDialog
        title: "選擇音樂資料夾"
        onAccepted: player.addLibraryFolder(selectedFolder)
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
        function onLibraryFolderAdded() {
            window.playlistFromLibrary = false;
            window.openPanel = "library";
        }
        function onFontScaleChanged() {
            Appearance.fontScale = player.fontScale;
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

    SequentialAnimation {
        id: introAnimation
        ParallelAnimation {
            NumberAnimation {
                target: startupMark; property: "opacity"
                from: 0; to: 1; duration: Motion.intro * 0.48
                easing.type: Easing.OutExpo
            }
            NumberAnimation {
                target: startupMark; property: "scale"
                from: 0.72; to: 1.0; duration: Motion.intro * 0.60
                easing.type: Easing.OutBack
                easing.overshoot: Motion.overshoot
            }
        }
        PauseAnimation { duration: 180 }
        NumberAnimation {
            target: startup; property: "opacity"
            from: 1; to: 0; duration: Motion.intro * 0.38
            easing.type: Easing.InQuad
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
    Shortcut { sequence: "Ctrl+M"; onActivated: window.toggleMiniMode() }
    Shortcut { sequence: "L"; onActivated: window.togglePanel("lyrics") }
    Shortcut { sequence: "Ctrl+L"; onActivated: window.togglePanel("library") }
    Shortcut { sequence: "Ctrl+O"; onActivated: libraryFolderDialog.open() }
    Shortcut { sequence: "P"; onActivated: window.togglePanel("playlist") }
    Shortcut { sequence: "I"; onActivated: window.togglePanel("quality") }
    Shortcut { sequence: "E"; onActivated: window.togglePanel("effects") }
    Shortcut { sequence: "Ctrl+,"; onActivated: window.togglePanel("settings") }
    Shortcut { sequence: "C"; onActivated: window.cinema = !window.cinema }
    Shortcut { sequence: "F11"; onActivated: window.toggleFullscreen() }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (window.miniMode) {
                window.toggleMiniMode();
            } else if (window.fullScreen) {
                window.toggleFullscreen();
            } else if (window.cinema) {
                window.cinema = false;
            } else {
                window.openPanel = "";
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
