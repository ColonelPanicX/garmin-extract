"""Textual TUI application for garmin-extract."""

from __future__ import annotations

from textual.app import App

from garmin_extract import __version__


class GarminExtractApp(App[None]):
    """garmin-extract TUI — boots to the main menu."""

    TITLE = f"garmin-extract  v{__version__}"
    SUB_TITLE = "Automated Garmin Connect data pipeline"

    def __init__(self, dry_run: bool = False, verbose: int = 0) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.verbose = verbose

    def on_mount(self) -> None:
        from garmin_extract.screens.main_menu import MainMenuScreen

        self.push_screen(MainMenuScreen())
