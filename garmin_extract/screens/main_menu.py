"""Main menu screen — the landing screen for the TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from garmin_extract import __version__

_MENU = f"""\
  garmin-extract  v{__version__}
  Automated Garmin Connect data pipeline\
"""

_OPTIONS = """\

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │   [1]  Initial Setup                                │
  │        Configure credentials and prerequisites      │
  │                                                     │
  │   [2]  Pull Data                                    │
  │        Download your Garmin health metrics          │
  │                                                     │
  │   [3]  Automation                                   │
  │        Gmail MFA, scheduled pulls, Drive / Sheets   │
  │                                                     │
  └─────────────────────────────────────────────────────┘\
"""


class MainMenuScreen(Screen[None]):
    """Landing screen — routes to the three main sections."""

    BINDINGS = [
        Binding("1", "go_setup", "Initial Setup", show=False),
        Binding("2", "go_pull", "Pull Data", show=False),
        Binding("3", "go_automation", "Automation", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    MainMenuScreen {
        align: center middle;
    }

    #menu-header {
        width: 57;
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #menu-options {
        width: 57;
        color: $text;
    }

    #menu-hint {
        width: 57;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(_MENU, id="menu-header")
        yield Static(_OPTIONS, id="menu-options")
        yield Static("Press  1  2  3  to select  ·  q  to quit", id="menu-hint")
        yield Footer()

    def action_go_setup(self) -> None:
        from garmin_extract.screens.stub import StubScreen

        self.app.push_screen(StubScreen("Initial Setup", "Phase 3"))

    def action_go_pull(self) -> None:
        from garmin_extract.screens.data_pull import DataPullScreen

        self.app.push_screen(DataPullScreen())

    def action_go_automation(self) -> None:
        from garmin_extract.screens.stub import StubScreen

        self.app.push_screen(StubScreen("Automation", "Phase 4"))

    def action_quit(self) -> None:
        self.app.exit()
