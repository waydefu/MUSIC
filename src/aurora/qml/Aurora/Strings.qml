pragma Singleton
import QtQuick

/*! 所有 UI 文案集中在這裡。日後要做多語系只需要換這一個檔案。 */
QtObject {
    readonly property string appName: "AURORA"
    readonly property string appSubtitle: "極光播放器"

    // 傳輸控制
    readonly property string play: "播放"
    readonly property string pause: "暫停"
    readonly property string previous: "上一首"
    readonly property string next: "下一首"
    readonly property string shuffle: "隨機播放"
    readonly property string repeat: "循環模式"
    readonly property string mute: "靜音"

    // 面板
    readonly property string playlist: "播放清單"
    readonly property string lyrics: "歌詞"
    readonly property string quality: "音質"
    readonly property string library: "音樂庫"
    readonly property string settings: "設定"
    readonly property string effects: "音效"

    // 音效
    readonly property string equalizer: "等化器"
    readonly property string equalizerHint: "拉高某一段時，整條曲線會自動降低相同的量，所以音量不會變大、也不會破音。"
    readonly property string spatial: "空間音效"
    readonly property string spatialHint: "把左右不相關的殘響與環境音展開，置中的人聲與低音維持原位。"
    readonly property string resetEq: "歸零"
    readonly property string headroom: "自動餘裕"
    readonly property string addedLatency: "額外延遲"
    readonly property string effectsOff: "關閉時完全不處理訊號，也不會有延遲。"
    readonly property string limiterEngaged: "限幅器曾經作動 —— 上游有訊號超出餘裕"
    readonly property string fxDegraded: "音效發生錯誤，已自動停用"

    // 空狀態
    readonly property string emptyPlaylist: "把音樂檔或資料夾拖進來"
    readonly property string emptyPlaylistHint: "支援 MP3 · FLAC · WAV · OGG"
    readonly property string noLyrics: "這首歌沒有歌詞"
    readonly property string noLyricsHint: "把同名的 .lrc 放在音樂檔旁邊就會自動載入"
    readonly property string noTrack: "沒有播放中的曲目"

    // 音質面板
    readonly property string signalChain: "輸出鏈路"
    readonly property string codecReasons: "推理依據"
    readonly property string measuring: "量測中"
    readonly property string handsFreeWarning: "目前是藍牙通話模式，音質受限"

    // 視窗
    readonly property string minimise: "最小化"
    readonly property string miniMode: "迷你模式"
    readonly property string close: "關閉"
    readonly property string cinemaMode: "電影模式"
    readonly property string qualityPreset: "畫質"

    // 拖放
    readonly property string dropHere: "放開以加入播放清單"
}
