"""watchdog-based filesystem monitoring.

Wraps a watchdog ``Observer`` and translates raw filesystem events
(create/delete/modify/move) into simple string callbacks for the Core.
"""

from collections.abc import Callable

from loguru import logger
from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer


class _FSHandler(FileSystemEventHandler):
    """Translates watchdog events into (type, src, dst) callbacks."""

    def __init__(self, on_event: Callable) -> None:
        super().__init__()
        self.on_event = on_event

    def on_any_event(self, event: FileSystemEvent) -> None:
        if isinstance(event, (FileCreatedEvent, DirCreatedEvent)):
            self.on_event("created", event.src_path, None)
            logger.debug(f"created: {event.src_path}")
        elif isinstance(event, (FileDeletedEvent, DirDeletedEvent)):
            self.on_event("deleted", event.src_path, None)
            logger.debug(f"deleted: {event.src_path}")
        elif isinstance(event, (FileModifiedEvent, DirModifiedEvent)):
            self.on_event("modified", event.src_path, None)
            logger.debug(f"modified: {event.src_path}")
        elif isinstance(event, (FileMovedEvent, DirMovedEvent)):
            self.on_event("moved", event.src_path, event.dest_path)
            logger.debug(f"moved: {event.src_path}")


class FSMonitor:
    """Wraps a watchdog Observer and translates events.

    Supports watching multiple directories simultaneously.  Events from all
    watched paths are delivered as ``(event_type, src_path, dst_path)`` tuples
    via *callback*.
    """

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._running = False

    def start(self, paths: list[str], on_event: Callable) -> None:
        """Start watching all *paths* (non-recursive) and call *on_event* for each change."""
        self.stop()
        if not paths:
            return
        self._observer = Observer()
        handler = _FSHandler(on_event)
        for path in paths:
            self._observer.schedule(handler, path, recursive=False)
        self._observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop the observer and wait for it to finish."""
        if self._running and self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join()
            except Exception:
                pass
            self._running = False
