"""Tests for EventBus signal dispatching."""

import queue
from typing import Any

import pytest

from skjalf.view.event_bus import EventBus
from skjalf.watcher.events import (
    DirectoryUpdatedEvent,
    ErrorEvent,
    SearchResultEvent,
    ThumbnailReadyEvent,
)


class TestEventBusDispatch:
    @pytest.mark.parametrize(
        "event,signal_name",
        [
            (
                DirectoryUpdatedEvent(path="/tmp", added=[], removed=[], modified=[]),
                "directory_updated",
            ),
            (
                SearchResultEvent(query="test", results=[], is_final=True),
                "search_result",
            ),
            (
                ThumbnailReadyEvent(path="/img.jpg", image_data=b"data"),
                "thumbnail_ready",
            ),
            (ErrorEvent(message="fail"), "error"),
        ],
    )
    def test_dispatches_event(self, event: Any, signal_name: str):
        q = queue.Queue()
        bus = EventBus(q)

        received = []
        getattr(bus, signal_name).connect(received.append)
        bus._dispatch(event)

        assert len(received) == 1
        assert received[0] is event

    def test_stop_sets_flag(self):
        q = queue.Queue()
        bus = EventBus(q)
        assert bus._running is True
        bus.stop()
        assert bus._running is False


class TestEventBusRun:
    def test_run_drains_queue(self, qtbot):
        """The run loop should process events from the queue."""
        q = queue.Queue()
        bus = EventBus(q)

        received = []
        bus.directory_updated.connect(received.append)

        # Put an event in the queue
        q.put(DirectoryUpdatedEvent(path="/tmp", added=[], removed=[], modified=[]))

        # Run one iteration manually (we can't easily test the full loop)
        bus._running = True
        # Simulate what run() does for one event
        event = q.get(timeout=0.1)
        bus._dispatch(event)

        assert len(received) == 1
