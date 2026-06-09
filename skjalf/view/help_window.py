"""Help dialog with usage instructions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ..config import HELP_WINDOW_SIZE


class HelpWindow(QDialog):
    """Simple modal dialog showing Skjalf usage instructions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setFixedSize(*HELP_WINDOW_SIZE)

        layout = QVBoxLayout(self)
        text = (
            "Skjalf File Explorer\n\n"
            "• Use the sidebar to register folders.\n"
            "• Drag-and-drop folders onto the sidebar to register them.\n"
            "• Type natural language style search queries into search bar.\n"
            "• Right-click for context menus (Open, Delete, Rename, Copy, Move).\n"
            "• Double-click a folder to enter it.\n"
            "• Only folders and image files are displayed.\n"
            "• Database location: ~/.cache/skjalf/skjalf.db\n"
        )
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(lbl)
