"""Main window: sidebar, main view, search bar, and event bus wiring."""

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from skjalf.watcher.embedder import Embedder
from .event_bus import EventBus
from .help_window import HelpWindow
from .main_view import MainViewWidget
from .sidebar import SidebarWidget
from ..config import DEBOUNCE_SEARCH_MS, SEARCH_RESULTS_MIN, SEARCH_RESULTS_MAX, SEARCH_RESULTS_DEFAULT, SIDEBAR_WIDTH


class MainWindow(QMainWindow):
    """Top-level application window.

    Owns the sidebar, main view, search bar, and GPU toggle.  A background
    event bus thread reads events from the Core queue and dispatches them
    to the appropriate UI handlers.
    """

    def __init__(self, core):
        super().__init__(parent=None)
        self.setWindowTitle("Skjalf")
        self.core = core
        self.event_queue = core.event_queue
        self._search_active = False

        self._build_toolbar()
        self._build_layout()
        self._start_event_bus()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        top = QWidget()
        layout = QHBoxLayout(top)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search files…")
        self._search_debounce = QTimer()
        self._search_debounce.setInterval(DEBOUNCE_SEARCH_MS)
        self._search_debounce.setSingleShot(True)
        self.search_bar.textChanged.connect(self._on_search_changed)

        clear_btn = QPushButton("X")
        clear_btn.clicked.connect(self._clear_search)

        help_btn = QPushButton("?")
        help_btn.clicked.connect(self._open_help)

        layout.addWidget(self.search_bar)
        layout.addWidget(clear_btn)
        layout.addWidget(help_btn)

        # Results limit
        results_label = QLabel("Results:")
        results_label.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        layout.addWidget(results_label)

        self._results_limit = QSpinBox()
        self._results_limit.setRange(SEARCH_RESULTS_MIN, SEARCH_RESULTS_MAX)
        self._results_limit.setValue(SEARCH_RESULTS_DEFAULT)
        self._results_limit.setToolTip(f"Number of search results to show ({SEARCH_RESULTS_MIN}–{SEARCH_RESULTS_MAX})")
        self._results_limit.valueChanged.connect(self._on_results_limit_changed)
        layout.addWidget(self._results_limit)

        # GPU toggle
        self._gpu_toggle = QCheckBox("GPU")
        self._gpu_toggle.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        self._gpu_toggle.toggled.connect(self._on_gpu_toggled)
        has_gpu = Embedder.gpu_available()
        self._gpu_toggle.setEnabled(has_gpu)
        self._gpu_toggle.setChecked(has_gpu and Embedder.device() == "cuda")
        self._gpu_toggle.setToolTip(
            "Toggle GPU acceleration for embeddings" if has_gpu
            else "No CUDA-capable GPU detected"
        )
        layout.addWidget(self._gpu_toggle)

        self._toolbar = top

    def _build_layout(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)

        middle_layout = QHBoxLayout()
        self.sidebar = SidebarWidget(self.core)
        self.main_view = MainViewWidget(self.core)
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)

        middle_layout.addWidget(self.sidebar)
        middle_layout.addWidget(self.main_view, stretch=1)

        middle_widget = QWidget()
        middle_widget.setLayout(middle_layout)

        main_layout.addWidget(self._toolbar)
        main_layout.addWidget(middle_widget, stretch=1)
        self.setCentralWidget(central)

        # Convenience references
        self.directory_model = self.main_view.directory_model
        self.search_model = self.main_view.search_model

        # Signal wiring
        self.sidebar.folder_activated.connect(self._navigate)
        self.main_view.visible_rows_changed.connect(self._on_visible_rows_changed)

    def _start_event_bus(self):
        self.event_bus = EventBus(self.event_queue)
        self.event_thread = QThread()
        self.event_bus.moveToThread(self.event_thread)
        self.event_thread.started.connect(self.event_bus.run)

        # Connect event handlers
        self.event_bus.search_result.connect(self._on_search_result)
        self.event_bus.directory_updated.connect(self._on_directory_updated)
        self.event_bus.fs_watcher.connect(self._on_fs_watcher)
        self.event_bus.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.event_bus.error.connect(self._on_error)
        self.event_bus.progress.connect(self._on_progress)

        self.event_thread.start()

    # ------------------------------------------------------------------
    # Search actions
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str):
        self._search_debounce.stop()
        self._search_debounce.start()
        if not text:
            self._clear_search()
        else:
            self._search_active = True
            self.main_view.show_search()
            self.core.search(text, self._results_limit.value())

    def _on_results_limit_changed(self, _value: int):
        """Re-run search with new limit if a search is active."""
        if self._search_active:
            text = self.search_bar.text().strip()
            if text:
                self.core.search(text, self._results_limit.value())

    def _clear_search(self):
        self.search_bar.clear()
        self._search_active = False
        self.main_view.show_directory()
        self.core.clear_search()
        self.core.refresh_directory()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, path: str):
        self.core.navigate_to(path)
        # Re-run search if active so it targets the new folder
        if self._search_active:
            text = self.search_bar.text().strip()
            if text:
                self.core.search(text, self._results_limit.value())

    # ------------------------------------------------------------------
    # GPU toggle
    # ------------------------------------------------------------------

    def _on_gpu_toggled(self, checked: bool):
        Embedder.set_device("cuda" if checked else "cpu")

    # ------------------------------------------------------------------
    # Event handlers (called from event bus thread via Qt signals)
    # ------------------------------------------------------------------

    def _on_search_result(self, event):
        if not self._search_active:
            return
        if event.is_final:
            self.search_model.set_results(event.results)
            # Request thumbnails for visible rows now that the model is populated
            QTimer.singleShot(0, self.main_view._request_visible_rows)
        else:
            self.search_model.append(event.results)

    def _on_directory_updated(self, event):
        if self._search_active:
            return
        self.main_view.show_directory()
        self.directory_model.reset(event.added)

    def _on_fs_watcher(self, event):
        """Refresh directory on filesystem changes (only when not searching)."""
        if self._search_active:
            return
        self.core.refresh_directory()

    def _on_thumbnail_ready(self, event):
        """Apply incoming thumbnail data to the active model(s) and repaint."""
        updated = False

        for model in (self.directory_model, self.search_model):
            for idx, item in enumerate(model._items):
                if item.path == event.path:
                    item.thumbnail_data = event.image_data
                    model.dataChanged.emit(model.index(idx), model.index(idx))
                    updated = True
                    break

        if updated:
            # Force full repaint so thumbnails appear even without keyboard focus
            self.main_view.viewport().update()

    def _on_visible_rows_changed(self, rows):
        """Request thumbnails for newly visible rows (lazy loading on scroll)."""
        model = self.search_model if self._search_active else self.directory_model
        entries = [model.get_item(row) for row in rows if model.get_item(row)]
        if entries:
            self.core.request_thumbnails(entries)

    def _on_error(self, event):
        logger.warning(f"[ui] {event.message}")

    def _on_progress(self, event):
        if event.folder:
            self.sidebar.update_progress(event.folder, event.current, event.total)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _open_help(self):
        HelpWindow(self).exec()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self.event_bus.stop()
        self.event_thread.quit()
        self.event_thread.wait()
        self.core.stop()
        super().closeEvent(event)
