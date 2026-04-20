"""PySide6 application entry point."""

from __future__ import annotations

import platform
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from garmin_extract import __version__
from garmin_extract.gui.main_window import MainWindow
from garmin_extract.gui.theme import DARK_STYLESHEET


def run(dry_run: bool = False, verbose: int = 0) -> None:
    """Launch the PySide6 GUI."""
    app = QApplication(sys.argv)
    app.setApplicationName("garmin-extract")
    app.setApplicationVersion(__version__)
    app.setStyleSheet(DARK_STYLESHEET)

    if platform.system() == "Windows":
        from garmin_extract._browser import detect_windows_browser

        if detect_windows_browser() is None:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("No browser found")
            msg.setText("No supported browser found.")
            msg.setInformativeText(
                "garmin-extract requires Chrome, Brave, or Edge.\n"
                "Install Chrome from google.com/chrome and restart."
            )
            msg.exec()
            sys.exit(1)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
