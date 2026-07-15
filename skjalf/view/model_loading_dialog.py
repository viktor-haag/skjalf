"""Dialog shown while the embedding model loads into memory."""

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from skjalf.watcher.embedder import Embedder


class _ModelLoadWorker(QObject):
    """Background worker that loads and warms up the model."""

    finished = Signal()
    error = Signal(str)

    def run(self) -> None:
        try:
            Embedder.warm_up()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class ModelLoadingDialog(QDialog):
    """Shows a loading indicator while the model loads into memory."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint)
        self.setFixedSize(360, 120)
        self.setWindowTitle("Loading Model")
        self._success = False

        self._setup_ui()
        self._start_loading()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._label = QLabel("Loading embedding model into memory…")
        layout.addWidget(self._label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # indeterminate
        layout.addWidget(self._progress)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._cancel_btn)

    def _start_loading(self):
        self._thread = QThread(self)
        self._worker = _ModelLoadWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _on_finished(self):
        self._success = True
        self._progress.setFormat("Model loaded!")
        self._cancel_btn.setEnabled(False)
        self.accept()
        self._thread.quit()
        self._thread.wait()

    def _on_error(self, message: str):
        self._thread.quit()
        self._thread.wait()
        self.reject()
        self._last_error = message

    def was_successful(self) -> bool:
        return self._success
