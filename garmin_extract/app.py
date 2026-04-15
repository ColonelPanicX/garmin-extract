"""Textual TUI application for garmin-extract."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from garmin_extract import __version__

_CONFIG_FILE = Path(__file__).parent.parent / ".garmin_config.json"


def _load_app_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_app_config(cfg: dict) -> None:
    try:
        _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


class GarminExtractApp(App[None]):
    """garmin-extract TUI — boots to the main menu."""

    TITLE = f"garmin-extract  v{__version__}"
    SUB_TITLE = "Automated Garmin Connect data pipeline"

    def __init__(self, dry_run: bool = False, verbose: int = 0) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.verbose = verbose

    def on_mount(self) -> None:
        cfg = _load_app_config()
        if saved_theme := cfg.get("theme"):
            self.theme = saved_theme
        from garmin_extract.screens.main_menu import MainMenuScreen

        self.push_screen(MainMenuScreen())

    def watch_theme(self, theme: str) -> None:
        """Persist theme selection across restarts."""
        cfg = _load_app_config()
        cfg["theme"] = theme
        _save_app_config(cfg)
