"""Qt-based event bus that drains Core.event_queue into Qt signals.

Runs in a dedicated QThread, polling the queue at the interval defined by
``FS_POLL_INTERVAL_SEC`` and re-emitting each event as a typed Qt signal.
"""

from PySide6.QtCore import QObject, Signal

from skjalf.config import FS_POLL_INTERVAL_SEC
from skjalf.watcher.events import (
    DirectoryUpdatedEvent,
    ErrorEvent,
    FSWatcherEvent,
    ProgressEvent,
    SearchResultEvent,
    ThumbnailReadyEvent,
)

# Mapping from event class → signal attribute name
_DISPATCH_MAP = {
    DirectoryUpdatedEvent: "directory_updated",
    SearchResultEvent: "search_result",
    FSWatcherEvent: "fs_watcher",
    ThumbnailReadyEvent: "thumbnail_ready",
    ErrorEvent: "error",
    ProgressEvent: "progress",
}


class EventBus(QObject):
    """Drains the Core event queue and forwards events as Qt signals."""

    directory_updated = Signal(object)
    search_result = Signal(object)
    fs_watcher = Signal(object)
    thumbnail_ready = Signal(object)
    error = Signal(object)
    progress = Signal(object)

    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self._running = True

    def run(self) -> None:
        """Main loop: poll the queue and dispatch events."""
        while self._running:
            try:
                event = self.queue.get(timeout=FS_POLL_INTERVAL_SEC)
                self._dispatch(event)
            except Exception:
                # Queue.get raises on timeout; all other exceptions are silently
                # swallowed so the thread keeps running.
                pass

    def _dispatch(self, event) -> None:
        for event_type, signal_name in _DISPATCH_MAP.items():
            if isinstance(event, event_type):
                getattr(self, signal_name).emit(event)
                return

    def stop(self) -> None:
        """Signal the run loop to exit."""
        self._running = False
