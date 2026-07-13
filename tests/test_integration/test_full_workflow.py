"""Integration tests for the full workflow: register → navigate → search → embed.

These tests use the mocked Core fixture to avoid real ML inference and FS monitoring.
They focus on cross-module interactions that unit tests don't cover.
"""

from pathlib import Path

from skjalf.watcher.events import (
    DirectoryUpdatedEvent,
    FolderPendingUpdated,
)


class TestRegisterAndNavigate:
    """Test the full flow: register a folder, navigate into it, get entries."""

    def test_register_then_navigate(self, mock_core, tmp_path, fake_jpeg_path):
        # Create some image files
        (tmp_path / "photo1.jpg").write_bytes(Path(fake_jpeg_path).read_bytes())
        (tmp_path / "photo2.png").write_bytes(Path(fake_jpeg_path).read_bytes())
        (tmp_path / "readme.txt").write_bytes(b"not an image")

        # Register the folder
        mock_core.register_folder(str(tmp_path))
        events = []
        while not mock_core.event_queue.empty():
            events.append(mock_core.event_queue.get_nowait())

        # Should have received a FolderPendingUpdated event
        pending_events = [e for e in events if isinstance(e, FolderPendingUpdated)]
        assert len(pending_events) >= 1

        # Navigate into the folder
        mock_core.navigate_to(str(tmp_path))
        nav_event = mock_core.event_queue.get_nowait()
        assert isinstance(nav_event, DirectoryUpdatedEvent)
        assert nav_event.path == str(tmp_path.resolve())

        names = [e.name for e in nav_event.added]
        assert "photo1.jpg" in names
        assert "photo2.png" in names
        assert "readme.txt" in names


class TestLifecycle:
    """Test full lifecycle: register → embed → deregister."""

    def test_register_embed_deregister(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()

        mock_core.start_embed_folder(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()

        mock_core.deregister_folder(str(tmp_path))
        folders = mock_core.folder_store.list_folders()
        assert str(tmp_path.resolve()) not in folders
