"""Tests for Core.register_folder and Core.deregister_folder."""

from skjalf.watcher.events import FolderPendingUpdated


class TestRegisterFolder:
    def test_register_adds_to_store(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        folders = mock_core.folder_store.list_folders()
        assert str(tmp_path.resolve()) in folders

    def test_register_tracks_in_memory(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        assert tmp_path.resolve() in mock_core._registered

    def test_register_updates_pending_count(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        # Should emit a FolderPendingUpdated event
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, FolderPendingUpdated)
        assert event.folder == str(tmp_path.resolve())


class TestDeregisterFolder:
    def test_deregister_removes_from_store(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()
        mock_core.deregister_folder(str(tmp_path))
        folders = mock_core.folder_store.list_folders()
        assert str(tmp_path.resolve()) not in folders

    def test_deregister_removes_from_memory(self, mock_core, tmp_path):
        mock_core.register_folder(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()
        mock_core.deregister_folder(str(tmp_path))
        assert tmp_path.resolve() not in mock_core._registered
