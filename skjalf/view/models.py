"""Qt models for Directory and Search views."""

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QIcon, QPixmap

from skjalf.utils import is_image_file
from skjalf.watcher.events import FileEntry


def _filtered(entries: list[FileEntry]) -> list[FileEntry]:
    """Keep only directories and image files."""
    return [e for e in entries if e.is_dir or is_image_file(e.name)]


def _preserve_thumbnails(old: list[FileEntry], new: list[FileEntry]) -> None:
    """Copy thumbnail_data from *old* items to *new* items by matching path.

    This keeps thumbnails visible across model resets (navigation, search,
    FS-triggered refresh) without re-generating them.
    """
    cache = {e.path: e.thumbnail_data for e in old if getattr(e, "thumbnail_data", None)}
    for item in new:
        if item.path in cache:
            item.thumbnail_data = cache[item.path]


# ------------------------------------------------------------------
# Shared base model
# ------------------------------------------------------------------

class FileListModel(QAbstractListModel):
    """Base model for listing files/directories in the main view.

    Provides common rowCount, data, get_item, add_items, remove_paths,
    update_items, and reset/preserve-thumbnail helpers.  Concrete
    subclasses only need to implement the operation that changes the
    full contents when the list is rebuilt (reset vs set_results).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[FileEntry] = []

    # -- QAbstractListModel interface ----------------------------------------

    def rowCount(self, index=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.name

        if role == Qt.ItemDataRole.DecorationRole:
            if item.is_dir:
                return QIcon.fromTheme("folder")
            if getattr(item, "thumbnail_data", None):
                pix = QPixmap()
                if pix.loadFromData(item.thumbnail_data):
                    return pix
            return QIcon.fromTheme("document")

        return None

    # -- Public API ----------------------------------------------------------

    def get_item(self, row: int) -> FileEntry | None:
        """Return the FileEntry at *row*, or None if out of range."""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def add_items(self, entries: list[FileEntry]) -> None:
        """Append new entries to the end of the model."""
        filtered = _filtered(entries)
        if not filtered:
            return
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items) + len(filtered) - 1)
        self._items.extend(filtered)
        self.endInsertRows()

    def remove_paths(self, paths: list[str]) -> None:
        """Remove all items whose path is in *paths*."""
        to_remove = {e.path for e in self._items if e.path in paths}
        if not to_remove:
            return
        rows = [i for i, item in enumerate(self._items) if item.path in to_remove]
        self.beginRemoveRows(QModelIndex(), min(rows), max(rows))
        self._items = [i for i in self._items if i.path not in to_remove]
        self.endRemoveRows()

    def update_items(self, entries: list[FileEntry]) -> None:
        """Replace items by matching path and emit dataChanged."""
        paths = {e.path: e for e in entries}
        for i, old in enumerate(self._items):
            new = paths.get(old.path)
            if new:
                self._items[i] = new
                self.dataChanged.emit(self.index(i), self.index(i))

    def _apply_full_reset(self, entries: list[FileEntry]) -> None:
        """Replace the entire model contents, preserving existing thumbnails."""
        old = self._items
        self._items = _filtered(entries)
        _preserve_thumbnails(old, self._items)
        self.modelReset.emit()

    def _append_filtered(self, entries: list[FileEntry]) -> None:
        """Append entries after filtering, emitting begin/end insert rows."""
        filtered = _filtered(entries)
        if not filtered:
            return
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items) + len(filtered) - 1)
        self._items.extend(filtered)
        self.endInsertRows()


# ------------------------------------------------------------------
# Directory model
# ------------------------------------------------------------------

class DirectoryModel(FileListModel):
    """Incremental model for the currently browsed folder.

    Supports add / remove / update / reset.  Thumbnail data is preserved
    across resets so already-loaded thumbnails remain visible.
    """

    def reset(self, entries: list[FileEntry]) -> None:
        """Replace the entire model contents, preserving existing thumbnail data."""
        self._apply_full_reset(entries)


# ------------------------------------------------------------------
# Search model
# ------------------------------------------------------------------

class SearchModel(FileListModel):
    """Model rebuilt for every search query.

    Like DirectoryModel, thumbnail data is preserved across set_results
    so previously loaded thumbnails don't disappear.
    """

    def set_results(self, results: list[FileEntry]) -> None:
        """Replace the model with new search results, preserving thumbnail data."""
        self._apply_full_reset(results)

    def append(self, entries: list[FileEntry]) -> None:
        """Append incremental search results."""
        self._append_filtered(entries)
