"""Google Drive / Sheets export screen — Phase 5."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

_W = 53
_ITEMS = [
    ("1", "Upload CSVs to Drive", "Upload garmin_daily.csv + activities.csv"),
    ("2", "Sync to Google Sheets", "Create / update a Garmin Data spreadsheet"),
    ("3", "Both (Drive + Sheets)", "Upload CSVs and sync spreadsheet"),
]
_EMPTY_ROW = "  │" + " " * _W + "│"


def _build_menu(cursor: int = 0) -> str:
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


class DriveSheetsScreen(Screen[None]):
    """Google Drive / Sheets export landing screen."""

    _ITEM_COUNT = 3

    BINDINGS = [
        Binding("1", "do_drive", show=False),
        Binding("2", "do_sheets", show=False),
        Binding("3", "do_both", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("enter", "cursor_select", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    DriveSheetsScreen {
        layout: vertical;
        padding: 2 4;
    }

    #ds-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #ds-auth {
        height: auto;
        margin-bottom: 1;
    }

    #ds-last {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }

    #ds-menu {
        width: 57;
        color: $text;
    }

    #ds-hint {
        width: 57;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    #ds-status {
        height: auto;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Google Drive / Sheets", id="ds-header")
        yield Static("Checking authorization…", id="ds-auth")
        yield Static("", id="ds-last")
        yield Static(_build_menu(0), id="ds-menu")
        yield Static(
            "↑↓  j/k  navigate  ·  enter  select  ·  1–3  direct  ·  b  back",
            id="ds-hint",
        )
        yield Static("", id="ds-status")
        yield Footer()

    def on_mount(self) -> None:
        self._cursor = 0
        self.run_worker(self._check_auth, thread=True, name="ds-auth-check")

    def on_screen_resume(self) -> None:
        self.run_worker(self._check_auth, thread=True, name="ds-auth-check")

    def _refresh_menu(self) -> None:
        self.query_one("#ds-menu", Static).update(_build_menu(self._cursor))

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._refresh_menu()

    def action_cursor_down(self) -> None:
        if self._cursor < self._ITEM_COUNT - 1:
            self._cursor += 1
            self._refresh_menu()

    def action_cursor_select(self) -> None:
        [self.action_do_drive, self.action_do_sheets, self.action_do_both][self._cursor]()

    # ── auth status ──────────────────────────────────────────────────────────

    def _check_auth(self) -> None:
        from garmin_extract._google_drive import check_auth, load_config

        status, detail = check_auth()
        cfg = load_config()
        last = cfg.get("last_export")

        if status == "ok":
            auth_text = "[green]✓[/] Drive and Sheets authorized"
        elif status == "missing_scopes":
            auth_text = f"[yellow]⚠[/]  {detail}"
        else:
            auth_text = f"[red]✗[/]  {detail}"

        last_text = ""
        if last:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(last).astimezone(None)  # local timezone
                last_text = f"Last export: {dt.strftime('%Y-%m-%d %H:%M')}"
            except Exception:
                last_text = f"Last export: {last[:19]}"

        self.app.call_from_thread(self._apply_auth, auth_text, last_text)

    def _apply_auth(self, auth_text: str, last_text: str) -> None:
        self.query_one("#ds-auth", Static).update(auth_text)
        self.query_one("#ds-last", Static).update(last_text)

    # ── actions ──────────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self.query_one("#ds-status", Static).update(text)

    def action_do_drive(self) -> None:
        self._cursor = 0
        self._refresh_menu()
        self._set_status("[dim]Uploading CSVs to Drive…[/]")
        self.run_worker(self._run_drive, thread=True, exclusive=True, name="ds-drive")

    def action_do_sheets(self) -> None:
        self._cursor = 1
        self._refresh_menu()
        self._set_status("[dim]Syncing to Google Sheets…[/]")
        self.run_worker(self._run_sheets, thread=True, exclusive=True, name="ds-sheets")

    def action_do_both(self) -> None:
        self._cursor = 2
        self._refresh_menu()
        self._set_status("[dim]Uploading CSVs and syncing Sheets…[/]")
        self.run_worker(self._run_both, thread=True, exclusive=True, name="ds-both")

    # ── workers ──────────────────────────────────────────────────────────────

    def _run_drive(self) -> None:
        from garmin_extract._google_drive import upload_csvs_to_drive

        result = upload_csvs_to_drive()
        if result["ok"]:
            names = "  ·  ".join(f["name"] for f in result["files"])
            text = f"[green]✓[/] Uploaded: {names}\n[dim]{result['folder_link']}[/]"
        else:
            text = f"[red]✗[/]  {result['error']}"
        self.app.call_from_thread(self._apply_result, text)

    def _run_sheets(self) -> None:
        from garmin_extract._google_drive import sync_to_sheets

        result = sync_to_sheets()
        if result["ok"]:
            text = f"[green]✓[/] Google Sheet updated\n[dim]{result['sheet_url']}[/]"
        else:
            text = f"[red]✗[/]  {result['error']}"
        self.app.call_from_thread(self._apply_result, text)

    def _run_both(self) -> None:
        from garmin_extract._google_drive import sync_to_sheets, upload_csvs_to_drive

        lines = []

        drive_result = upload_csvs_to_drive()
        if drive_result["ok"]:
            names = "  ·  ".join(f["name"] for f in drive_result["files"])
            lines.append(f"[green]✓[/] Drive: {names}")
        else:
            lines.append(f"[red]✗[/] Drive: {drive_result['error']}")

        sheets_result = sync_to_sheets()
        if sheets_result["ok"]:
            lines.append(f"[green]✓[/] Sheets updated\n[dim]{sheets_result['sheet_url']}[/]")
        else:
            lines.append(f"[red]✗[/] Sheets: {sheets_result['error']}")

        self.app.call_from_thread(self._apply_result, "\n".join(lines))

    def _apply_result(self, text: str) -> None:
        self._set_status(text)
        # Refresh last-export timestamp
        self.run_worker(self._check_auth, thread=True, name="ds-auth-refresh")

    # ── navigation ───────────────────────────────────────────────────────────

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
