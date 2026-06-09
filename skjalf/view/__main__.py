"""Application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from skjalf.watcher.core import Core
from .main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    core = Core()
    core.start()
    window = MainWindow(core)
    window.show()
    window.resize(1000, 600)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
