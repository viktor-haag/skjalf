"""Dialog for downloading the embedding model on first run."""

from huggingface_hub import snapshot_download
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from tqdm import tqdm

from skjalf.config import EMBEDDING_MODEL_NAME


class _TqdmSignalProxy(tqdm):
    """Custom tqdm subclass that reports progress via a class-level callback.

    Set ``_TqdmSignalProxy.callback`` to a callable ``(n, total, desc) -> None``
    before starting the download.
    """

    callback = None  # set by the worker before download

    def update(self, n=1):
        super().update(n)
        cb = self.callback
        if cb is not None and self.total and self.total > 0:
            cb(self.n, self.total, getattr(self, "desc", ""))


class _ModelDownloadWorker(QObject):
    """Background worker for model download, emits progress signals."""

    progress = Signal(int, int, str)  # bytes_downloaded, total, filename
    finished = Signal()
    error = Signal(str)

    def run(self) -> None:
        try:
            _TqdmSignalProxy.callback = self._on_progress
            snapshot_download(
                repo_id=EMBEDDING_MODEL_NAME,
                tqdm_class=_TqdmSignalProxy,
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, downloaded: int, total: int, desc: str):
        # desc typically contains the filename
        filename = desc.split()[-1] if desc else ""
        self.progress.emit(downloaded, total, filename)


class ModelDownloadDialog(QDialog):
    """Shows a progress dialog while the embedding model downloads."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setFixedSize(480, 200)
        self.setWindowTitle("Downloading Model")
        self._downloaded = False

        self._setup_ui()
        self._start_download()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._label = QLabel(
            "Downloading embedding model (kakaobrain/align-base)...\n"
            "This is a one-time download (~500 MB)."
        )
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # indeterminate initially
        layout.addWidget(self._progress)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _start_download(self):
        self._thread = QThread(self)
        self._worker = _ModelDownloadWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _on_progress(self, downloaded: int, total: int, filename: str):
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(downloaded)
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self._label.setText(
                f"Downloading {filename}...\n{mb_downloaded:.1f} / {mb_total:.1f} MB"
            )

    def _on_finished(self):
        self._downloaded = True
        self._progress.setFormat("Download complete!")
        self._cancel_btn.setEnabled(False)
        self.accept()
        self._thread.quit()
        self._thread.wait()

    def _on_error(self, message: str):
        self._thread.quit()
        self._thread.wait()
        QMessageBox.critical(
            self,
            "Download Failed",
            f"Failed to download the embedding model:\n\n{message}\n\n"
            "Please check your internet connection and try again.",
        )
        self.reject()

    def was_successful(self) -> bool:
        return self._downloaded
