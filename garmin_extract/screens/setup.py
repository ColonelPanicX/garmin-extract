"""Initial Setup screens — prerequisite checks, credentials, and Gmail MFA."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, ProgressBar, RichLog, Static

ROOT = Path(__file__).parent.parent.parent
ENV_FILE = ROOT / ".env"
GMAIL_CREDS_FILE = ROOT / "google_credentials.json"
GMAIL_TOKEN_FILE = ROOT / ".google_token.json"
GMAIL_AUTH_CODE_FILE = ROOT / ".gmail_auth_code"

# ── helpers (thin wrappers so screens don't import menu.py) ──────────────────


def _check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = v >= (3, 12)
    return ok, f"Python {v.major}.{v.minor}.{v.micro}"


def _check_chrome() -> tuple[bool, str]:
    from garmin_extract.menu import _find_chrome

    found, version = _find_chrome()
    return found, version or "Not found"


def _check_xvfb() -> tuple[bool, str]:
    if platform.system() != "Linux":
        return True, f"Not required on {platform.system()}"
    import os

    if os.environ.get("DISPLAY"):
        return True, "Not needed — display available"
    from garmin_extract.menu import _find_xvfb

    found = _find_xvfb()
    return found, "Installed" if found else "Not found"


def _check_packages() -> tuple[bool, str]:
    from garmin_extract.menu import _missing_packages

    missing = _missing_packages()
    if not missing:
        return True, "All installed"
    return False, f"Missing: {', '.join(missing)}"


def _load_env() -> dict[str, str]:
    from garmin_extract.menu import load_env

    return load_env()


def _save_env(vals: dict[str, str]) -> None:
    from garmin_extract.menu import save_env

    save_env(vals)


def _check_credentials() -> tuple[bool, str]:
    from garmin_extract._credentials import check_credentials

    return check_credentials()


def _check_gmail() -> tuple[bool, str]:
    if not GMAIL_CREDS_FILE.exists():
        return False, "google_credentials.json missing"
    if not GMAIL_TOKEN_FILE.exists():
        return False, "Credentials found — not yet authorized"
    return True, "Authorized"


def _status_tag(ok: bool, text: str) -> str:
    color = "green" if ok else "yellow"
    icon = "✓" if ok else "○"
    return f"[{color}]{icon}[/]  [dim]{text}[/]"


# ── SetupScreen ───────────────────────────────────────────────────────────────


class SetupScreen(Screen[None]):
    """Landing screen for Initial Setup — shows live status for all three areas."""

    _ITEM_COUNT = 3

    BINDINGS = [
        Binding("1", "go_prereqs", show=False),
        Binding("2", "go_credentials", show=False),
        Binding("3", "go_gmail", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("enter", "cursor_select", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    SetupScreen {
        align: center middle;
    }

    #setup-menu {
        width: 57;
        height: auto;
        color: $text;
        margin-bottom: 1;
    }

    #setup-hint {
        width: 57;
        text-align: center;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._build_menu(), id="setup-menu")
        yield Static(
            "↑↓  j/k  navigate  ·  enter  select  ·  1–3  direct  ·  b  back",
            id="setup-hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._cursor = 0
        self._prereq_ok = False
        self._prereq_status = "[dim]checking…[/]"
        self._creds_ok = False
        self._creds_str = "[dim]checking…[/]"
        self._gmail_ok = False
        self._gmail_str = "[dim]checking…[/]"
        self._refresh_status()

    def on_screen_resume(self) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        self.run_worker(
            lambda: self._check_all(),
            thread=True,
            name="setup-checker",
            exclusive=True,
        )

    def _check_all(self) -> None:
        py_ok, py_str = _check_python()
        chrome_ok, chrome_str = _check_chrome()
        xvfb_ok, xvfb_str = _check_xvfb()
        pkg_ok, pkg_str = _check_packages()
        prereq_ok = py_ok and chrome_ok and xvfb_ok and pkg_ok
        prereq_parts = []
        for ok, label in [
            (py_ok, "Python"),
            (chrome_ok, "Chrome"),
            (xvfb_ok, "Xvfb"),
            (pkg_ok, "Packages"),
        ]:
            prereq_parts.append(f"[{'green' if ok else 'red'}]{label}[/]")
        prereq_status = "  ".join(prereq_parts)

        creds_ok, creds_str = _check_credentials()
        gmail_ok, gmail_str = _check_gmail()

        self.app.call_from_thread(
            self._update_menu,
            prereq_ok,
            prereq_status,
            creds_ok,
            creds_str,
            gmail_ok,
            gmail_str,
        )

    def _update_menu(
        self,
        prereq_ok: bool,
        prereq_status: str,
        creds_ok: bool,
        creds_str: str,
        gmail_ok: bool,
        gmail_str: str,
    ) -> None:
        self._prereq_ok = prereq_ok
        self._prereq_status = prereq_status
        self._creds_ok = creds_ok
        self._creds_str = creds_str
        self._gmail_ok = gmail_ok
        self._gmail_str = gmail_str
        self._redraw_menu()

    def _redraw_menu(self) -> None:
        self.query_one("#setup-menu", Static).update(
            self._build_menu(
                self._prereq_ok,
                self._prereq_status,
                self._creds_ok,
                self._creds_str,
                self._gmail_ok,
                self._gmail_str,
            )
        )

    def _build_menu(
        self,
        prereq_ok: bool = False,
        prereq_status: str = "[dim]checking…[/]",
        creds_ok: bool = False,
        creds_str: str = "[dim]checking…[/]",
        gmail_ok: bool = False,
        gmail_str: str = "[dim]checking…[/]",
    ) -> str:
        cursor = getattr(self, "_cursor", 0)
        p_icon = "[green]✓[/]" if prereq_ok else "[yellow]○[/]"
        c_icon = "[green]✓[/]" if creds_ok else "[yellow]○[/]"
        g_icon = "[green]✓[/]" if gmail_ok else "[dim]○[/]"

        def _pre(idx: int) -> str:
            return "❯ " if cursor == idx else "  "

        def _lbl(text: str, idx: int) -> str:
            return f"[bold]{text}[/]" if cursor == idx else text

        return (
            f"\n"
            f"  [bold dim]PREREQUISITES[/]\n  {'─' * 51}\n"
            f"{_pre(0)}[bold cyan][1][/]  {_lbl('Check & Install', 0)}\n"
            f"       {p_icon}  {prereq_status}\n"
            f"\n"
            f"  [bold dim]CREDENTIALS[/]\n  {'─' * 51}\n"
            f"{_pre(1)}[bold cyan][2][/]  {_lbl('Garmin Connect', 1)}\n"
            f"       {c_icon}  [dim]{creds_str}[/]\n"
            f"\n"
            f"  [bold dim]AUTOMATION[/]  [dim](optional)[/]\n  {'─' * 51}\n"
            f"{_pre(2)}[bold cyan][3][/]  {_lbl('Gmail MFA', 2)}\n"
            f"       {g_icon}  [dim]{gmail_str}[/]\n"
        )

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._redraw_menu()

    def action_cursor_down(self) -> None:
        if self._cursor < self._ITEM_COUNT - 1:
            self._cursor += 1
            self._redraw_menu()

    def action_cursor_select(self) -> None:
        [self.action_go_prereqs, self.action_go_credentials, self.action_go_gmail][self._cursor]()

    def action_go_prereqs(self) -> None:
        self._cursor = 0
        self.app.push_screen(PrereqScreen())

    def action_go_credentials(self) -> None:
        self._cursor = 1
        self.app.push_screen(CredentialsScreen())

    def action_go_gmail(self) -> None:
        self._cursor = 2
        self.app.push_screen(GmailSetupScreen())

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ── PrereqScreen ──────────────────────────────────────────────────────────────


class PrereqScreen(Screen[None]):
    """Run prerequisite checks and offer to install missing items (Linux)."""

    BINDINGS = [
        Binding("i", "install", "Install missing", show=False),
        Binding("b", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    PrereqScreen {
        layout: vertical;
    }

    #prereq-layout {
        height: 1fr;
    }

    #prereq-log {
        width: 2fr;
        border-right: solid $primary-darken-3;
    }

    #prereq-panel {
        width: 1fr;
        padding: 0 1;
    }

    #prereq-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        height: auto;
    }

    #prereq-list {
        height: auto;
        color: $text;
    }

    #prereq-status-bar {
        height: 3;
        padding: 0 1;
        border-top: solid $primary-darken-3;
    }

    #prereq-progress {
        width: 1fr;
        margin: 1 0;
    }

    #prereq-status {
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    _ITEMS = ["Python 3.12+", "Google Chrome", "Xvfb", "Python packages"]

    def __init__(self) -> None:
        super().__init__()
        self._states: dict[str, str] = {k: "pending" for k in self._ITEMS}
        self._details: dict[str, str] = {}
        self._done = False
        self._can_install = False  # set True if Linux + something failed

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="prereq-layout"):
            yield RichLog(id="prereq-log", highlight=True, markup=True, wrap=True)
            with Vertical(id="prereq-panel"):
                yield Static("Prerequisites", id="prereq-header")
                yield Static(self._render_list(), id="prereq-list")
        with Vertical(id="prereq-status-bar"):
            yield ProgressBar(total=len(self._ITEMS), id="prereq-progress", show_eta=False)
            yield Static("Running checks…", id="prereq-status")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(lambda: self._run_checks(), thread=True, name="prereq-checker")

    def on_screen_resume(self) -> None:
        """Re-run checks when navigating back from the install screen."""
        self._states = {k: "pending" for k in self._ITEMS}
        self._details = {}
        self._done = False
        self._can_install = False
        self.query_one("#prereq-progress", ProgressBar).update(progress=0)
        self.query_one("#prereq-progress", ProgressBar).display = True
        self.query_one("#prereq-list", Static).update(self._render_list())
        self.query_one("#prereq-status", Static).update("Running checks…")
        self.run_worker(
            lambda: self._run_checks(), thread=True, name="prereq-checker", exclusive=True
        )

    def _run_checks(self) -> None:
        log = self.query_one("#prereq-log", RichLog)
        checks = [
            ("Python 3.12+", _check_python),
            ("Google Chrome", _check_chrome),
            ("Xvfb", _check_xvfb),
            ("Python packages", _check_packages),
        ]
        failed: list[str] = []
        for name, fn in checks:
            self.app.call_from_thread(
                self.query_one("#prereq-status", Static).update, f"Checking {name}…"
            )
            ok, detail = fn()
            self._states[name] = "ok" if ok else "fail"
            self._details[name] = detail
            if not ok:
                failed.append(name)
            self.app.call_from_thread(self.query_one("#prereq-progress", ProgressBar).advance, 1)
            self.app.call_from_thread(
                self.query_one("#prereq-list", Static).update, self._render_list()
            )
            icon = "[green]✓[/]" if ok else "[red]✗[/]"
            self.app.call_from_thread(log.write, f"{icon}  {name}:  {detail}")

        self._done = True
        self.app.call_from_thread(self._hide_progress_bar)
        if not failed:
            self.app.call_from_thread(
                self.query_one("#prereq-status", Static).update,
                "All checks passed ✓  —  press  b  to go back",
            )
            self.app.call_from_thread(log.write, "\n[green]All prerequisites satisfied.[/green]")
        else:
            summary = ", ".join(failed)
            self.app.call_from_thread(
                self.query_one("#prereq-status", Static).update,
                f"Issues found: {summary}",
            )
            if platform.system() == "Linux":
                self._can_install = True
                self.app.call_from_thread(self._show_install_binding)
                self.app.call_from_thread(
                    log.write,
                    "\n[yellow]Press  [bold]i[/bold]  to attempt automatic installation.[/yellow]",
                )
            else:
                self.app.call_from_thread(
                    log.write,
                    "\n[yellow]Please install the missing items manually,"
                    " then re-run this check.[/yellow]",
                )

    def _hide_progress_bar(self) -> None:
        try:
            self.query_one("#prereq-progress", ProgressBar).display = False
        except Exception:
            pass

    def _show_install_binding(self) -> None:
        try:
            self.BINDINGS = [
                Binding("i", "install", "Install missing", show=True),
                Binding("b", "back", "Back", show=True),
                Binding("q", "quit", "Quit", show=True),
            ]
            self.refresh_bindings()
        except Exception:
            pass

    def _render_list(self) -> str:
        lines = []
        for item in self._ITEMS:
            state = self._states[item]
            detail = self._details.get(item, "")
            if state == "ok":
                lines.append(f"[green]✓[/] {item}\n  [dim]{detail}[/]")
            elif state == "fail":
                lines.append(f"[red]✗[/] {item}\n  [dim]{detail}[/]")
            else:
                lines.append(f"[dim]○  {item}[/]")
        return "\n".join(lines)

    def action_install(self) -> None:
        if not self._can_install:
            return
        self.app.push_screen(_InstallScreen(self._states, self._details))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class _InstallScreen(Screen[None]):
    """Run apt install commands for any failed prerequisites (Linux only)."""

    BINDINGS = [
        Binding("b", "back", "Back", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    _InstallScreen { layout: vertical; }

    #install-log { height: 1fr; }

    #install-status-bar {
        height: 3;
        padding: 0 1;
        border-top: solid $primary-darken-3;
    }

    #install-status {
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self, states: dict[str, str], details: dict[str, str]) -> None:
        super().__init__()
        self._states = states
        self._details = details
        self._done = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="install-log", highlight=True, markup=True, wrap=True)
        with Vertical(id="install-status-bar"):
            yield Static("Installing…", id="install-status")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(lambda: self._do_install(), thread=True, name="installer")

    def _do_install(self) -> None:
        import subprocess

        log = self.query_one("#install-log", RichLog)

        if self._states.get("Google Chrome") == "fail":
            self.app.call_from_thread(log.write, "[bold]Installing Google Chrome…[/bold]")
            cmds = [
                "wget -q -O - https://dl.google.com/linux/linux_signing_key.pub"
                " | sudo apt-key add -",
                'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/'
                ' stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list',
                "sudo apt-get update -q",
                "sudo apt-get install -y google-chrome-stable",
                "sudo apt-get --fix-broken install -y",
            ]
            for cmd in cmds:
                self.app.call_from_thread(log.write, f"[dim]$ {cmd}[/dim]")
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                assert proc.stdout is not None
                for line in iter(proc.stdout.readline, ""):
                    self.app.call_from_thread(log.write, line.rstrip())
                proc.wait()

        if self._states.get("Xvfb") == "fail":
            self.app.call_from_thread(log.write, "\n[bold]Installing Xvfb…[/bold]")
            proc = subprocess.Popen(
                ["sudo", "apt-get", "install", "-y", "xvfb"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                self.app.call_from_thread(log.write, line.rstrip())
            proc.wait()

        self._done = True
        self.app.call_from_thread(
            self.query_one("#install-status", Static).update,
            "Done — press  b  to re-run checks",
        )
        self.app.call_from_thread(
            log.write,
            "\n[green]Installation complete.[/green]  Press  b  to go back and re-run checks.",
        )
        self.app.call_from_thread(self._enable_back)

    def _enable_back(self) -> None:
        try:
            self.BINDINGS = [
                Binding("b", "back", "Back", show=True),
                Binding("q", "quit", "Quit", show=True),
            ]
            self.refresh_bindings()
        except Exception:
            pass

    def action_back(self) -> None:
        if self._done:
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ── CredentialsScreen ─────────────────────────────────────────────────────────


class CredentialsScreen(Screen[None]):
    """Input screen for Garmin Connect email and password."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    CredentialsScreen {
        align: center middle;
    }

    #creds-box {
        width: 62;
        height: auto;
        border: round $primary;
        padding: 1 2;
    }

    #creds-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #creds-mode {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }

    #creds-warning {
        display: none;
        color: $error;
        border: round $error;
        padding: 0 1;
        margin-bottom: 1;
    }

    #creds-warning.visible {
        display: block;
    }

    #creds-error {
        color: $error;
        height: 1;
    }

    #creds-success {
        color: $success;
        height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._keyring_available: bool | None = None  # None = still detecting

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="creds-box"):
            yield Static("Garmin Connect Credentials", id="creds-title")
            yield Static("[dim]Detecting keyring…[/]", id="creds-mode")
            yield Static("", id="creds-warning")
            yield Input(placeholder="Email", id="creds-email")
            yield Input(placeholder="Password", password=True, id="creds-password")
            yield Static("", id="creds-error")
            yield Static("", id="creds-success")
        yield Footer()

    def on_mount(self) -> None:
        from garmin_extract._credentials import load_credentials

        # Pre-fill email from wherever creds are stored
        email, _ = load_credentials()
        if email:
            self.query_one("#creds-email", Input).value = email
            self.query_one("#creds-password", Input).focus()
        else:
            self.query_one("#creds-email", Input).focus()

        self.run_worker(self._detect_keyring, thread=True, name="creds-keyring-detect")

    def _detect_keyring(self) -> None:
        from garmin_extract._credentials import detect_keyring

        ok, detail = detect_keyring()
        self.app.call_from_thread(self._apply_keyring_state, ok, detail)

    def _apply_keyring_state(self, ok: bool, detail: str) -> None:
        self._keyring_available = ok
        mode = self.query_one("#creds-mode", Static)
        warning = self.query_one("#creds-warning", Static)

        if ok:
            mode.update(f"[green]●[/]  Keyring: {detail}")
        else:
            mode.update(
                "[yellow]⚠[/]  No secure keyring available"
                " — credentials will be stored in [bold].env[/bold]"
            )
            warning.update(
                "  [bold]⚠  PLAINTEXT WARNING[/bold]\n\n"
                "  Saving will write your password to a plain-text file on disk.\n"
                "  Anyone with read access to your filesystem can see it.\n\n"
                "  [dim]enter[/dim]  →  save to .env (plaintext)\n"
                "  [dim]esc  [/dim]  →  don't save — you'll be prompted at runtime"
            )
            warning.add_class("visible")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "creds-email":
            self.query_one("#creds-password", Input).focus()
            return
        self._save()

    def _save(self) -> None:
        from garmin_extract._credentials import save_to_env, save_to_keyring

        email = self.query_one("#creds-email", Input).value.strip()
        password = self.query_one("#creds-password", Input).value.strip()
        error = self.query_one("#creds-error", Static)
        success = self.query_one("#creds-success", Static)

        if not email:
            error.update("Email is required.")
            self.query_one("#creds-email", Input).focus()
            return
        if not password:
            error.update("Password is required.")
            self.query_one("#creds-password", Input).focus()
            return

        error.update("")

        if self._keyring_available:
            ok, detail = save_to_keyring(email, password)
            if ok:
                success.update(f"✓  Saved to keyring — {email}")
            else:
                error.update(f"Keyring save failed: {detail}")
        else:
            save_to_env(email, password)
            success.update(f"✓  Saved to .env — {email}")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


# ── Gmail setup ───────────────────────────────────────────────────────────────


class _GmailCodeModal(ModalScreen[None]):
    """Modal to capture the OAuth code from the browser and write to .gmail_auth_code."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]

    CSS = """
    _GmailCodeModal {
        align: center middle;
    }

    #gmail-code-box {
        width: 90;
        height: auto;
        border: round $accent;
        padding: 1 2;
    }

    #gmail-code-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #gmail-code-url-label {
        color: $text-muted;
        margin-top: 1;
    }

    #gmail-code-url {
        color: $accent;
        margin-bottom: 1;
    }

    #gmail-code-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #gmail-code-error {
        color: $error;
        height: 1;
    }
    """

    def __init__(self, auth_url: str = "") -> None:
        super().__init__()
        self._auth_url = auth_url

    def compose(self) -> ComposeResult:
        with Static(id="gmail-code-box"):
            yield Static("Paste Authorization Code", id="gmail-code-title")
            if self._auth_url:
                yield Static("Open this URL in any browser:", id="gmail-code-url-label")
                yield Static(self._auth_url, id="gmail-code-url")
            yield Static(
                "After authorizing, paste the code below:",
                id="gmail-code-hint",
            )
            yield Input(placeholder="Paste code here", id="gmail-code-input")
            yield Static("", id="gmail-code-error")

    def on_mount(self) -> None:
        self.query_one("#gmail-code-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        code = event.value.strip()
        if not code:
            self.query_one("#gmail-code-error", Static).update("Please paste the code.")
            return
        GMAIL_AUTH_CODE_FILE.write_text(code + "\n")
        self.dismiss()


class GmailSetupScreen(Screen[None]):
    """Run the Gmail OAuth flow for automated MFA retrieval."""

    BINDINGS = [
        Binding("b", "back", "Back", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    GmailSetupScreen {
        layout: vertical;
    }

    #gmail-log { height: 1fr; }

    #gmail-status-bar {
        height: 3;
        padding: 0 1;
        border-top: solid $primary-darken-3;
    }

    #gmail-status {
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._done = False
        self._code_shown = False
        self._auth_url = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="gmail-log", highlight=True, markup=True, wrap=True)
        with Vertical(id="gmail-status-bar"):
            yield Static("Starting…", id="gmail-status")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#gmail-log", RichLog)
        if not GMAIL_CREDS_FILE.exists():
            log.write(
                "[bold]google_credentials.json[/bold] not found.\n\n"
                "To create it:\n"
                "  1. Go to [link]https://console.cloud.google.com[/link]\n"
                "  2. Create a project\n"
                "  3. Enable the Gmail API\n"
                "  4. Credentials → Create → OAuth 2.0 Client ID → Desktop app\n"
                "  5. Download JSON → save as [bold]google_credentials.json[/bold]\n"
                "     in the project root directory\n\n"
                "Then come back here to complete authorization."
            )
            self.query_one("#gmail-status", Static).update(
                "google_credentials.json required  —  press  b  to go back"
            )
            self._done = True
            self._enable_back()
            return

        if GMAIL_TOKEN_FILE.exists():
            log.write(
                "[green]✓[/green]  Gmail MFA is already authorized.\n\n"
                "Token file found:  [dim].google_token.json[/dim]\n\n"
                "To re-authorize (e.g. to use a different account), delete\n"
                "[dim].google_token.json[/dim] and run this setup again."
            )
            self.query_one("#gmail-status", Static).update(
                "Already authorized ✓  —  press  b  to go back"
            )
            self._done = True
            self._enable_back()
            return

        self.run_worker(lambda: self._do_auth(), thread=True, name="gmail-auth")

    def _do_auth(self) -> None:
        import subprocess

        log = self.query_one("#gmail-log", RichLog)
        self.app.call_from_thread(
            self.query_one("#gmail-status", Static).update, "Running authorization flow…"
        )

        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "scripts" / "setup_gmail_auth.py")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(ROOT),
            )
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                self.app.call_from_thread(log.write, line)

                # Auth URL detected — capture it
                if line.startswith("https://") and not self._code_shown:
                    self._auth_url = line.strip()
                    self.app.call_from_thread(
                        self.query_one("#gmail-status", Static).update,
                        "Open the URL in any browser, then paste the code into the dialog",
                    )

                # Waiting for code file — show modal with URL embedded
                if "Waiting up to" in line and not self._code_shown:
                    self._code_shown = True
                    self.app.call_from_thread(
                        self.query_one("#gmail-status", Static).update,
                        "Waiting for authorization code…",
                    )
                    self.app.call_from_thread(self.app.push_screen, _GmailCodeModal(self._auth_url))

            proc.wait()
            self._done = True
            if proc.returncode == 0:
                self.app.call_from_thread(
                    self.query_one("#gmail-status", Static).update,
                    "Gmail MFA authorized ✓  —  press  b  to go back",
                )
                self.app.call_from_thread(
                    log.write, "\n[green]✓ Gmail MFA automation is now active.[/green]"
                )
            else:
                self.app.call_from_thread(
                    self.query_one("#gmail-status", Static).update,
                    "Authorization did not complete — press  b  to try again",
                )
        except Exception as exc:
            self.app.call_from_thread(log.write, f"\n[red]Error: {exc}[/red]")
            self._done = True
            self.app.call_from_thread(
                self.query_one("#gmail-status", Static).update,
                "Error — press  b  to go back",
            )

        self.app.call_from_thread(self._enable_back)

    def _enable_back(self) -> None:
        try:
            self.BINDINGS = [
                Binding("b", "back", "Back", show=True),
                Binding("q", "quit", "Quit", show=True),
            ]
            self.refresh_bindings()
        except Exception:
            pass

    def action_back(self) -> None:
        if self._done:
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
