"""Initial Setup page — prerequisite checks, credentials, Gmail OAuth."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).parent.parent.parent.parent
GMAIL_CREDS_FILE = ROOT / "google_credentials.json"
GMAIL_TOKEN_FILE = ROOT / ".google_token.json"
GMAIL_AUTH_CODE_FILE = ROOT / ".gmail_auth_code"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_python() -> tuple[bool, str]:
    v = sys.version_info
    return v >= (3, 12), f"Python {v.major}.{v.minor}.{v.micro}"


def _check_chrome() -> tuple[bool, str]:
    from garmin_extract.menu import _find_chrome

    found, version = _find_chrome()
    return found, version or "Not found"


def _check_packages() -> tuple[bool, str]:
    from garmin_extract.menu import _missing_packages

    missing = _missing_packages()
    if not missing:
        return True, "All installed"
    return False, f"Missing: {', '.join(missing)}"


def _check_credentials() -> tuple[bool, str]:
    from garmin_extract._credentials import check_credentials

    return check_credentials()


def _check_gmail() -> tuple[bool, str]:
    if not GMAIL_CREDS_FILE.exists():
        return False, "google_credentials.json missing"
    if not GMAIL_TOKEN_FILE.exists():
        return False, "Credentials found — not yet authorized"
    return True, "Authorized"


# ── Signals bridge (thread → UI) ────────────────────────────────────────────


class _StatusSignals(QObject):
    """Signals emitted from background threads to update the UI."""

    prereq_done = Signal(bool, str)  # (all_ok, summary)
    creds_done = Signal(bool, str)  # (ok, detail)
    gmail_done = Signal(bool, str)  # (ok, detail)
    all_done = Signal()


# ── Status card widget ───────────────────────────────────────────────────────


class _StatusCard(QFrame):
    """A clickable card showing a section name, status icon, and detail text."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("status-card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QFrame#status-card {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 16px;
            }
            QFrame#status-card:hover {
                border-color: #89b4fa;
            }
            """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        # Left: icon + text
        left = QVBoxLayout()
        left.setSpacing(4)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 16px; font-weight: bold; background: transparent;")
        left.addWidget(self._title)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet("font-size: 13px; color: #6c7086; background: transparent;")
        left.addWidget(self._subtitle)

        self._detail = QLabel("Checking…")
        self._detail.setStyleSheet("font-size: 13px; color: #6c7086; background: transparent;")
        left.addWidget(self._detail)

        layout.addLayout(left, stretch=1)

        # Right: status icon
        self._icon = QLabel("○")
        self._icon.setStyleSheet("font-size: 22px; color: #6c7086; background: transparent;")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setFixedWidth(40)
        layout.addWidget(self._icon)

        self._callback: object = None

    def set_status(self, ok: bool, detail: str) -> None:
        if ok:
            self._icon.setText("✓")
            self._icon.setStyleSheet("font-size: 22px; color: #a6e3a1; background: transparent;")
        else:
            self._icon.setText("✗")
            self._icon.setStyleSheet("font-size: 22px; color: #f38ba8; background: transparent;")
        # Strip Rich markup for GUI display
        import re

        clean = re.sub(r"\[/?[^\]]*\]", "", detail)
        self._detail.setText(clean)

    def on_click(self, callback: object) -> None:
        self._callback = callback

    def mousePressEvent(self, event: object) -> None:  # noqa: N802
        if self._callback and callable(self._callback):
            self._callback()


# ── Prerequisites dialog ─────────────────────────────────────────────────────


class PrereqDialog(QDialog):
    """Modal dialog that runs prerequisite checks with live output."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Prerequisites")
        self.setMinimumSize(600, 400)
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background-color: #1e1e2e; color: #cdd6f4; font-family: monospace;"
            " font-size: 13px; border: 1px solid #45475a; border-radius: 4px;"
        )
        layout.addWidget(self._log)

        self._progress = QProgressBar()
        self._progress.setMaximum(3)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._status = QLabel("Running checks…")
        self._status.setStyleSheet("color: #6c7086;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.setEnabled(False)
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._signals = _CheckSignals()
        self._signals.log_line.connect(self._append_log)
        self._signals.progress.connect(self._progress.setValue)
        self._signals.finished.connect(self._on_finished)

        Thread(target=self._run_checks, daemon=True).start()

    def _run_checks(self) -> None:
        checks = [
            ("Python 3.12+", _check_python),
            ("Google Chrome", _check_chrome),
            ("Python packages", _check_packages),
        ]
        failed: list[str] = []
        for i, (name, fn) in enumerate(checks):
            ok, detail = fn()
            icon = "✓" if ok else "✗"
            self._signals.log_line.emit(f"  {icon}  {name}: {detail}")
            if not ok:
                failed.append(name)
            self._signals.progress.emit(i + 1)

        if failed:
            self._signals.finished.emit(f"Issues found: {', '.join(failed)}")
        else:
            self._signals.finished.emit("All checks passed ✓")

    def _append_log(self, text: str) -> None:
        self._log.append(text)

    def _on_finished(self, summary: str) -> None:
        self._status.setText(summary)
        self._close_btn.setEnabled(True)
        self._progress.hide()


class _CheckSignals(QObject):
    log_line = Signal(str)
    progress = Signal(int)
    finished = Signal(str)


# ── Credentials dialog ───────────────────────────────────────────────────────


class CredentialsDialog(QDialog):
    """Modal dialog for entering Garmin Connect credentials."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Garmin Connect Credentials")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Keyring status
        self._mode_label = QLabel("Detecting keyring…")
        self._mode_label.setStyleSheet("color: #6c7086; font-size: 13px;")
        layout.addWidget(self._mode_label)

        # Warning panel (hidden by default)
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet(
            "background-color: #45475a; color: #f38ba8; border: 1px solid #f38ba8;"
            " border-radius: 6px; padding: 12px; font-size: 13px;"
        )
        self._warning.hide()
        layout.addWidget(self._warning)

        # Email
        layout.addWidget(QLabel("Email"))
        self._email = QLineEdit()
        self._email.setPlaceholderText("you@example.com")
        layout.addWidget(self._email)

        # Password
        layout.addWidget(QLabel("Password"))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Garmin Connect password")
        layout.addWidget(self._password)

        # Feedback
        self._error = QLabel()
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.hide()
        layout.addWidget(self._error)

        self._success = QLabel()
        self._success.setStyleSheet("color: #a6e3a1;")
        self._success.hide()
        layout.addWidget(self._success)

        # Buttons
        btn_layout = QHBoxLayout()
        self._clear_btn = QPushButton("Clear Credentials")
        self._clear_btn.setStyleSheet("color: #f38ba8;")
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self._clear)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._save)
        btn_layout.addWidget(self._save_btn)
        layout.addLayout(btn_layout)

        self._keyring_available: bool | None = None
        Thread(target=self._detect_keyring, daemon=True).start()
        self._load_existing()

    def _load_existing(self) -> None:
        try:
            from garmin_extract._credentials import load_credentials

            email, password = load_credentials()
            if email:
                self._email.setText(email)
                self._password.setFocus()
            else:
                self._email.setFocus()
            self._clear_btn.setEnabled(bool(email or password))
        except Exception:
            self._email.setFocus()

    def _detect_keyring(self) -> None:
        from garmin_extract._credentials import detect_keyring

        ok, detail = detect_keyring()
        # Use QMetaObject.invokeMethod for thread safety — but simpler
        # to use a signal. For brevity, just set and update in main thread.
        self._keyring_available = ok
        self._keyring_detail = detail

    def showEvent(self, event: object) -> None:  # noqa: N802
        super().showEvent(event)
        # Poll for keyring detection result (runs nearly instantly)
        from PySide6.QtCore import QTimer

        def _apply() -> None:
            if self._keyring_available is None:
                QTimer.singleShot(50, _apply)
                return
            if self._keyring_available:
                self._mode_label.setText(f"● Keyring: {self._keyring_detail}")
                self._mode_label.setStyleSheet("color: #a6e3a1; font-size: 13px;")
            else:
                self._mode_label.setText(
                    "⚠ No secure keyring — credentials will be saved to .env (plaintext)"
                )
                self._mode_label.setStyleSheet("color: #f9e2af; font-size: 13px;")
                self._warning.setText(
                    "⚠ PLAINTEXT WARNING\n\n"
                    "Saving will write your password to a plain-text file on disk.\n"
                    "Anyone with read access to your filesystem can see it."
                )
                self._warning.show()

        QTimer.singleShot(50, _apply)

    def _clear(self) -> None:
        from garmin_extract._credentials import clear_credentials

        self._error.hide()
        self._success.hide()
        ok, detail = clear_credentials()
        if ok:
            self._email.clear()
            self._password.clear()
            self._clear_btn.setEnabled(False)
            self._success.setText("Credentials cleared.")
            self._success.show()
        else:
            self._error.setText(f"Clear failed: {detail}")
            self._error.show()

    def _save(self) -> None:
        from garmin_extract._credentials import save_to_env, save_to_keyring

        email = self._email.text().strip()
        password = self._password.text().strip()

        self._error.hide()
        self._success.hide()

        if not email:
            self._error.setText("Email is required.")
            self._error.show()
            self._email.setFocus()
            return
        if not password:
            self._error.setText("Password is required.")
            self._error.show()
            self._password.setFocus()
            return

        if self._keyring_available:
            ok, detail = save_to_keyring(email, password)
            if ok:
                self._success.setText(f"✓ Saved to keyring — {email}")
                self._success.show()
            else:
                self._error.setText(f"Keyring save failed: {detail}")
                self._error.show()
                return
        else:
            save_to_env(email, password)
            self._success.setText(f"✓ Saved to .env — {email}")
            self._success.show()

        self._save_btn.setEnabled(False)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, self.accept)


# ── Gmail OAuth dialog ───────────────────────────────────────────────────────


class GmailOAuthDialog(QDialog):
    """Modal dialog for Gmail OAuth authorization flow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gmail OAuth Setup")
        self.setMinimumSize(650, 450)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background-color: #1e1e2e; color: #cdd6f4; font-family: monospace;"
            " font-size: 13px; border: 1px solid #45475a; border-radius: 4px;"
        )
        layout.addWidget(self._log)

        # Code input area (hidden until needed)
        self._code_frame = QFrame()
        self._code_frame.hide()
        code_layout = QVBoxLayout(self._code_frame)
        code_layout.setContentsMargins(0, 8, 0, 0)
        code_layout.addWidget(QLabel("Paste the authorization code below:"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("Paste code here")
        self._code_input.returnPressed.connect(self._submit_code)
        code_layout.addWidget(self._code_input)
        layout.addWidget(self._code_frame)

        self._status = QLabel()
        self._status.setStyleSheet("color: #6c7086;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._auth_url = ""
        self._signals = _GmailSignals()
        self._signals.log_line.connect(self._append_log)
        self._signals.show_code_input.connect(self._show_code_input)
        self._signals.finished.connect(self._on_finished)

        self._start_flow()

    def _start_flow(self) -> None:
        if not GMAIL_CREDS_FILE.exists():
            self._log.append(
                "google_credentials.json not found.\n\n"
                "To create it:\n"
                "  1. Go to https://console.cloud.google.com\n"
                "  2. Create a project\n"
                "  3. Enable the Gmail API\n"
                "  4. Credentials → Create → OAuth 2.0 Client ID → Desktop app\n"
                "  5. Download JSON → save as google_credentials.json\n"
                "     in the project root directory\n\n"
                "Then come back here to complete authorization."
            )
            self._status.setText("google_credentials.json required")
            return

        if GMAIL_TOKEN_FILE.exists():
            self._log.append(
                "✓  Gmail MFA is already authorized.\n\n"
                "Token file found: .google_token.json\n\n"
                "To re-authorize, delete .google_token.json and run this again."
            )
            self._status.setText("Already authorized ✓")
            return

        self._status.setText("Running authorization flow…")
        Thread(target=self._do_auth, daemon=True).start()

    def _do_auth(self) -> None:
        import subprocess

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
            code_shown = False
            for raw_line in iter(proc.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                self._signals.log_line.emit(line)

                if line.startswith("https://") and not code_shown:
                    self._auth_url = line.strip()

                if "Waiting up to" in line and not code_shown:
                    code_shown = True
                    self._signals.show_code_input.emit(self._auth_url)

            proc.wait()
            if proc.returncode == 0:
                self._signals.finished.emit("Gmail MFA authorized ✓")
            else:
                self._signals.finished.emit("Authorization did not complete")
        except Exception as exc:
            self._signals.finished.emit(f"Error: {exc}")

    def _append_log(self, text: str) -> None:
        self._log.append(text)

    def _show_code_input(self, auth_url: str) -> None:
        self._status.setText("Open the URL above in any browser, then paste the code below")
        self._code_frame.show()
        self._code_input.setFocus()

    def _submit_code(self) -> None:
        code = self._code_input.text().strip()
        if not code:
            return
        GMAIL_AUTH_CODE_FILE.write_text(code + "\n")
        self._code_frame.hide()
        self._status.setText("Code submitted — waiting for confirmation…")

    def _on_finished(self, summary: str) -> None:
        self._status.setText(summary)
        self._code_frame.hide()


class _GmailSignals(QObject):
    log_line = Signal(str)
    show_code_input = Signal(str)
    finished = Signal(str)


# ── Setup page (main content widget) ────────────────────────────────────────


class SetupPage(QWidget):
    """The Initial Setup page shown in the main window's stacked widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        heading = QLabel("Initial Setup")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        sub = QLabel("Configure credentials and prerequisites")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        layout.addSpacing(16)

        # ── Prerequisite card ─────────────────────────
        self._prereq_card = _StatusCard("Prerequisites", "Python, Chrome, packages")
        self._prereq_card.on_click(self._open_prereqs)
        layout.addWidget(self._prereq_card)

        layout.addSpacing(4)

        # ── Credentials card ──────────────────────────
        self._creds_card = _StatusCard("Garmin Credentials", "Email and password")
        self._creds_card.on_click(self._open_credentials)
        layout.addWidget(self._creds_card)

        layout.addSpacing(4)

        # ── Gmail OAuth card ──────────────────────────
        self._gmail_card = _StatusCard("Gmail OAuth", "Automatic MFA + Drive/Sheets (optional)")
        self._gmail_card.on_click(self._open_gmail)
        layout.addWidget(self._gmail_card)

        layout.addStretch()

        # Run initial status checks
        self._signals = _StatusSignals()
        self._signals.prereq_done.connect(self._prereq_card.set_status)
        self._signals.creds_done.connect(self._creds_card.set_status)
        self._signals.gmail_done.connect(self._gmail_card.set_status)
        self.refresh_status()

    def refresh_status(self) -> None:
        Thread(target=self._check_all, daemon=True).start()

    def _check_all(self) -> None:
        py_ok, _ = _check_python()
        chrome_ok, _ = _check_chrome()
        pkg_ok, _ = _check_packages()
        all_ok = py_ok and chrome_ok and pkg_ok

        parts = []
        for ok, name in [(py_ok, "Python"), (chrome_ok, "Chrome"), (pkg_ok, "Packages")]:
            parts.append(f"{'✓' if ok else '✗'} {name}")
        self._signals.prereq_done.emit(all_ok, "  ".join(parts))

        creds_ok, creds_str = _check_credentials()
        self._signals.creds_done.emit(creds_ok, creds_str)

        gmail_ok, gmail_str = _check_gmail()
        self._signals.gmail_done.emit(gmail_ok, gmail_str)

    def _open_prereqs(self) -> None:
        dlg = PrereqDialog(self)
        dlg.exec()
        self.refresh_status()

    def _open_credentials(self) -> None:
        dlg = CredentialsDialog(self)
        dlg.exec()
        self.refresh_status()

    def _open_gmail(self) -> None:
        dlg = GmailOAuthDialog(self)
        dlg.exec()
        self.refresh_status()
