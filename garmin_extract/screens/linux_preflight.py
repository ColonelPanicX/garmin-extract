"""Linux preflight — gates pulls on Xvfb, Garmin creds, and Gmail MFA.

On truly-headless Linux (no $DISPLAY) the pull cannot proceed without all
three: Xvfb installed, Garmin credentials saved, and Gmail MFA configured
(manual login is impossible with no screen to interact with). On desktop
Linux the user may still choose manual login as on Windows/macOS.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

ROOT = Path(__file__).parent.parent.parent
GMAIL_CREDS_FILE = ROOT / "google_credentials.json"
GMAIL_TOKEN_FILE = ROOT / ".google_token.json"


def _gmail_configured() -> bool:
    return GMAIL_CREDS_FILE.exists() and GMAIL_TOKEN_FILE.exists()


class LinuxPreflightScreen(ModalScreen[str | None]):
    """Modal that gates a pull on Linux prerequisites.

    Dismissed values:
      - "manual"  — user chose manual login (DISPLAY available only)
      - "auto"    — all required prerequisites satisfied, proceed with auto login
      - None      — user cancelled
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    CSS = """
    LinuxPreflightScreen {
        align: center middle;
    }

    #preflight-box {
        width: 72;
        height: auto;
        max-height: 90%;
        border: round $accent;
        padding: 1 2;
    }

    #preflight-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #preflight-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    .gate-row {
        height: auto;
        margin-bottom: 1;
    }

    .gate-status {
        height: auto;
    }

    .gate-actions {
        height: auto;
        margin-top: 0;
    }

    #creds-form {
        height: auto;
        display: none;
        padding: 1 0;
    }

    #creds-form.visible {
        display: block;
    }

    #creds-error {
        color: $error;
        height: auto;
    }

    #preflight-buttons {
        height: auto;
        margin-top: 1;
    }

    Button {
        margin-right: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._creds_visible = False

    # ── state helpers ────────────────────────────────────────────────────

    def _is_headless(self) -> bool:
        from garmin_extract._xvfb import is_truly_headless

        return is_truly_headless()

    def _xvfb_needed(self) -> bool:
        return self._is_headless()

    def _xvfb_ok(self) -> bool:
        from garmin_extract._xvfb import is_installed

        return is_installed()

    def _creds_ok(self) -> bool:
        from garmin_extract._credentials import load_credentials

        email, password = load_credentials()
        return bool(email and password)

    def _mfa_ok(self) -> bool:
        return _gmail_configured()

    def _can_proceed_auto(self) -> bool:
        """All required gates must be green."""
        if self._xvfb_needed() and not self._xvfb_ok():
            return False
        if self._is_headless():
            return self._creds_ok() and self._mfa_ok()
        return self._creds_ok()

    # ── compose ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="preflight-box"):
            yield Static("Linux Preflight", id="preflight-title")
            yield Static("", id="preflight-hint")

            # Xvfb row (only meaningful when headless)
            with Vertical(classes="gate-row", id="xvfb-row"):
                yield Static("", id="xvfb-status", classes="gate-status")
                with Horizontal(classes="gate-actions", id="xvfb-actions"):
                    yield Button("Install Xvfb", id="install-xvfb", variant="primary")

            # Credentials row
            with Vertical(classes="gate-row", id="creds-row"):
                yield Static("", id="creds-status", classes="gate-status")
                with Horizontal(classes="gate-actions", id="creds-actions"):
                    yield Button("Configure auto login", id="configure-creds")
                with Vertical(id="creds-form"):
                    yield Input(placeholder="Garmin email", id="creds-email")
                    yield Input(
                        placeholder="Garmin password",
                        id="creds-password",
                        password=True,
                    )
                    yield Static("", id="creds-error")
                    with Horizontal():
                        yield Button("Save", id="save-creds", variant="primary")
                        yield Button("Cancel", id="cancel-creds")

            # Gmail MFA row
            with Vertical(classes="gate-row", id="mfa-row"):
                yield Static("", id="mfa-status", classes="gate-status")
                with Horizontal(classes="gate-actions", id="mfa-actions"):
                    yield Button("Configure Gmail MFA", id="configure-mfa")

            # Action row
            with Horizontal(id="preflight-buttons"):
                yield Button("Log in manually", id="manual", variant="success")
                yield Button("Continue", id="continue", variant="primary")
                yield Button("Cancel", id="cancel")

    # ── lifecycle ────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._refresh()

    def on_screen_resume(self) -> None:
        # Re-run when returning from the pushed GmailSetupScreen
        self._refresh()

    def _refresh(self) -> None:
        headless = self._is_headless()

        hint = (
            "Headless Linux — automation requires Xvfb, saved Garmin credentials, "
            "and Gmail MFA. Manual login is unavailable without a display."
            if headless
            else "Choose how to log in. Auto login saves your credentials to the OS "
            "keyring for future unattended runs."
        )
        self.query_one("#preflight-hint", Static).update(hint)

        # ── Xvfb
        xvfb_row = self.query_one("#xvfb-row", Vertical)
        if self._xvfb_needed():
            xvfb_row.display = True
            ok = self._xvfb_ok()
            self.query_one("#xvfb-status", Static).update(
                "[green]✓[/]  Xvfb installed"
                if ok
                else "[red]✗[/]  Xvfb not installed — required for headless Chrome"
            )
            self.query_one("#install-xvfb", Button).display = not ok
        else:
            xvfb_row.display = False

        # ── Credentials
        creds_ok = self._creds_ok()
        creds_required = headless
        creds_label = (
            "[green]✓[/]  Garmin credentials saved"
            if creds_ok
            else (
                "[red]✗[/]  Garmin credentials not configured — required for headless"
                if creds_required
                else "[yellow]○[/]  Garmin credentials not configured (optional)"
            )
        )
        self.query_one("#creds-status", Static).update(creds_label)
        self.query_one("#configure-creds", Button).display = not self._creds_visible

        # ── Gmail MFA
        mfa_row = self.query_one("#mfa-row", Vertical)
        if headless:
            mfa_row.display = True
            mfa_ok = self._mfa_ok()
            self.query_one("#mfa-status", Static).update(
                "[green]✓[/]  Gmail MFA configured"
                if mfa_ok
                else "[red]✗[/]  Gmail MFA not configured — required for headless"
            )
        else:
            mfa_row.display = False

        # ── Buttons
        self.query_one("#manual", Button).display = not headless
        self.query_one("#continue", Button).disabled = not self._can_proceed_auto()

    # ── events ───────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "cancel":
            self.dismiss(None)
        elif bid == "manual":
            self.dismiss("manual")
        elif bid == "continue":
            if self._can_proceed_auto():
                self.dismiss("auto")
        elif bid == "install-xvfb":
            self._install_xvfb()
        elif bid == "configure-creds":
            self._show_creds_form()
        elif bid == "cancel-creds":
            self._hide_creds_form()
        elif bid == "save-creds":
            self._save_creds()
        elif bid == "configure-mfa":
            self._open_mfa_setup()

    def _install_xvfb(self) -> None:
        btn = self.query_one("#install-xvfb", Button)
        btn.disabled = True
        btn.label = "Installing…"
        self.run_worker(self._xvfb_worker, thread=True, exclusive=True)

    def _xvfb_worker(self) -> None:
        from garmin_extract._xvfb import install

        ok, detail = install()
        self.app.call_from_thread(self._xvfb_done, ok, detail)

    def _xvfb_done(self, ok: bool, detail: str) -> None:
        btn = self.query_one("#install-xvfb", Button)
        btn.disabled = False
        btn.label = "Install Xvfb"
        if not ok:
            self.notify(detail, severity="error", title="Xvfb install failed")
        self._refresh()

    def _show_creds_form(self) -> None:
        self._creds_visible = True
        self.query_one("#creds-form").add_class("visible")
        self.query_one("#configure-creds", Button).display = False
        from garmin_extract._credentials import load_credentials

        email, _ = load_credentials()
        if email:
            self.query_one("#creds-email", Input).value = email
        self.query_one("#creds-email", Input).focus()

    def _hide_creds_form(self) -> None:
        self._creds_visible = False
        self.query_one("#creds-form").remove_class("visible")
        self.query_one("#creds-error", Static).update("")
        self._refresh()

    def _save_creds(self) -> None:
        email = self.query_one("#creds-email", Input).value.strip()
        password = self.query_one("#creds-password", Input).value.strip()
        err = self.query_one("#creds-error", Static)
        if not email or not password:
            err.update("Email and password are required.")
            return
        from garmin_extract._credentials import detect_keyring, save_to_env, save_to_keyring

        keyring_ok, _ = detect_keyring()
        if keyring_ok:
            ok, detail = save_to_keyring(email, password)
            if not ok:
                err.update(f"Keyring save failed: {detail}")
                return
        else:
            save_to_env(email, password)
        err.update("")
        self._hide_creds_form()

    def _open_mfa_setup(self) -> None:
        from garmin_extract.screens.setup import GmailSetupScreen

        self.app.push_screen(GmailSetupScreen())

    def action_cancel(self) -> None:
        self.dismiss(None)
