"""跨層傳遞的值物件。

全部是 ``frozen=True`` 的 dataclass 或 Enum —— 不用裸 dict 傳資料，
這樣型別檢查器才抓得到欄位錯字，重構時也不會漏改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TransportKind(Enum):
    """輸出裝置的傳輸型態。由端點的 enumerator 名稱 100% 判定。"""

    WIRED = "wired"
    BLUETOOTH_A2DP = "a2dp"
    BLUETOOTH_HFP = "hfp"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            TransportKind.WIRED: "有線／內建",
            TransportKind.BLUETOOTH_A2DP: "藍牙 A2DP",
            TransportKind.BLUETOOTH_HFP: "藍牙 HFP 通話模式",
            TransportKind.UNKNOWN: "未知",
        }[self]


class Confidence(Enum):
    """一項資訊的確信等級。UI 必須把這個等級顯示出來，不能讓推定值冒充實測值。"""

    MEASURED = "measured"
    """直接從系統或 PCM 讀到的事實。"""

    DERIVED = "derived"
    """由實測值唯一推導而得（例：HFP 8kHz 單聲道 ⇒ CVSD）。"""

    INFERRED = "inferred"
    """由對照表推定，可能不準。UI 標示 ⓘ推定。"""

    UNKNOWN = "unknown"
    """查不到。UI 顯示「Windows 未提供」而非留白。"""

    @property
    def badge(self) -> str:
        return {
            Confidence.MEASURED: "✓實測",
            Confidence.DERIVED: "✓推導",
            Confidence.INFERRED: "ⓘ推定",
            Confidence.UNKNOWN: "—",
        }[self]


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """一個 PCM 格式。用於檔案來源、引擎、以及輸出端點三個位置。"""

    sample_rate: int
    channels: int
    bits_per_sample: int
    is_float: bool = False

    @property
    def channel_label(self) -> str:
        return {1: "單聲道", 2: "立體聲"}.get(self.channels, f"{self.channels} 聲道")

    def describe(self) -> str:
        depth = "32-bit float" if self.is_float else f"{self.bits_per_sample}-bit"
        return f"{self.sample_rate / 1000:g} kHz / {depth} / {self.channel_label}"


@dataclass(frozen=True, slots=True)
class Track:
    """一首曲目的中繼資料。封面以外部檔案路徑引用，不把 bytes 塞進值物件。"""

    path: str
    title: str
    artist: str = ""
    album: str = ""
    duration_sec: float = 0.0
    fmt: AudioFormat | None = None
    bitrate_kbps: int | None = None
    codec: str = ""
    lossless: bool = False
    cover_path: str | None = None
    track_no: int | None = None
    year: str = ""
    mtime: float = 0.0
    size: int = 0

    @property
    def display_title(self) -> str:
        return self.title or self.path.rsplit("\\", 1)[-1]

    @property
    def display_artist(self) -> str:
        return self.artist or "未知演出者"


#: 藍牙耳機的通話端點，名稱會被系統加上這些後綴之一。
_HFP_NAME_SUFFIXES = (" hands-free ag audio", " hands-free", " hands free")


def strip_hfp_suffix(name: str) -> str:
    """去掉通話模式後綴，得到「同一支耳機」的比對基準。

    公開而不是模組私有，因為兩個不同層都要用同一套規則：平台層拿它判定
    transport，:class:`EndpointSnapshot` 拿它判定同一支耳機是否同時掛著
    A2DP 與 HFP 端點。兩邊各寫一份遲早會不一致。
    """
    lowered = name.lower()
    for suffix in _HFP_NAME_SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name.strip()


@dataclass(frozen=True, slots=True)
class EndpointInfo:
    """一個音訊輸出端點。"""

    id: str
    friendly_name: str
    description: str
    enumerator: str
    instance_id: str
    transport: TransportKind
    device_format: AudioFormat | None = None
    mix_format: AudioFormat | None = None
    #: 從 InstanceId 的 ``VID&<namespace><companyId>`` 解出的藍牙 SIG 公司代碼。
    company_id: int | None = None

    @property
    def effective_format(self) -> AudioFormat | None:
        """優先用裝置格式；沒有就退回共用混音格式。"""
        return self.device_format or self.mix_format


@dataclass(frozen=True, slots=True)
class EndpointSnapshot:
    """某一瞬間的輸出裝置狀態。

    這個型別是**平台中立**的：Windows 由 MMDevice／WASAPI 填，
    macOS 由 Core Audio 填，上層拿到的是同一個型別。
    住在 ``core/`` 而不是某個平台套件裡，是因為 ``platform/`` 的
    adapter 契約要用它當回傳型別 —— 如果它住在 ``platform_win/``，
    平台抽象層就會反過來依賴 Windows 模組，那就不是抽象了。

    **不得**在這裡加任何平台專屬欄位。
    """

    default: EndpointInfo | None = None
    active: tuple[EndpointInfo, ...] = ()

    @property
    def hfp_also_connected(self) -> bool:
        """目前走 A2DP，但同一支耳機的通話端點也在線上。

        這是實務上最常見的「音質突然變差」原因：某個程式開了麥克風，
        系統就把耳機切成通話模式。提早告訴使用者可以省下很多困惑。
        """
        if self.default is None or self.default.transport is not TransportKind.BLUETOOTH_A2DP:
            return False
        base = strip_hfp_suffix(self.default.friendly_name).lower()
        return any(
            item.transport is TransportKind.BLUETOOTH_HFP
            and strip_hfp_suffix(item.friendly_name).lower() == base
            for item in self.active
        )


@dataclass(frozen=True, slots=True)
class CodecInfo:
    """輸出編碼的判定結果，永遠附帶確信等級與推理依據。"""

    name: str
    confidence: Confidence
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RolloffResult:
    """從實際 PCM 量到的頻譜截止。"""

    enough_data: bool
    cutoff_hz: float | None = None
    label: str = "資料不足"
    estimated_kbps: int | None = None
    #: 容器宣稱無損但量測結果不像 ⇒ 疑似轉檔。
    suspected_transcode: bool = False


@dataclass(frozen=True, slots=True)
class LevelStats:
    """響度與削波統計，全部從實際 PCM 算出。"""

    rms_db: float
    peak_db: float
    #: 波峰因數（peak − RMS）。刻意不叫它 EBU R128 或 TT-DR ——
    #: 那些是有正式定義的指標，這裡算的不是，UI 上也照實標注。
    dynamic_range_db: float
    #: 削波**事件**數，不是樣本數：一段連續滿刻度只算一次。
    clipped_runs: int


@dataclass(frozen=True, slots=True)
class ChainStage:
    """訊號鏈上的一段。"""

    label: str
    detail: str
    confidence: Confidence = Confidence.MEASURED
    warn: bool = False


@dataclass(frozen=True, slots=True)
class QualityReport:
    """完整的訊號鏈報告，直接餵給 QualityPanel。"""

    stages: tuple[ChainStage, ...]
    codec: CodecInfo
    rolloff: RolloffResult
    levels: LevelStats | None = None
    stars: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Palette:
    """從封面抽出的一整套色票。全部是 ``#RRGGBB``，QML 可直接吃。"""

    accent: str
    accent2: str
    bg_top: str
    bg_bottom: str
    text_primary: str = "#F5F7FA"
    text_secondary: str = "#98A2B3"


@dataclass(frozen=True, slots=True)
class LyricWord:
    """逐字時間標籤（增強型 LRC 的 ``<mm:ss.xx>``）。"""

    time_sec: float
    text: str


@dataclass(frozen=True, slots=True)
class LyricLine:
    time_sec: float
    text: str
    words: tuple[LyricWord, ...] = ()


@dataclass(frozen=True, slots=True)
class Lyrics:
    lines: tuple[LyricLine, ...] = ()
    offset_ms: int = 0
    title: str = ""
    artist: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def has_word_timing(self) -> bool:
        return any(line.words for line in self.lines)


@dataclass(frozen=True, slots=True)
class SpectrumFrame:
    """一幀視覺化資料。條與峰值都已正規化到 0..1。"""

    bars: tuple[float, ...]
    peaks: tuple[float, ...]
    rms: float = 0.0
    bass: float = 0.0
    onset: bool = False


@dataclass(frozen=True, slots=True)
class ScanProgress:
    scanned: int
    added: int
    current_dir: str = ""
    done: bool = False
    batch: tuple[Track, ...] = field(default_factory=tuple)
