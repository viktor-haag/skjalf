"""Help dialog with usage instructions."""

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ..config import HELP_WINDOW_SIZE


class HelpWindow(QDialog):
    """Simple modal dialog showing Skjalf usage instructions."""

    def __init__(self, parent=None, update_info: Optional[Tuple[str, str]] = None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setFixedSize(*HELP_WINDOW_SIZE)

        layout = QVBoxLayout(self)

        # Build base text
        lines = [
            "Skjalf File Explorer\n",
            "",
            "• Use the sidebar to register folders.",
            "• Drag-and-drop folders onto the sidebar to register them.",
            "• Type natural language style search queries into search bar.",
            "• Right-click for context menus (Open, Delete, Rename, Copy, Move).",
            "• Double-click a folder to enter it.",
            "• Only folders and image files are displayed.",
            "• Database location: ~/.cache/skjalf/skjalf.db\n",
        ]

        # Add update info if available
        if update_info is not None:
            current_version, latest_version = update_info
            lines.append(f"⚠ Update available!")
            lines.append(f"Current version: {current_version}")
            lines.append(f"Latest version: {latest_version}")
            lines.append(
                "Please check our GitHub releases page for the latest version."
            )

        text = "\n".join(lines)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(lbl)
