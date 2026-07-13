"""Tests for Core._update_pending_count and related methods."""

from pathlib import Path

from skjalf.watcher.events import FolderPendingUpdated


class TestPendingCount:
    def test_pending_count_for_empty_folder(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        # Consume all events
        events = []
        while not mock_core.event_queue.empty():
            events.append(mock_core.event_queue.get_nowait())

        pending_events = [e for e in events if isinstance(e, FolderPendingUpdated)]
        assert len(pending_events) >= 1
        assert pending_events[-1].pending_count == 0

    def test_pending_count_for_folder_with_images(
        self, mock_core, tmp_path, fake_jpeg_path
    ):
        """Images on disk not in ChromaDB should count as pending."""
        # Copy a real image into the folder
        img = tmp_path / "test.jpg"
        img.write_bytes(Path(fake_jpeg_path).read_bytes())

        # Mock embedder.get_stored_mtime to return None (not embedded)
        mock_core.embedder.get_stored_mtime = lambda p: None

        mock_core.register_folder(str(tmp_path))
        events = []
        while not mock_core.event_queue.empty():
            events.append(mock_core.event_queue.get_nowait())

        pending_events = [e for e in events if isinstance(e, FolderPendingUpdated)]
        assert any(e.pending_count >= 1 for e in pending_events)


class TestFindRootForPath:
    def test_finds_root(self, mock_core, tmp_path):
        mock_core._registered.append(tmp_path.resolve())
        child = tmp_path / "sub" / "file.jpg"
        root = mock_core._find_root_for_path(child)
        assert root == tmp_path.resolve()

    def test_returns_none_for_unregistered(self, mock_core, tmp_path):
        root = mock_core._find_root_for_path(tmp_path / "file.jpg")
        assert root is None
