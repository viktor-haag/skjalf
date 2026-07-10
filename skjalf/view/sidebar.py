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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import SIDEBAR_ICON_SIZE


# ------------------------------------------------------------------
# Single folder row (icon + name + optional progress bar)
# ------------------------------------------------------------------

class _FolderRow(QWidget):
    """A single sidebar row: folder icon + name on top, progress bar below."""

    play_clicked = Signal(str)   # Folder path when play is clicked
    pause_clicked = Signal(str)  # Folder path when pause is clicked

    def __init__(self, name: str, icon: QIcon, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._embed_state = "idle"  # "idle", "in_progress", "complete"
        self.setAcceptDrops(False)  # Let the parent QListWidget handle drops

        layout = QVBoxLayout(self, spacing=2)
        layout.setContentsMargins(4, 2, 4, 2)

        # Icon + label row WITH play/pause button
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)

        # Play/Pause button (to the left of folder icon)
        self._play_button = QPushButton()
        self._play_button.setFixedSize(24, 24)
        self._play_button.setFlat(True)
        self._play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_play_icon("idle")
        top.addWidget(self._play_button)

        # Folder icon + label
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

        # Connect play button click
        self._play_button.clicked.connect(self._on_play_clicked)

    def _set_play_icon(self, state: str) -> None:
        """Set the play button appearance based on embed state."""
        if state == "idle":
            # Red play icon — clickable to start embedding
            self._play_button.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: red;
                }
                QPushButton:hover {
                    color: darkred;
                }
            """)
            self._play_button.setText("▶")
            self._play_button.setEnabled(True)
        elif state == "in_progress":
            # Red pause icon — clickable to cancel
            self._play_button.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: red;
                }
            """)
            self._play_button.setText("⏸")
            self._play_button.setEnabled(True)
        elif state == "complete":
            # Green indicator lamp — not clickable
            self._play_button.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: green;
                }
            """)
            self._play_button.setText("●")
            self._play_button.setEnabled(False)

    def set_embed_state(self, state: str) -> None:
        """Update the play button and progress bar for the given embed state."""
        self._embed_state = state
        self._set_play_icon(state)

    def _on_play_clicked(self):
        if self._embed_state == "idle":
            self.play_clicked.emit(self._path)
        elif self._embed_state == "in_progress":
            self.pause_clicked.emit(self._path)

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

        # Connect play/pause signals from folder rows
        self._on_play_clicked = self._handle_play_clicked
        self._on_pause_clicked = self._handle_pause_clicked

        self.refresh()

    # -- Public API ----------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the sidebar from registered folders."""
        # Save embed states before destroying widgets, so they survive rebuilds.
        saved_states: dict[str, str] = {}
        for row in self._folder_rows.values():
            saved_states[row._path] = row._embed_state

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

            # Restore previously saved embed state.
            if path in saved_states:
                row.set_embed_state(saved_states[path])

            # Index by both raw and resolved path for flexible lookups
            for key in (path, str(Path(path).resolve())):
                self._folder_rows[key] = row
                self._folder_items[key] = item

            # Connect play/pause signals
            row.play_clicked.connect(self._handle_play_clicked)
            row.pause_clicked.connect(self._handle_pause_clicked)

    def update_progress(self, folder: str, current: int, total: int) -> None:
        """Update the progress bar for *folder*."""
        row, item = self._lookup(folder)
        if row is None:
            return

        if 0 < current < total:
            row.set_progress(current, total)
            # Ensure button is in "in_progress" state while actively embedding
            if row._embed_state != "in_progress":
                row.set_embed_state("in_progress")
            if item and row.progress.isVisible():
                item.setSizeHint(row.sizeHint())
        elif current >= total > 0:
            row.set_progress(current, total)
            row.hide_progress()
            # Embedding complete — transition to green lamp
            row.set_embed_state("complete")
            if item:
                item.setSizeHint(row.sizeHint())
        else:
            row.set_progress(current, total)

    def update_pending_status(self, folder: str, pending_count: int) -> None:
        """Update the play button state based on pending file count."""
        row, item = self._lookup(folder)
        if row is None:
            return

        if pending_count > 0:
            # Has unembedded files — show red play button
            row.set_embed_state("idle")
        else:
            # All files embedded — show green lamp
            row.set_embed_state("complete")
            row.hide_progress()

    def set_embedding_state(self, folder: str, state: str) -> None:
        """Set the embedding state (called when embedding starts or is cancelled)."""
        row, item = self._lookup(folder)
        if row is None:
            return

        if state == "in_progress":
            row.set_embed_state("in_progress")
            # Progress bar will be shown via update_progress() events
        elif state == "idle":
            # Embedding was cancelled — recalculate pending and show play button
            # This is handled by the FolderPendingUpdated event, but ensure consistency
            # We don't change the icon here; let the pending count update drive it
            pass

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

    def _handle_play_clicked(self, path: str) -> None:
        """Handle play button click — start embedding."""
        self.core.start_embed_folder(path)

    def _handle_pause_clicked(self, path: str) -> None:
        """Handle pause button click — cancel current embedding."""
        self.core.cancel_embed_folder(path)

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
