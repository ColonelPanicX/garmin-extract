"""Data pull screen — submenu for all pull and report options."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

_SECTION = "  [bold dim]{title}[/]\n  " + "─" * 51


def _date_range_label(days: int) -> str:
    today = date.today()
    start = today - timedelta(days=days)
    end = today - timedelta(days=1)
    return f"{start.isoformat()}  →  {end.isoformat()}"


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


class DataPullScreen(Screen[None]):
    """Submenu for pulling data and rebuilding reports."""

    _ITEM_COUNT = 7

    BINDINGS = [
        Binding("1", "pull_yesterday", show=False),
        Binding("2", "pull_7", show=False),
        Binding("3", "pull_30", show=False),
        Binding("4", "pull_custom", show=False),
        Binding("5", "pull_history", show=False),
        Binding("6", "import_zip", show=False),
        Binding("7", "rebuild_csvs", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("enter", "cursor_select", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    DataPullScreen {
        align: center middle;
    }

    #pull-menu {
        width: 57;
        height: auto;
        color: $text;
        margin-bottom: 1;
    }

    #pull-hint {
        width: 57;
        text-align: center;
        color: $text-muted;
    }

    #custom-input-container {
        width: 57;
        height: auto;
        display: none;
        padding: 1 2;
        border: round $warning;
    }

    #custom-input-container.visible {
        display: block;
    }
    """

    def _item(self, n: int, key: str, label: str, hint: str = "") -> str:
        """Render one menu item with cursor indicator if selected."""
        sel = (n - 1) == getattr(self, "_cursor", 0)
        pre = "❯ " if sel else "  "
        lbl = f"[bold]{label}[/]" if sel else label
        h = f"  [dim]{hint}[/]" if hint else ""
        return f"{pre}[bold cyan][{key}][/]  {lbl}{h}"

    def _build_menu(self) -> str:
        yest = _yesterday()
        r7 = _date_range_label(7)
        r30 = _date_range_label(30)
        _ = self._item
        return (
            f"\n"
            f"  [bold dim]RECENT[/]\n  {'─' * 51}\n"
            f"{_(1, '1', 'Yesterday', yest)}\n"
            f"{_(2, '2', 'Last 7 days', r7)}\n"
            f"{_(3, '3', 'Last 30 days', r30)}\n"
            f"\n"
            f"  [bold dim]CUSTOM[/]\n  {'─' * 51}\n"
            f"{_(4, '4', 'Specific date or range')}\n"
            f"{_(5, '5', 'Full history', '(from a date you choose)')}\n"
            f"\n"
            f"  [bold dim]IMPORT[/]\n  {'─' * 51}\n"
            f"{_(6, '6', 'Import from Garmin bulk export', '.zip')}\n"
            f"\n"
            f"  [bold dim]REPORTS[/]\n  {'─' * 51}\n"
            f"{_(7, '7', 'Rebuild CSV reports', 'from existing data')}\n"
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._build_menu(), id="pull-menu")
        yield Static(
            "↑↓  j/k  navigate  ·  enter  select  ·  1–7  direct  ·  b  back",
            id="pull-hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._cursor = 0

    def _refresh_menu(self) -> None:
        self.query_one("#pull-menu", Static).update(self._build_menu())

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._refresh_menu()

    def action_cursor_down(self) -> None:
        if self._cursor < self._ITEM_COUNT - 1:
            self._cursor += 1
            self._refresh_menu()

    def action_cursor_select(self) -> None:
        _actions = [
            self.action_pull_yesterday,
            self.action_pull_7,
            self.action_pull_30,
            self.action_pull_custom,
            self.action_pull_history,
            self.action_import_zip,
            self.action_rebuild_csvs,
        ]
        _actions[self._cursor]()

    def _push_progress(
        self,
        start_date: str,
        days: int,
        label: str,
        no_skip: bool = False,
        rebuild_only: bool = False,
    ) -> None:
        from garmin_extract.screens.pull_progress import PullProgressScreen

        self.app.push_screen(
            PullProgressScreen(
                start_date=start_date,
                days=days,
                label=label,
                no_skip=no_skip,
                rebuild_only=rebuild_only,
            )
        )

    def action_pull_yesterday(self) -> None:
        self._cursor = 0
        yest = _yesterday()
        self._push_progress(yest, 1, f"Yesterday  ({yest})")

    def action_pull_7(self) -> None:
        self._cursor = 1
        start = (date.today() - timedelta(days=7)).isoformat()
        self._push_progress(start, 7, f"Last 7 days  ({_date_range_label(7)})")

    def action_pull_30(self) -> None:
        self._cursor = 2
        start = (date.today() - timedelta(days=30)).isoformat()
        self._push_progress(start, 30, f"Last 30 days  ({_date_range_label(30)})")

    def action_pull_custom(self) -> None:
        self._cursor = 3
        self.app.push_screen(CustomDateScreen())

    def action_pull_history(self) -> None:
        self._cursor = 4
        self.app.push_screen(FullHistoryScreen())

    def action_import_zip(self) -> None:
        self._cursor = 5
        self.app.push_screen(ImportZipScreen())

    def action_rebuild_csvs(self) -> None:
        self._cursor = 6
        self._push_progress("", 0, "Rebuilding CSV reports", rebuild_only=True)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ─────────────────────────────────────────────────────────────────────────────
# Input screens for custom / history / import flows
# ─────────────────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class _InputScreen(Screen[None]):
    """Base class for single-step input screens."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    _InputScreen {
        align: center middle;
    }

    #input-box {
        width: 58;
        height: auto;
        border: round $primary;
        padding: 1 2;
    }

    #input-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #input-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #input-error {
        color: $error;
        height: 1;
    }
    """

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class CustomDateScreen(_InputScreen):
    """Prompt for a start date and optional day count."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="input-box"):
            yield Static("Custom Date Pull", id="input-title")
            yield Static(
                "Formats: YYYY-MM-DD  ·  MM/DD/YYYY  ·  MM/DD/YY",
                id="input-hint",
            )
            yield Input(placeholder="Start date", id="start-date")
            yield Input(placeholder="Number of days  (default: 1)", id="num-days")
            yield Static("", id="input-error")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "start-date":
            self.query_one("#num-days", Input).focus()
            return

        start_raw = self.query_one("#start-date", Input).value.strip()
        days_raw = self.query_one("#num-days", Input).value.strip()
        error = self.query_one("#input-error", Static)

        start = _parse_date(start_raw)
        if not start:
            error.update(f"Cannot parse '{start_raw}' — try 2025-04-07")
            self.query_one("#start-date", Input).focus()
            return

        days = int(days_raw) if days_raw.isdigit() and int(days_raw) > 0 else 1

        self._push_pull(start, days)

    def _push_pull(self, start: str, days: int) -> None:
        from garmin_extract.screens.pull_progress import PullProgressScreen

        self.app.pop_screen()
        self.app.push_screen(
            PullProgressScreen(start_date=start, days=days, label=f"Custom  ({start}, {days}d)")
        )


class FullHistoryScreen(_InputScreen):
    """Prompt for a start date for a full history pull."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="input-box"):
            yield Static("Full History Pull", id="input-title")
            yield Static(
                "Pulls every day from your chosen start date through yesterday.\n"
                "Formats: YYYY-MM-DD  ·  MM/DD/YYYY  ·  MM/DD/YY",
                id="input-hint",
            )
            yield Input(placeholder="Pull data starting from", id="start-date")
            yield Static("", id="input-error")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = self.query_one("#start-date", Input).value.strip()
        error = self.query_one("#input-error", Static)

        start = _parse_date(raw)
        if not start:
            error.update(f"Cannot parse '{raw}' — try 2023-01-01")
            return

        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
        yesterday = date.today() - timedelta(days=1)
        days = (yesterday - start_dt).days + 1

        if days <= 0:
            error.update("Start date must be before today.")
            return

        from garmin_extract.screens.pull_progress import PullProgressScreen

        self.app.pop_screen()
        self.app.push_screen(
            PullProgressScreen(
                start_date=start,
                days=days,
                label=f"Full history  ({start} → {yesterday.isoformat()})",
            )
        )


class ImportZipScreen(_InputScreen):
    """Prompt for the path to a Garmin bulk export .zip."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="input-box"):
            yield Static("Import from Garmin Bulk Export", id="input-title")
            yield Static(
                "Request your export at:\n"
                "Garmin Connect → Profile → Account → Your Garmin Data\n"
                "The .zip file arrives within 24–48 hours.",
                id="input-hint",
            )
            yield Input(placeholder="Path to export .zip", id="zip-path")
            yield Static("", id="input-error")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = self.query_one("#zip-path", Input).value.strip().strip("'\"")
        error = self.query_one("#input-error", Static)

        if not raw:
            return

        if not Path(raw).exists():
            error.update(f"File not found: {raw}")
            return

        from garmin_extract.screens.pull_progress import PullProgressScreen

        self.app.pop_screen()
        self.app.push_screen(
            PullProgressScreen(
                start_date="",
                days=0,
                label="Garmin bulk export import",
                zip_path=raw,
            )
        )
