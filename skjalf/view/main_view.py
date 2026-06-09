"""Main content view: icon grid with lazy thumbnail loading."""

from pathlib import Path

from PySide6.QtCore import QModelIndex, QUrl, Qt, QSize, QRect, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QIcon, QPixmap, QPalette, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QInputDialog,
    QListView,
    QMenu,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from .file_op_dialog import FileOperationDialog
from .models import DirectoryModel, SearchModel
from ..config import DEBOUNCE_SCROLL_MS, GRID_SIZE, ICON_SIZE
from ..utils import safe_delete


# ------------------------------------------------------------------
# Item delegate
# ------------------------------------------------------------------

class AlignedDelegate(QStyledItemDelegate):
    """Paints items in a grid with the image centered above the text.

    Selected items are drawn with a green highlight.  The layout mirrors
    Windows Explorer: uniform cells, image anchored to top, text wrapped at bottom.
    """

    def __init__(self, grid_size: QSize, parent=None):
        super().__init__(parent)
        self._grid_size = grid_size

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return self._grid_size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # Background highlight for selected items
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(144, 238, 144, 100))
            painter.drawRect(option.rect)
            painter.restore()

        rect = option.rect
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        icon = index.data(Qt.ItemDataRole.DecorationRole)

        painter.save()
        painter.setClipRect(rect)

        # Layout: text block at bottom, image above it
        fm = painter.fontMetrics()
        text_height = fm.height() * 2 + 8
        text_rect = QRect(rect.left() + 4, rect.bottom() - text_height, rect.width() - 8, text_height - 4)
        image_max_height = rect.height() - text_rect.height() - 6
        image_rect = QRect(rect.left() + 4, rect.top(), rect.width() - 8, image_max_height)

        # Draw image
        if isinstance(icon, QIcon):
            icon.paint(painter, image_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       QIcon.Mode.Normal, QIcon.State.On)
        elif isinstance(icon, QPixmap):
            scaled = icon.scaled(image_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            x = image_rect.center().x() - scaled.width() // 2
            y = image_rect.bottom() - scaled.height()
            painter.drawPixmap(x, y, scaled)

        # Draw text
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QColor(40, 40, 40))
        else:
            painter.setPen(option.palette.color(QPalette.ColorRole.Text))

        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.TextWordWrap, text)
        painter.restore()


# ------------------------------------------------------------------
# Main view widget
# ------------------------------------------------------------------

class MainViewWidget(QListView):
    """Icon-grid view for browsing directories and search results.

    Supports multi-selection, context menus, drag-and-drop, and lazy
    thumbnail loading (thumbnails are only requested for rows currently
    visible in the viewport).
    """

    # Emitted when the set of visible rows changes (scroll or layout).
    visible_rows_changed = Signal(list)  # list[int] of visible row indices

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.directory_model = DirectoryModel()
        self.search_model = SearchModel()
        self.setModel(self.directory_model)

        # View appearance
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(*ICON_SIZE))
        self.setGridSize(QSize(*GRID_SIZE))
        self.setUniformItemSizes(True)
        self.setItemDelegate(AlignedDelegate(QSize(*GRID_SIZE), self))
        self.setWordWrap(False)
        self.setMovement(QListView.Movement.Static)

        # Multi-selection: Ctrl+Click, Shift+Click, rubber band
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Drag-and-drop (drop-only)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self._search_active = False

        # Lazy thumbnail: debounced scroll handler
        self._scroll_debounce = QTimer(self)
        self._scroll_debounce.setInterval(DEBOUNCE_SCROLL_MS)
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.timeout.connect(self._request_visible_rows)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ------------------------------------------------------------------
    # Lazy thumbnail visibility
    # ------------------------------------------------------------------

    def _on_scroll(self, _value: int):
        """Restart debounce timer on scroll; request visible rows when settled."""
        self._scroll_debounce.start()

    def _request_visible_rows(self):
        """Compute visible rows and emit the signal."""
        rows = self._get_visible_rows()
        if rows:
            self.visible_rows_changed.emit(rows)

    def _get_visible_rows(self) -> list[int]:
        """Return row indices whose visual rects intersect the viewport (+ margin)."""
        model = self.model()
        if not model:
            return []
        total = model.rowCount()
        if not total:
            return []

        vp_rect = self.viewport().rect()
        margin = self.gridSize()
        vp_rect = vp_rect.adjusted(-margin.width(), -margin.height(), margin.width(), margin.height())

        return [row for row in range(total)
                if self.visualRect(model.index(row)).intersects(vp_rect)]

    # ------------------------------------------------------------------
    # Model switching
    # ------------------------------------------------------------------

    def show_directory(self):
        """Switch to the directory model and request initial thumbnails."""
        self._search_active = False
        self.setModel(self.directory_model)
        QTimer.singleShot(0, self._request_visible_rows)

    def show_search(self):
        """Switch to the search model and request initial thumbnails."""
        self._search_active = True
        self.setModel(self.search_model)
        QTimer.singleShot(0, self._request_visible_rows)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            model = self.search_model if self._search_active else self.directory_model
            item = model.get_item(index.row())
            if item:
                if item.is_dir:
                    self._open_dir(item.path)
                else:
                    self._open_file(item.path)
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Context menu (multi-item)
    # ------------------------------------------------------------------

    def _show_menu(self, pos):
        indices = self.selectedIndexes()
        if not indices:
            index = self.indexAt(pos)
            if not index.isValid():
                return
            indices = [index]

        model = self.search_model if self._search_active else self.directory_model
        items = [model.get_item(idx.row()) for idx in indices if model.get_item(idx.row())]
        if not items:
            return

        menu = QMenu()
        all_files = all(not it.is_dir for it in items)
        all_dirs = all(it.is_dir for it in items)
        single = len(items) == 1

        if single:
            item = items[0]
            if item.is_dir:
                menu.addAction("Open").triggered.connect(lambda: self._open_dir(item.path))
            else:
                menu.addAction("Open").triggered.connect(lambda: self._open_file(item.path))
            menu.addSeparator()
        elif all_dirs:
            menu.addAction("Open all").triggered.connect(lambda: [self._open_dir(it.path) for it in items])
            menu.addSeparator()

        n = len(items)
        menu.addAction(f"Delete ({n})").triggered.connect(lambda: self._delete_items([it.path for it in items]))
        menu.addAction("Copy").triggered.connect(lambda: self._copy_items([it.path for it in items]))
        menu.addAction("Move").triggered.connect(lambda: self._move_items([it.path for it in items]))

        if single:
            menu.addAction("Rename").triggered.connect(lambda: self._rename_item(items[0].path))

        menu.exec(self.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _open_dir(self, path: str):
        self.core.navigate_to(path)

    def _open_file(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _delete_items(self, paths: list[str]) -> None:
        n = len(paths)
        msg = f"Delete {paths[0]}?" if n == 1 else f"Delete {n} items?"
        if QMessageBox.question(self, "Confirm", msg) == QMessageBox.StandardButton.Yes:
            for path in paths:
                try:
                    safe_delete(Path(path))
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not delete {Path(path).name}:\n{e}")
            self.core.refresh_directory()

    def _rename_item(self, path: str) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=Path(path).name)
        if ok and new_name:
            new_path = Path(path).parent / new_name
            try:
                Path(path).rename(new_path)
                self.core.refresh_directory()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _copy_items(self, paths: list[str]) -> None:
        dest_dir = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if dest_dir:
            dialog = FileOperationDialog("copy", paths, Path(dest_dir), self,
                                         on_finished=self.core.refresh_directory)
            dialog.exec()

    def _move_items(self, paths: list[str]) -> None:
        dest_dir = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if dest_dir:
            dialog = FileOperationDialog("move", paths, Path(dest_dir), self,
                                         on_finished=self.core.refresh_directory)
            dialog.exec()
