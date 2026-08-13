"""播放清單 metadata 的單執行緒背景載入器。

這個類別刻意不繼承 QObject，也不從工作執行緒發 Qt signal。背景執行緒只把純
Python ``Track`` 放進結果佇列；``PlayerController`` 的 60 Hz 計時器再於主執行緒
取出並更新 QAbstractListModel。這讓 QML 模型始終遵守 Qt 的執行緒親和性規則。
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterable

from aurora.core.models import Track
from aurora.library.metadata import read_track

_STOP = object()


class MetadataLoader:
    """依序解析曲目，並以小批次把結果交還 UI 主執行緒。"""

    def __init__(self, batch_size: int = 16) -> None:
        self._batch_size = max(1, int(batch_size))
        self._requests: queue.Queue[str | object] = queue.Queue()
        self._results: queue.Queue[tuple[Track, ...]] = queue.Queue()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def request(self, paths: Iterable[str]) -> None:
        """排入尚未處理的路徑；同一路徑同時間最多只解析一次。"""
        accepted: list[str] = []
        with self._pending_lock:
            for raw_path in paths:
                path = str(raw_path)
                key = path.casefold()
                if not path or key in self._pending:
                    continue
                self._pending.add(key)
                accepted.append(path)

        if not accepted or self._stop.is_set():
            return
        for path in accepted:
            self._requests.put(path)
        self._ensure_started()

    def take_ready(self) -> tuple[Track, ...]:
        """非阻塞取出目前完成的所有批次。只從 UI 主執行緒呼叫。"""
        ready: list[Track] = []
        while True:
            try:
                ready.extend(self._results.get_nowait())
            except queue.Empty:
                return tuple(ready)

    def close(self) -> None:
        """停止接受工作；不讓單一慢速檔案拖住應用程式關閉。"""
        self._stop.set()
        self._requests.put(_STOP)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="aurora-metadata",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        batch: list[Track] = []
        while not self._stop.is_set():
            item = self._requests.get()
            if item is _STOP:
                break
            path = str(item)
            track = read_track(path)
            with self._pending_lock:
                self._pending.discard(path.casefold())
            if track is not None:
                batch.append(track)

            if len(batch) >= self._batch_size or self._requests.empty():
                if batch and not self._stop.is_set():
                    self._results.put(tuple(batch))
                batch = []

        if batch and not self._stop.is_set():
            self._results.put(tuple(batch))
