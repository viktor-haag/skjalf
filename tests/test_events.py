"""Tests for event dataclasses."""

import pytest

from skjalf.watcher.events import (
    DirectoryUpdatedEvent,
    EmbeddingCancelled,
    EmbeddingStarted,
    ErrorEvent,
    FileEntry,
    FolderPendingUpdated,
    FSWatcherEvent,
    ProgressEvent,
    SearchResultEvent,
    ThumbnailReadyEvent,
)


class TestFileEntry:
    def test_create_file_entry(self):
        entry = FileEntry(path="/tmp/img.jpg", name="img.jpg", is_dir=False)
        assert entry.path == "/tmp/img.jpg"
        assert entry.name == "img.jpg"
        assert not entry.is_dir
        assert entry.size is None
        assert entry.modified is None
        assert entry.thumbnail_data is None

    def test_create_dir_entry(self):
        entry = FileEntry(path="/tmp/photos", name="photos", is_dir=True)
        assert entry.is_dir

    def test_entry_with_optional_fields(self):
        entry = FileEntry(
            path="/tmp/img.jpg",
            name="img.jpg",
            is_dir=False,
            size=1024,
            modified=1234567890.0,
            thumbnail_data=b"data",
        )
        assert entry.size == 1024
        assert entry.modified == 1234567890.0
        assert entry.thumbnail_data == b"data"


class TestDirectoryUpdatedEvent:
    @pytest.mark.parametrize("field", ["added", "removed", "modified"])
    def test_stores_each_list(self, field):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        kwargs = {"added": [], "removed": [], "modified": []}
        kwargs[field] = entries
        event = DirectoryUpdatedEvent(path="/tmp", **kwargs)

        assert event.path == "/tmp"
        assert getattr(event, field) == entries
        # The other two fields should be empty
        for other in ("added", "removed", "modified"):
            if other != field:
                assert getattr(event, other) == []


class TestThumbnailReadyEvent:
    def test_create_event(self):
        event = ThumbnailReadyEvent(path="/img.jpg", image_data=b"thumb")
        assert event.path == "/img.jpg"
        assert event.image_data == b"thumb"


class TestSearchResultEvent:
    def test_intermediate_result(self):
        event = SearchResultEvent(query="cat", results=[], is_final=False)
        assert not event.is_final
        assert event.results == []

    def test_final_result(self):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        event = SearchResultEvent(query="cat", results=entries, is_final=True)
        assert event.is_final
        assert len(event.results) == 1


class TestFSWatcherEvent:
    def test_created_event(self):
        event = FSWatcherEvent(event_type="created", src_path="/new.jpg")
        assert event.event_type == "created"
        assert event.src_path == "/new.jpg"
        assert event.dst_path is None

    def test_moved_event(self):
        event = FSWatcherEvent(
            event_type="moved", src_path="/old.jpg", dst_path="/new.jpg"
        )
        assert event.dst_path == "/new.jpg"


class TestErrorEvent:
    def test_message_only(self):
        event = ErrorEvent(message="something broke")
        assert event.message == "something broke"
        assert event.context is None

    def test_with_context(self):
        event = ErrorEvent(message="fail", context="search")
        assert event.context == "search"


class TestProgressEvent:
    def test_progress_event(self):
        event = ProgressEvent(operation="embed", current=5, total=100, folder="/photos")
        assert event.operation == "embed"
        assert event.current == 5
        assert event.total == 100
        assert event.folder == "/photos"

    def test_progress_without_folder(self):
        event = ProgressEvent(operation="other", current=1, total=10)
        assert event.folder is None


class TestFolderPendingUpdated:
    def test_pending_updated(self):
        event = FolderPendingUpdated(folder="/photos", pending_count=42)
        assert event.folder == "/photos"
        assert event.pending_count == 42


class TestEmbeddingStarted:
    def test_started(self):
        event = EmbeddingStarted(folder="/photos")
        assert event.folder == "/photos"


class TestEmbeddingCancelled:
    def test_cancelled(self):
        event = EmbeddingCancelled(folder="/photos")
        assert event.folder == "/photos"
