"""
Textual TUI application for garmin-extract.

Phase 1: placeholder shell — confirms the package, entry point, and
routing all work before the full screen hierarchy is built in Phase 2.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from garmin_extract import __version__

_PLACEHOLDER = """\
 ┌─────────────────────────────────────────┐
 │                                         │
 │   garmin-extract  TUI                   │
 │   Phase 2 — coming soon                 │
 │                                         │
 │   The full interactive interface is     │
 │   being built. In the meantime, use:    │
 │                                         │
 │     python -m garmin_extract --no-tui   │
 │                                         │
 └─────────────────────────────────────────┘
"""


class GarminExtractApp(App[None]):
    """garmin-extract TUI (Phase 1 placeholder)."""

    TITLE = f"garmin-extract  v{__version__}"
    SUB_TITLE = "Automated Garmin Connect data pipeline"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    Screen {
        align: center middle;
        background: $surface;
    }

    #placeholder {
        width: auto;
        height: auto;
        padding: 1 2;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self, dry_run: bool = False, verbose: int = 0) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.verbose = verbose

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(_PLACEHOLDER, id="placeholder")
        yield Footer()
