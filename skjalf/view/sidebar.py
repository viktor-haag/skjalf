"""Sidebar widget: registered folders with embedding progress bars."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..config import SIDEBAR_ICON_SIZE


# ------------------------------------------------------------------
# Single folder row (icon + name + optional progress bar)
# ------------------------------------------------------------------

class _FolderRow(QWidget):
    """A single sidebar row: folder icon + name on top, progress bar below."""

    def __init__(self, name: str, icon: QIcon, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self.setAcceptDrops(False)  # Let the parent QListWidget handle drops

        layout = QVBoxLayout(self, spacing=2)
        layout.setContentsMargins(4, 2, 4, 2)

        # Icon + label row
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon.pixmap(*SIDEBAR_ICON_SIZE))
        top.addWidget(icon_lbl)

        lbl = QLabel(name)
        lbl.setToolTip(path)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        top.addWidget(lbl, stretch=1)
        layout.addLayout(top)

        # Progress bar (hidden until embedding starts)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setFixedHeight(14)
        self.progress.setFormat("%p%")
        layout.addWidget(self.progress)

    def set_progress(self, current: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
            if not self.progress.isVisible():
                self.progress.setVisible(True)
        else:
            self.progress.setVisible(False)

    def hide_progress(self) -> None:
        self.progress.setVisible(False)


# ------------------------------------------------------------------
# Sidebar widget
# ------------------------------------------------------------------

class SidebarWidget(QListWidget):
    """List of registered folders with drag-and-drop registration.

    Signals:
        folder_activated: emitted when a folder row is clicked (navigate).
        folder_registered / folder_deregistered: emitted after register/deregister.
    """

    folder_activated = Signal(str)
    folder_registered = Signal(str)
    folder_deregistered = Signal(str)

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core

        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemClicked.connect(self._on_clicked)

        self._folder_rows: dict[str, _FolderRow] = {}
        self._folder_items: dict[str, QListWidgetItem] = {}

        self.refresh()

    # -- Public API ----------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the sidebar from registered folders."""
        self.clear()
        self._folder_rows.clear()
        self._folder_items.clear()

        folder_icon = QIcon.fromTheme("folder")
        for path in self.core.folder_store.list_folders():
            name = Path(path).name or path
            row = _FolderRow(name, folder_icon, path)
            item = QListWidgetItem(self)
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)

            # Index by both raw and resolved path for flexible lookups
            for key in (path, str(Path(path).resolve())):
                self._folder_rows[key] = row
                self._folder_items[key] = item

    def update_progress(self, folder: str, current: int, total: int) -> None:
        """Update the progress bar for *folder*."""
        row, item = self._lookup(folder)
        if row is None:
            return

        if 0 < current < total:
            row.set_progress(current, total)
            if item and row.progress.isVisible():
                item.setSizeHint(row.sizeHint())
        elif current >= total > 0:
            row.set_progress(current, total)
            row.hide_progress()
            if item:
                item.setSizeHint(row.sizeHint())
        else:
            row.set_progress(current, total)

    # -- Internal helpers ----------------------------------------------------

    def _lookup(self, folder: str):
        """Find row and item by raw path, resolved path, or folder name."""
        row = self._folder_rows.get(folder)
        item = self._folder_items.get(folder)
        if row is None:
            resolved = str(Path(folder).resolve())
            row = self._folder_rows.get(resolved)
            item = self._folder_items.get(resolved)
        if row is None:
            name = Path(folder).name
            for key, r in self._folder_rows.items():
                if Path(key).name == name:
                    row = r
                    item = self._folder_items.get(key)
                    break
        return row, item

    # -- Interaction ---------------------------------------------------------

    def _on_clicked(self, item):
        widget = self.itemWidget(item)
        if widget and hasattr(widget, "_path"):
            self.folder_activated.emit(widget._path)

    def _show_menu(self, pos):
        item = self.itemAt(pos)
        menu = QMenu()
        if item:
            widget = self.itemWidget(item)
            path = widget._path if widget and hasattr(widget, "_path") else ""
            menu.addAction("Deregister").triggered.connect(lambda: self._deregister(path))
        else:
            menu.addAction("Register folder…").triggered.connect(self._register)
        menu.exec(self.mapToGlobal(pos))

    def _register(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder to register")
        if path:
            self.core.register_folder(path)
            self.refresh()
            self.folder_registered.emit(path)

    def _deregister(self, path: str):
        self.core.deregister_folder(path)
        self.refresh()
        self.folder_deregistered.emit(path)

    # -- Drag & drop (external folders) --------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        """Register dropped folders that aren't already registered."""
        registered = {str(Path(p).resolve()) for p in self.core.folder_store.list_folders()}

        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if not path:
                continue
            resolved = str(Path(path).resolve())
            if resolved not in registered:
                self.core.register_folder(path)
                registered.add(resolved)

        self.refresh()
        event.acceptProposedAction()
