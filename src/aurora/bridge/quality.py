"""音質面板的 ViewModel，兼輸出裝置監控。

每兩秒輪詢一次預設輸出端點 —— Windows 沒有便宜可靠的變更通知機制
（``IMMNotificationClient`` 是 COM 回呼，在 ctypes 下實作成本很高），
而輪詢兩秒對「換耳機」這種事件已經夠即時。

Signals
-------
``reportChanged()``
    訊號鏈任一段有變動。
``deviceChanged(str)``
    預設輸出裝置換了，帶新裝置名稱。UI 用它跳 toast。
``hfpWarning(bool)``
    掉進／脫離藍牙通話模式。這是實務上最常見的音質崩壞原因。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal

from aurora.audio.engine import AudioEngine
from aurora.core.btcodec import HostContext, default_table, resolve_codec
from aurora.core.constants import ENDPOINT_POLL_MS
from aurora.core.models import (
    CodecInfo,
    Confidence,
    QualityReport,
    RolloffResult,
    Track,
    TransportKind,
)
from aurora.core.quality import build_report
from aurora.platform_win.btregistry import radio_usb_vid
from aurora.platform_win.endpoint import EndpointSnapshot, query_endpoints
from aurora.platform_win.osinfo import windows_build

_UNKNOWN_CODEC = CodecInfo("未知", Confidence.UNKNOWN, ())


class QualityController(QObject):
    """組裝訊號鏈報告並監看輸出裝置。"""

    reportChanged = Signal()
    deviceChanged = Signal(str)
    hfpWarning = Signal(bool)
    outputRateChanged = Signal(int)

    def __init__(self, engine: AudioEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._table = default_table()
        self._context = HostContext(windows_build(), self._table.radio_for_vid(radio_usb_vid()))
        self._snapshot = EndpointSnapshot()
        self._track: Track | None = None
        self._report = self._build()
        self._was_hfp = False

        self._timer = QTimer(self)
        self._timer.setInterval(ENDPOINT_POLL_MS)
        self._timer.timeout.connect(self.refresh_endpoint)

    def start(self) -> None:
        self.refresh_endpoint()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------ 屬性

    @Property(str, notify=reportChanged)
    def codecName(self) -> str:
        return self._report.codec.name

    @Property(str, notify=reportChanged)
    def codecBadge(self) -> str:
        return self._report.codec.confidence.badge

    @Property(bool, notify=reportChanged)
    def codecIsInferred(self) -> bool:
        return self._report.codec.confidence is Confidence.INFERRED

    @Property(str, notify=reportChanged)
    def deviceName(self) -> str:
        endpoint = self._snapshot.default
        return endpoint.friendly_name if endpoint else "沒有輸出裝置"

    @Property(str, notify=reportChanged)
    def transportLabel(self) -> str:
        endpoint = self._snapshot.default
        return endpoint.transport.label if endpoint else "未知"

    @Property(str, notify=reportChanged)
    def endpointFormat(self) -> str:
        endpoint = self._snapshot.default
        fmt = endpoint.effective_format if endpoint else None
        return fmt.describe() if fmt else "—"

    @Property(int, notify=reportChanged)
    def stars(self) -> int:
        return self._report.stars

    @Property(bool, notify=reportChanged)
    def isHandsFree(self) -> bool:
        endpoint = self._snapshot.default
        return endpoint is not None and endpoint.transport is TransportKind.BLUETOOTH_HFP

    @Property(list, notify=reportChanged)
    def stages(self) -> list[dict[str, object]]:
        """訊號鏈各段。QML 用 Repeater 直接吃這個清單。"""
        return [
            {
                "label": stage.label,
                "detail": stage.detail,
                "badge": stage.confidence.badge,
                "warn": stage.warn,
            }
            for stage in self._report.stages
        ]

    @Property(list, notify=reportChanged)
    def warnings(self) -> list[str]:
        return list(self._report.warnings)

    @Property(list, notify=reportChanged)
    def codecReasons(self) -> list[str]:
        return list(self._report.codec.reasons)

    @Property(str, notify=reportChanged)
    def measurementProgress(self) -> str:
        frames = self._engine.analyzer.analysed_frames
        return "" if self._report.rolloff.enough_data else f"量測中… 已取樣 {frames} 框"

    # ------------------------------------------------------------ 更新

    def set_track(self, track: Track | None) -> None:
        self._track = track
        self.refresh()

    def refresh_endpoint(self) -> None:
        """輪詢預設輸出端點。裝置或傳輸模式有變就通知 UI。"""
        snapshot = query_endpoints()
        previous = self._snapshot.default
        current = snapshot.default
        self._snapshot = snapshot

        changed = (previous is None) != (current is None) or (
            previous is not None and current is not None and previous.id != current.id
        )
        if changed and current is not None:
            self.deviceChanged.emit(current.friendly_name)
            fmt = current.effective_format
            if fmt is not None:
                self.outputRateChanged.emit(fmt.sample_rate)

        is_hfp = current is not None and current.transport is TransportKind.BLUETOOTH_HFP
        if is_hfp != self._was_hfp:
            self._was_hfp = is_hfp
            self.hfpWarning.emit(is_hfp)

        self.refresh()

    def refresh(self) -> None:
        report = self._build()
        if report != self._report:
            self._report = report
            self.reportChanged.emit()

    def _build(self) -> QualityReport:
        endpoint = self._snapshot.default
        codec = (
            resolve_codec(endpoint, self._context, self._table)
            if endpoint is not None
            else _UNKNOWN_CODEC
        )
        rolloff = (
            self._engine.analyzer.rolloff(
                lossless_container=self._track.lossless,
                source_sample_rate=self._track.fmt.sample_rate if self._track.fmt else None,
            )
            if self._track is not None
            else RolloffResult(enough_data=False)
        )
        return build_report(
            track=self._track,
            engine_format=self._engine.output_format,
            endpoint=endpoint,
            codec=codec,
            rolloff=rolloff,
            levels=self._engine.analyzer.levels(),
            hfp_also_connected=self._snapshot.hfp_also_connected,
        )
