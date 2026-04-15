"""PySide6 application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from garmin_extract import __version__
from garmin_extract.gui.main_window import MainWindow
from garmin_extract.gui.theme import DARK_STYLESHEET


def run(dry_run: bool = False, verbose: int = 0) -> None:
    """Launch the PySide6 GUI."""
    app = QApplication(sys.argv)
    app.setApplicationName("garmin-extract")
    app.setApplicationVersion(__version__)
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
