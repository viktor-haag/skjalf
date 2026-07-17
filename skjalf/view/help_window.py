"""Help dialog with usage instructions."""

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QFrame

from ..config import HELP_WINDOW_SIZE


class HelpWindow(QDialog):
    """Simple modal dialog showing Skjalf usage instructions."""

    def __init__(self, parent=None, update_info: Optional[Tuple[str, str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setMinimumSize(*HELP_WINDOW_SIZE)

        layout = QVBoxLayout(self)

        # Update info box (if available)
        if update_info is not None:
            current_version, latest_version = update_info
            update_box = QFrame()
            update_box.setStyleSheet(
                "QFrame { "
                "background-color: #FDF6E3; "
                "border: 1px solid #E8D5A8; "
                "border-radius: 6px; "
                "padding: 10px; "
                "}"
            )
            update_layout = QVBoxLayout(update_box)
            update_text = (
                '<span style="color: #FF8F00; font-weight: bold; font-size: 13px;">⚠ Update available!</span><br>'
                '<span style="color: #333;">Current version: ' + current_version + '</span><br>'
                '<span style="color: #333;">Latest version: ' + latest_version + '</span><br>'
                '<span style="color: #666; font-size: 11px;">Please check our GitHub releases page for the latest version.</span>'
            )
            update_lbl = QLabel(update_text)
            update_lbl.setWordWrap(True)
            update_layout.addWidget(update_lbl)
            layout.addWidget(update_box)

        # Base help text
        base_lines = [
            "Skjalf File Explorer",
            "",
            "• Use the sidebar to register folders.",
            "• Drag-and-drop folders onto the sidebar to register them.",
            "• Type natural language style search queries into search bar.",
            "• Right-click for context menus (Open, Delete, Rename, Copy, Move).",
            "• Double-click a folder to enter it.",
            "• Only folders and image files are displayed.",
            "• Database location: ~/.cache/skjalf/skjalf.db",
        ]
        text = "<br>".join(base_lines)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(lbl)
