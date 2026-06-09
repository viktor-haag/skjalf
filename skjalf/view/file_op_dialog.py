"""Modal progress dialog for file copy/move operations."""

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..config import DIALOG_SIZE


# ------------------------------------------------------------------
# Background worker
# ------------------------------------------------------------------

class FileOperationWorker(QObject):
    """Performs file copy/move in a background thread and reports progress."""

    progress = Signal(int, int, str)  # current, total, filename
    finished = Signal()
    error = Signal(str)

    def __init__(self, operation: str, paths: list[str], dest: Path) -> None:
        super().__init__()
        self.operation = operation  # "copy" or "move"
        self.paths = paths
        self.dest = dest
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self.paths)
        try:
            for i, path in enumerate(self.paths):
                if self._cancelled:
                    self.finished.emit()
                    return

                src = Path(path)
                self.progress.emit(i, total, src.name)

                try:
                    target = self.dest / src.name
                    # Handle name collisions: append _1, _2, …
                    if target.exists():
                        stem = src.stem
                        suffix = src.suffix
                        n = 1
                        while target.exists():
                            target = self.dest / f"{stem}_{n}{suffix}"
                            n += 1

                    if self.operation == "copy":
                        shutil.copy2(str(src), str(target))
                    else:
                        shutil.move(str(src), str(target))
                except Exception as e:
                    self.error.emit(f"Could not {self.operation} {src.name}:\n{e}")
                    return

            self.progress.emit(total, total, "")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


# ------------------------------------------------------------------
# Dialog
# ------------------------------------------------------------------

class FileOperationDialog(QDialog):
    """Modal dialog showing progress for file copy/move operations."""

    def __init__(
            self,
            operation: str,
            paths: list[str],
            dest: Path,
            parent=None,
            on_finished=None,
    ) -> None:
        super().__init__(parent)
        self._on_finished_cb = on_finished

        self._thread: QThread | None = None
        self._worker: FileOperationWorker | None = None

        self._setup_ui(operation, len(paths))
        self._start(operation, paths, dest)

    # -- UI construction -----------------------------------------------------

    def _setup_ui(self, operation: str, count: int) -> None:
        action = "Copying" if operation == "copy" else "Moving"
        self.setWindowTitle(f"{action} files…")
        self.setModal(True)
        self.setFixedSize(*DIALOG_SIZE)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowMaximizeButtonHint
            & ~Qt.WindowType.WindowMinimizeButtonHint
        )

        layout = QVBoxLayout()
        layout.setSpacing(12)

        title = QLabel(f"{action} {count} file(s)…")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self.filename_label = QLabel("")
        self.filename_label.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(self.filename_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, count)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # -- Worker management ---------------------------------------------------

    def _start(self, operation: str, paths: list[str], dest: Path) -> None:
        self._thread = QThread()
        self._worker = FileOperationWorker(operation, paths, dest)

        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        self.progress_bar.setValue(current)
        if filename:
            self.filename_label.setText(f"{current}/{total} — {filename}")
        else:
            self.filename_label.setText("Complete")

    def _on_finished(self) -> None:
        self._thread.quit()
        self._thread.wait()
        self.close()
        if self._on_finished_cb:
            self._on_finished_cb()

    def _on_error(self, message: str) -> None:
        self._thread.quit()
        self._thread.wait()
        self.reject()
        QMessageBox.critical(self, "Error", message)

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.filename_label.setText("Cancelling…")

    # -- Lifecycle -----------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Prevent closing while the operation is still running
        if self._thread and self._thread.isRunning():
            event.ignore()
            return
        event.accept()
