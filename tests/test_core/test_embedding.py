"""Tests for manual embedding (start_embed_folder / cancel_embed_folder)."""

from skjalf.watcher.events import (
    EmbeddingCancelled,
    EmbeddingStarted,
)


class TestStartEmbedFolder:
    def test_emits_embedding_started(self, mock_core, tmp_path):
        mock_core.start_embed_folder(str(tmp_path))
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, EmbeddingStarted)
        assert event.folder == str(tmp_path.resolve())

    def test_clears_cancel_flag(self, mock_core, tmp_path):
        root = tmp_path.resolve()
        mock_core._embed_cancel[root] = True
        mock_core.start_embed_folder(str(tmp_path))
        assert mock_core._embed_cancel[root] is False


class TestCancelEmbedFolder:
    def test_emits_embedding_cancelled(self, mock_core, tmp_path):
        mock_core.cancel_embed_folder(str(tmp_path))
        # cancel_embed_folder emits FolderPendingUpdated first (from _update_pending_count)
        # then EmbeddingCancelled
        events = []
        while not mock_core.event_queue.empty():
            events.append(mock_core.event_queue.get_nowait())
        cancelled = [e for e in events if isinstance(e, EmbeddingCancelled)]
        assert len(cancelled) == 1
        assert cancelled[0].folder == str(tmp_path.resolve())

    def test_sets_cancel_flag(self, mock_core, tmp_path):
        root = tmp_path.resolve()
        mock_core.cancel_embed_folder(str(tmp_path))
        # Consume all events
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()
        assert mock_core._embed_cancel[root] is True
