"""Tests for Core.search and Core.clear_search."""

from pathlib import Path

from skjalf.watcher.events import SearchResultEvent


class TestSearch:
    def test_search_emits_intermediate_result(self, mock_core, tmp_path):
        """Search should emit an intermediate (is_final=False) event immediately."""
        # Register a folder and navigate into it
        mock_core.register_folder(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()
        mock_core.navigate_to(str(tmp_path))
        while not mock_core.event_queue.empty():
            mock_core.event_queue.get_nowait()

        # Mock embedder.query to return empty results synchronously
        def fake_query(root, query, n):
            mock_core._publish(
                SearchResultEvent(query=query, results=[], is_final=True)
            )
            return []

        mock_core.embedder.query = fake_query

        # Search — intermediate event is emitted synchronously
        mock_core.search("cat")
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, SearchResultEvent)
        assert not event.is_final
        assert event.query == "cat"

    def test_search_with_no_registered_root(self, mock_core):
        """If current path has no registered root, should emit empty final result."""
        # Navigate somewhere not registered
        tmp = Path("/tmp/nonexistent_dir_xyz")
        mock_core._current_path = tmp.resolve()

        def fake_query(root, query, n):
            return []

        mock_core.embedder.query = fake_query
        mock_core.search("test")
        # Intermediate event
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, SearchResultEvent)
        assert not event.is_final

    def test_clear_search_emits_empty_final(self, mock_core):
        mock_core.clear_search()
        event = mock_core.event_queue.get_nowait()
        assert isinstance(event, SearchResultEvent)
        assert event.is_final
        assert event.query == ""
        assert event.results == []
