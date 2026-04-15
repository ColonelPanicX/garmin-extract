"""Automation screens — Gmail MFA status, cron schedule, Drive/Sheets stub."""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, Static

ROOT = Path(__file__).parent.parent.parent
GMAIL_CREDS_FILE = ROOT / "google_credentials.json"
GMAIL_TOKEN_FILE = ROOT / ".google_token.json"
PULL_SCRIPT = ROOT / "scripts" / "pull-garmin.sh"
_CRON_MARKER = "# garmin-extract"

_MENU = """\

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │   [1]  Gmail MFA                                    │
  │        View automation status                       │
  │                                                     │
  │   [2]  Scheduled Pulls                              │
  │        Set up automatic daily data pull             │
  │                                                     │
  │   [3]  Google Drive / Sheets                        │
  │        Export to Google services                    │
  │                                                     │
  └─────────────────────────────────────────────────────┘\
"""


# ── cron helpers ──────────────────────────────────────────────────────────────


def _read_crontab() -> str:
    """Return current crontab contents, or empty string if none set."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _write_crontab(contents: str) -> bool:
    """Write new crontab contents. Returns True on success."""
    try:
        result = subprocess.run(
            ["crontab", "-"],
            input=contents,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _find_cron_entry(crontab: str) -> str | None:
    """Return the garmin-extract cron line, or None if not installed."""
    for line in crontab.splitlines():
        if _CRON_MARKER in line:
            return line
    return None


def _build_cron_entry(hour: int) -> str:
    return f"0 {hour} * * * {PULL_SCRIPT}  {_CRON_MARKER}"


def _install_cron(hour: int) -> tuple[bool, str]:
    """Install or replace the garmin-extract cron entry."""
    crontab = _read_crontab()
    lines = [ln for ln in crontab.splitlines() if _CRON_MARKER not in ln]
    lines.append(_build_cron_entry(hour))
    new_contents = "\n".join(lines) + "\n"
    ok = _write_crontab(new_contents)
    return ok, new_contents if ok else "Failed to write crontab"


def _remove_cron() -> tuple[bool, str]:
    """Remove the garmin-extract cron entry."""
    crontab = _read_crontab()
    lines = [ln for ln in crontab.splitlines() if _CRON_MARKER not in ln]
    new_contents = ("\n".join(lines) + "\n") if lines else ""
    ok = _write_crontab(new_contents)
    return ok, "Removed" if ok else "Failed to remove"


# ── Gmail status helper ────────────────────────────────────────────────────────


def _check_gmail_automation() -> tuple[str, str]:
    """Return (status, detail) where status is 'ok' | 'partial' | 'unconfigured'."""
    has_creds = GMAIL_CREDS_FILE.exists()
    has_token = GMAIL_TOKEN_FILE.exists()

    if not has_creds and not has_token:
        return "unconfigured", "Not set up"
    if not has_creds:
        return "partial", "google_credentials.json missing — re-run Gmail OAuth setup"
    if not has_token:
        return "partial", "Not yet authorized — run Gmail OAuth setup to generate token"

    try:
        import json as _json

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        tok = _json.loads(GMAIL_TOKEN_FILE.read_text())
        creds = Credentials(
            token=tok.get("token"),
            refresh_token=tok.get("refresh_token"),
            token_uri=tok.get("token_uri"),
            client_id=tok.get("client_id"),
            client_secret=tok.get("client_secret"),
            scopes=tok.get("scopes"),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return "ok", "Gmail automation is active — MFA codes fetched automatically"
    except Exception as exc:
        return "partial", f"Token exists but failed to validate: {exc}"


# ── AutomationScreen (landing) ────────────────────────────────────────────────


class AutomationScreen(Screen[None]):
    """Automation landing — Gmail MFA status, cron schedule, Drive/Sheets."""

    BINDINGS = [
        Binding("1", "go_gmail", "Gmail MFA", show=False),
        Binding("2", "go_cron", "Cron Schedule", show=False),
        Binding("3", "go_sheets", "Drive/Sheets", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    AutomationScreen {
        align: center middle;
    }

    #auto-header {
        width: 57;
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #auto-options {
        width: 57;
        color: $text;
    }

    #auto-hint {
        width: 57;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Automation", id="auto-header")
        yield Static(_MENU, id="auto-options")
        yield Static("Press  1  2  3  to select  ·  b  to go back", id="auto-hint")
        yield Footer()

    def action_go_gmail(self) -> None:
        self.app.push_screen(GmailMfaScreen())

    def action_go_cron(self) -> None:
        self.app.push_screen(CronScreen())

    def action_go_sheets(self) -> None:
        from garmin_extract.screens.drive_sheets import DriveSheetsScreen

        self.app.push_screen(DriveSheetsScreen())

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ── GmailMfaScreen ────────────────────────────────────────────────────────────


class GmailMfaScreen(Screen[None]):
    """Gmail MFA automation status screen."""

    BINDINGS = [
        Binding("s", "go_setup", "Go to Setup", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    GmailMfaScreen {
        layout: vertical;
        padding: 2 4;
    }

    #gmail-mfa-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
    }

    #gmail-mfa-creds {
        height: auto;
        margin-bottom: 1;
    }

    #gmail-mfa-token {
        height: auto;
        margin-bottom: 1;
    }

    #gmail-mfa-status {
        height: auto;
        margin-bottom: 2;
    }

    #gmail-mfa-hint {
        color: $text-muted;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Gmail MFA Automation", id="gmail-mfa-header")
        yield Static("Checking…", id="gmail-mfa-creds")
        yield Static("", id="gmail-mfa-token")
        yield Static("", id="gmail-mfa-status")
        yield Static("", id="gmail-mfa-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._check, thread=True, name="gmail-mfa-check")

    def _check(self) -> None:
        has_creds = GMAIL_CREDS_FILE.exists()
        has_token = GMAIL_TOKEN_FILE.exists()
        status, detail = _check_gmail_automation()

        creds_text = (
            "[green]✓[/] google_credentials.json found"
            if has_creds
            else "[red]✗[/] google_credentials.json not found"
        )
        token_text = (
            "[green]✓[/] Authorization token present"
            if has_token
            else "[yellow]○[/] Not yet authorized"
        )

        if status == "ok":
            status_text = (
                "[green]● Gmail automation is active[/]"
                "  —  MFA codes will be fetched automatically"
            )
            hint_text = ""
            show_setup = False
        else:
            status_text = (
                "[dim]Not configured[/]" if status == "unconfigured" else f"[yellow]⚠[/]  {detail}"
            )
            hint_text = "Press  [bold]s[/]  to go to Initial Setup → Gmail OAuth"
            show_setup = True

        self.app.call_from_thread(
            self._apply_state, creds_text, token_text, status_text, hint_text, show_setup
        )

    def _apply_state(
        self,
        creds_text: str,
        token_text: str,
        status_text: str,
        hint_text: str,
        show_setup: bool,
    ) -> None:
        self.query_one("#gmail-mfa-creds", Static).update(creds_text)
        self.query_one("#gmail-mfa-token", Static).update(token_text)
        self.query_one("#gmail-mfa-status", Static).update(status_text)
        self.query_one("#gmail-mfa-hint", Static).update(hint_text)
        self.BINDINGS = [
            Binding("s", "go_setup", "Go to Setup", show=show_setup),
            Binding("b", "back", "Back", show=True),
            Binding("q", "quit", "Quit", show=True),
        ]
        self.refresh_bindings()

    def action_go_setup(self) -> None:
        from garmin_extract.screens.setup import SetupScreen

        self.app.push_screen(SetupScreen())

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ── _EditTimeModal ─────────────────────────────────────────────────────────────


class _EditTimeModal(ModalScreen[int | None]):
    """Modal to pick cron hour (0–23)."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]

    CSS = """
    _EditTimeModal {
        align: center middle;
    }

    #edit-time-box {
        width: 52;
        height: auto;
        border: round $accent;
        padding: 1 2;
    }

    #edit-time-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #edit-time-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #edit-time-error {
        color: $error;
        height: 1;
    }
    """

    def __init__(self, current_hour: int = 6) -> None:
        super().__init__()
        self._current_hour = current_hour

    def compose(self) -> ComposeResult:
        with Static(id="edit-time-box"):
            yield Static("Set Pull Time", id="edit-time-title")
            yield Static(
                f"Enter hour in 24h format (0–23).  Current: {self._current_hour:02d}:00",
                id="edit-time-hint",
            )
            yield Input(
                placeholder="6",
                value=str(self._current_hour),
                id="edit-time-input",
                max_length=2,
            )
            yield Static("", id="edit-time-error")

    def on_mount(self) -> None:
        self.query_one("#edit-time-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            hour = int(event.value.strip())
            if not 0 <= hour <= 23:
                raise ValueError
        except ValueError:
            self.query_one("#edit-time-error", Static).update(
                "Enter a whole number between 0 and 23."
            )
            return
        self.dismiss(hour)


# ── CronScreen ─────────────────────────────────────────────────────────────────


class CronScreen(Screen[None]):
    """Cron schedule management screen."""

    BINDINGS = [
        Binding("i", "install", "Enable / Re-enable", show=True),
        Binding("e", "edit_time", "Change Time", show=True),
        Binding("r", "remove", "Disable", show=True),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    CronScreen {
        layout: vertical;
        padding: 2 4;
    }

    #cron-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
    }

    #cron-status {
        height: auto;
        margin-bottom: 1;
    }

    #cron-entry {
        color: $text-muted;
        height: auto;
        margin-bottom: 2;
    }

    #cron-feedback {
        height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._installed = False
        self._current_hour = 6

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Scheduled Pulls", id="cron-header")
        yield Static("Checking schedule…", id="cron-status")
        yield Static("", id="cron-entry")
        yield Static("", id="cron-feedback")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_cron_display()

    def on_screen_resume(self) -> None:
        self._refresh_cron_display()

    def _refresh_cron_display(self) -> None:
        self.run_worker(self._check_cron, thread=True, exclusive=True)

    def _check_cron(self) -> None:
        crontab = _read_crontab()
        entry = _find_cron_entry(crontab)

        if entry:
            try:
                hour = int(entry.split()[1])
            except (IndexError, ValueError):
                hour = 6
            self.app.call_from_thread(self._apply_state, True, hour, entry.strip())
        else:
            self.app.call_from_thread(self._apply_state, False, 6, "")

    def _apply_state(self, installed: bool, hour: int, entry: str) -> None:
        self._installed = installed
        self._current_hour = hour

        if installed:
            self.query_one("#cron-status", Static).update(
                f"[green]● Active[/]  —  pulls data every day at [bold]{hour:02d}:00[/]"
            )
            self.query_one("#cron-entry", Static).update(
                "[dim]Output is logged to  /tmp/garmin-pull.log[/]"
            )
        else:
            self.query_one("#cron-status", Static).update("[dim]Not scheduled[/]")
            self.query_one("#cron-entry", Static).update("[dim]Default pull time: 6:00 AM daily[/]")

    def action_install(self) -> None:
        ok, _ = _install_cron(self._current_hour)
        feedback = (
            f"[green]Scheduled — will pull data every day at {self._current_hour:02d}:00[/]"
            if ok
            else "[red]Failed to save schedule — check system permissions[/]"
        )
        self.query_one("#cron-feedback", Static).update(feedback)
        self._refresh_cron_display()

    def action_remove(self) -> None:
        if not self._installed:
            self.query_one("#cron-feedback", Static).update(
                "[dim]No schedule is set — nothing to disable.[/]"
            )
            return
        ok, _ = _remove_cron()
        feedback = (
            "[dim]Schedule disabled — automatic pulls are turned off.[/]"
            if ok
            else "[red]Failed to remove schedule — check system permissions[/]"
        )
        self.query_one("#cron-feedback", Static).update(feedback)
        self._refresh_cron_display()

    def action_edit_time(self) -> None:
        if not self._installed:
            self.query_one("#cron-feedback", Static).update(
                "[dim]Enable a schedule first, then use  e  to change the time.[/]"
            )
            return
        self.app.push_screen(_EditTimeModal(self._current_hour), self._on_hour_selected)

    def _on_hour_selected(self, hour: int | None) -> None:
        if hour is None:
            return
        ok, _ = _install_cron(hour)
        feedback = (
            f"[green]Updated — will pull data every day at {hour:02d}:00[/]"
            if ok
            else "[red]Failed to update schedule — check system permissions[/]"
        )
        self.query_one("#cron-feedback", Static).update(feedback)
        self._refresh_cron_display()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
