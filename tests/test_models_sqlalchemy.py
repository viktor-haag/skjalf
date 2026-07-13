"""Tests for FolderStore (SQLAlchemy persistence).

Uses an in-memory SQLite database to avoid touching the real database.
"""

import pytest

from skjalf.watcher.models import FolderStore


@pytest.fixture
def store(tmp_path):
    """Create a FolderStore with an in-memory SQLite database."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    return FolderStore(db_url)


class TestFolderStoreAdd:
    def test_add_folder_persists(self, store):
        store.add_folder("/tmp/photos")
        folders = store.list_folders()
        assert "/tmp/photos" in folders

    def test_add_duplicate_raises(self, store):
        store.add_folder("/tmp/photos")
        with pytest.raises(Exception):
            store.add_folder("/tmp/photos")

    def test_add_multiple_accumulates(self, store):
        store.add_folder("/tmp/photos")
        store.add_folder("/tmp/videos")
        assert len(store.list_folders()) == 2


class TestFolderStoreRemove:
    def test_remove_existing_folder(self, store):
        store.add_folder("/tmp/photos")
        store.remove_folder("/tmp/photos")
        folders = store.list_folders()
        assert "/tmp/photos" not in folders

    def test_remove_nonexistent_folder_no_error(self, store):
        store.remove_folder("/tmp/nonexistent")
        assert store.list_folders() == []


class TestFolderStoreList:
    def test_list_empty(self, store):
        assert store.list_folders() == []

    def test_list_returns_paths(self, store):
        store.add_folder("/a")
        store.add_folder("/b")
        assert sorted(store.list_folders()) == ["/a", "/b"]
