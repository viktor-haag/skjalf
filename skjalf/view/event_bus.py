"""Qt-based event bus that drains Core.event_queue into Qt signals.

Runs in a dedicated QThread, polling the queue at the interval defined by
``FS_POLL_INTERVAL_SEC`` and re-emitting each event as a typed Qt signal.
"""

from PySide6.QtCore import QObject, Signal

from skjalf.config import FS_POLL_INTERVAL_SEC
from skjalf.watcher.events import (
    DirectoryUpdatedEvent,
    EmbeddingCancelled,
    EmbeddingStarted,
    ErrorEvent,
    FolderPendingUpdated,
    FSWatcherEvent,
    ProgressEvent,
    SearchResultEvent,
    ThumbnailReadyEvent,
)

# Mapping from event class → signal attribute name
_DISPATCH_MAP = {
    DirectoryUpdatedEvent: "directory_updated",
    EmbeddingCancelled: "embedding_cancelled",
    EmbeddingStarted: "embedding_started",
    ErrorEvent: "error",
    FolderPendingUpdated: "folder_pending_updated",
    FSWatcherEvent: "fs_watcher",
    ProgressEvent: "progress",
    SearchResultEvent: "search_result",
    ThumbnailReadyEvent: "thumbnail_ready",
}


class EventBus(QObject):
    """Drains the Core event queue and forwards events as Qt signals."""

    directory_updated = Signal(object)
    search_result = Signal(object)
    fs_watcher = Signal(object)
    thumbnail_ready = Signal(object)
    error = Signal(object)
    progress = Signal(object)
    folder_pending_updated = Signal(object)
    embedding_started = Signal(object)
    embedding_cancelled = Signal(object)

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
