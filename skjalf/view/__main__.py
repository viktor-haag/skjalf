"""Application entry point."""

import sys

from loguru import logger
from PySide6.QtWidgets import QApplication, QDialog

from skjalf.view.main_window import MainWindow
from skjalf.view.model_download_dialog import ModelDownloadDialog
from skjalf.view.model_loading_dialog import ModelLoadingDialog
from skjalf.watcher.core import Core
from skjalf.watcher.embedder import Embedder


def main() -> None:
    app = QApplication(sys.argv)

    # Check if model files are available; download if needed
    if not Embedder.model_available():
        dialog = ModelDownloadDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.was_successful():
            logger.error("Could not download model.")
            sys.exit(1)

    # Load model into memory and warm up (runs in background thread)
    loading = ModelLoadingDialog()
    if loading.exec() != QDialog.DialogCode.Accepted or not loading.was_successful():
        logger.error("Could not load model.")
        sys.exit(1)

    core = Core()
    core.start()
    window = MainWindow(core)
    window.show()
    window.resize(1000, 600)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
