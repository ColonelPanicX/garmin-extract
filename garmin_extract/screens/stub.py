"""
Stub screens for phases not yet built.

Displayed when the user navigates to Setup or Automation from the main
menu. Replaced by real screens in Phase 3 and Phase 4 respectively.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class StubScreen(Screen[None]):
    """Placeholder for a screen not yet built."""

    BINDINGS = [
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    StubScreen {
        align: center middle;
    }

    #stub-box {
        width: 52;
        height: auto;
        border: round $primary;
        padding: 2 4;
        content-align: center middle;
        text-align: center;
    }

    #stub-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    #stub-phase {
        color: $warning;
        margin-bottom: 1;
    }

    #stub-hint {
        color: $text-muted;
    }
    """

    def __init__(self, title: str, phase: str) -> None:
        super().__init__()
        self._title = title
        self._phase = phase

    def compose(self) -> ComposeResult:
        yield Header()
        with Static(id="stub-box"):
            yield Static(self._title, id="stub-title")
            yield Static(f"Coming in {self._phase}", id="stub-phase")
            yield Static("Press  b  to go back", id="stub-hint")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
