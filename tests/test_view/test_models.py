"""Tests for Qt models (DirectoryModel, SearchModel, FileListModel)."""

import pytest
from PySide6.QtCore import Qt

from skjalf.view.models import DirectoryModel, SearchModel, _filtered
from skjalf.watcher.events import FileEntry


class TestFiltered:
    def test_keeps_directories(self):
        entries = [FileEntry(path="/d", name="d", is_dir=True)]
        assert len(_filtered(entries)) == 1

    def test_keeps_image_files(self):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        assert len(_filtered(entries)) == 1

    def test_removes_non_image_files(self):
        entries = [FileEntry(path="/a.txt", name="a.txt", is_dir=False)]
        assert len(_filtered(entries)) == 0

    def test_mixed_filtering(self):
        entries = [
            FileEntry(path="/d", name="d", is_dir=True),
            FileEntry(path="/a.jpg", name="a.jpg", is_dir=False),
            FileEntry(path="/a.txt", name="a.txt", is_dir=False),
        ]
        filtered = _filtered(entries)
        assert len(filtered) == 2
        assert filtered[0].name == "d"
        assert filtered[1].name == "a.jpg"


class TestDirectoryModel:
    @pytest.fixture
    def model(self):
        return DirectoryModel()

    def test_initial_row_count(self, model):
        assert model.rowCount() == 0

    def test_reset_populates_model(self, model):
        entries = [
            FileEntry(path="/a.jpg", name="a.jpg", is_dir=False),
            FileEntry(path="/b", name="b", is_dir=True),
        ]
        model.reset(entries)
        assert model.rowCount() == 2

    def test_data_returns_name(self, model):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        model.reset(entries)
        idx = model.index(0)
        assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "a.jpg"

    def test_get_item(self, model):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        model.reset(entries)
        item = model.get_item(0)
        assert item.name == "a.jpg"

    def test_get_item_out_of_range(self, model):
        assert model.get_item(0) is None

    def test_add_items(self, model):
        model.add_items([FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)])
        assert model.rowCount() == 1

    def test_remove_paths(self, model):
        model.reset([FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)])
        model.remove_paths(["/a.jpg"])
        assert model.rowCount() == 0

    def test_thumbnail_preservation(self, model):
        """Thumbnails should survive a model reset."""
        entries_with_thumb = [
            FileEntry(
                path="/a.jpg", name="a.jpg", is_dir=False, thumbnail_data=b"thumb1"
            )
        ]
        model.reset(entries_with_thumb)
        # Reset with new entries that share the same path
        new_entries = [
            FileEntry(path="/a.jpg", name="a.jpg", is_dir=False, thumbnail_data=None)
        ]
        model.reset(new_entries)
        item = model.get_item(0)
        assert item.thumbnail_data == b"thumb1"


class TestSearchModel:
    @pytest.fixture
    def model(self):
        return SearchModel()

    def test_set_results(self, model):
        entries = [FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)]
        model.set_results(entries)
        assert model.rowCount() == 1

    def test_append_results(self, model):
        model.set_results([FileEntry(path="/a.jpg", name="a.jpg", is_dir=False)])
        model.append([FileEntry(path="/b.jpg", name="b.jpg", is_dir=False)])
        assert model.rowCount() == 2

    def test_set_results_filters_non_images(self, model):
        entries = [
            FileEntry(path="/a.jpg", name="a.jpg", is_dir=False),
            FileEntry(path="/a.txt", name="a.txt", is_dir=False),
        ]
        model.set_results(entries)
        assert model.rowCount() == 1
