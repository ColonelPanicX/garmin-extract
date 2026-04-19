"""Main window — sidebar navigation + stacked content area."""

from __future__ import annotations

import platform

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from garmin_extract import __version__
from garmin_extract.gui.screens.automation import AutomationPage
from garmin_extract.gui.screens.pull_data import PullDataPage
from garmin_extract.gui.screens.setup import SetupPage

_WINDOWS = platform.system() == "Windows"


class MainWindow(QMainWindow):
    """Top-level window with a left sidebar and swappable content panels."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"garmin-extract  v{__version__}")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        nav_items = (
            ("Pull Data", "Automation")
            if _WINDOWS
            else ("Initial Setup", "Pull Data", "Automation")
        )
        for label in nav_items:
            self.sidebar.addItem(label)
        self.sidebar.setCurrentRow(0)
        layout.addWidget(self.sidebar)

        # ── Content area ──────────────────────────────
        self.stack = QStackedWidget()
        if not _WINDOWS:
            self.stack.addWidget(SetupPage())
        self.stack.addWidget(PullDataPage())
        self.stack.addWidget(AutomationPage())
        layout.addWidget(self.stack)

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
