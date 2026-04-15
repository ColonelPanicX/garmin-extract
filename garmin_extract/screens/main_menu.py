"""Main menu screen — the landing screen for the TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from garmin_extract import __version__

_TITLE = f"""\
  garmin-extract  v{__version__}
  Automated Garmin Connect data pipeline\
"""

_W = 53  # inner box width
_EMPTY_ROW = "  │" + " " * _W + "│"
_ITEMS = [
    ("1", "Initial Setup", "Configure credentials and prerequisites"),
    ("2", "Pull Data", "Download your Garmin health metrics"),
    ("3", "Automation", "Gmail MFA, scheduled pulls, Drive / Sheets"),
]


def _build_menu(cursor: int) -> str:
    top = "  ┌" + "─" * _W + "┐"
    bottom = "  └" + "─" * _W + "┘"
    rows = ["\n" + top, _EMPTY_ROW]
    for i, (key, label, hint) in enumerate(_ITEMS):
        sel = i == cursor
        cur = "❯" if sel else " "
        lbl = f"[bold]{label}[/]" if sel else label
        h = f"[bold]{hint}[/]" if sel else hint
        lbl_pad = " " * (_W - 8 - len(label))
        hint_pad = " " * (_W - 8 - len(hint))
        rows.append(f"  │ {cur} [bold cyan][{key}][/]  {lbl}{lbl_pad}│")
        rows.append(f"  │        [dim]{h}[/]{hint_pad}│")
        rows.append(_EMPTY_ROW)
    rows.append(bottom)
    return "\n".join(rows)


class MainMenuScreen(Screen[None]):
    """Landing screen — routes to the three main sections."""

    BINDINGS = [
        Binding("1", "go_setup", show=False),
        Binding("2", "go_pull", show=False),
        Binding("3", "go_automation", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("enter", "cursor_select", show=False),
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
        yield Static(_TITLE, id="menu-header")
        yield Static(_build_menu(0), id="menu-options")
        yield Static(
            "↑↓  j/k  navigate  ·  enter  select  ·  1–3  direct  ·  q  quit",
            id="menu-hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._cursor = 0

    def _refresh_menu(self) -> None:
        self.query_one("#menu-options", Static).update(_build_menu(self._cursor))

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._refresh_menu()

    def action_cursor_down(self) -> None:
        if self._cursor < 2:
            self._cursor += 1
            self._refresh_menu()

    def action_cursor_select(self) -> None:
        [self.action_go_setup, self.action_go_pull, self.action_go_automation][self._cursor]()

    def action_go_setup(self) -> None:
        self._cursor = 0
        from garmin_extract.screens.setup import SetupScreen

        self.app.push_screen(SetupScreen())

    def action_go_pull(self) -> None:
        self._cursor = 1
        from garmin_extract.screens.data_pull import DataPullScreen

        self.app.push_screen(DataPullScreen())

    def action_go_automation(self) -> None:
        self._cursor = 2
        from garmin_extract.screens.automation import AutomationScreen

        self.app.push_screen(AutomationScreen())

    def action_quit(self) -> None:
        self.app.exit()
