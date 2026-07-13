"""Tests for Core.navigate_to and Core.refresh_directory."""

from skjalf.watcher.events import DirectoryUpdatedEvent


class TestNavigateTo:
    def test_navigate_emits_directory_updated(self, mock_core, tmp_path):
        mock_core.navigate_to(str(tmp_path))
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, DirectoryUpdatedEvent)
        assert event.path == str(tmp_path)

    def test_navigate_scans_directory(self, mock_core, tmp_path):
        (tmp_path / "file1.jpg").write_bytes(b"\x89PNG")
        (tmp_path / "file2.txt").write_bytes(b"text")
        mock_core.navigate_to(str(tmp_path))
        event = mock_core.event_queue.get_nowait()
        names = [e.name for e in event.added]
        assert "file1.jpg" in names
        assert "file2.txt" in names

    def test_navigate_skips_hidden_dirs(self, mock_core, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_bytes(b"data")
        mock_core.navigate_to(str(tmp_path))
        event = mock_core.event_queue.get_nowait()
        names = [e.name for e in event.added]
        assert ".git" not in names

    def test_navigate_sets_current_path(self, mock_core, tmp_path):
        mock_core.navigate_to(str(tmp_path))
        assert mock_core._current_path == tmp_path.resolve()


class TestRefreshDirectory:
    def test_refresh_emits_directory_updated(self, mock_core, tmp_path):
        mock_core.navigate_to(str(tmp_path))
        mock_core.event_queue.get_nowait()  # consume navigate event
        mock_core.refresh_directory()
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, DirectoryUpdatedEvent)

    def test_refresh_without_navigation_noop(self, mock_core):
        mock_core.refresh_directory()  # should not raise
        assert mock_core.event_queue.empty()
