"""Automation page — Gmail MFA status, scheduled pulls, Drive/Sheets export."""

from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QObject, Qt, QTime, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

_WINDOWS = platform.system() == "Windows"

ROOT = Path(__file__).parent.parent.parent.parent
GMAIL_CREDS_FILE = ROOT / "google_credentials.json"
GMAIL_TOKEN_FILE = ROOT / ".google_token.json"
DRIVE_CONFIG_FILE = ROOT / ".drive_config.json"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_gmail_automation() -> tuple[str, str]:
    """Return (status, detail) where status is 'ok' | 'partial' | 'unconfigured'."""
    has_creds = GMAIL_CREDS_FILE.exists()
    has_token = GMAIL_TOKEN_FILE.exists()

    if not has_creds and not has_token:
        return "unconfigured", "Not set up"
    if not has_creds:
        return "partial", "google_credentials.json missing"
    if not has_token:
        return "partial", "Not yet authorized"

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        tok = json.loads(GMAIL_TOKEN_FILE.read_text())
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
        return "partial", f"Token validation failed: {exc}"


def _check_drive_auth() -> tuple[str, str]:
    """Return (status, detail) for Drive/Sheets auth."""
    try:
        from garmin_extract._google_drive import check_auth

        return check_auth()
    except Exception as exc:
        return "error", str(exc)


def _load_drive_config() -> dict:
    try:
        return json.loads(DRIVE_CONFIG_FILE.read_text()) if DRIVE_CONFIG_FILE.exists() else {}
    except Exception:
        return {}


# ── Signals ──────────────────────────────────────────────────────────────────


class _AutoSignals(QObject):
    gmail_done = Signal(str, str, str)  # status, detail, icon_color
    drive_auth_done = Signal(str, str)  # auth_text, last_export_text
    drive_op_done = Signal(str)  # result text
    creds_done = Signal(bool, str)  # ok, detail
    sched_done = Signal(bool, str)  # installed, detail


# ── Status card (reused from setup) ─────────────────────────────────────────


class _SectionCard(QFrame):
    """A card for displaying automation section status."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("section-card")
        self.setStyleSheet("""
            QFrame#section-card {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
            """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(self._title)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet("font-size: 13px; color: #6c7086; background: transparent;")
        layout.addWidget(self._subtitle)

        self._status = QLabel("Checking...")
        self._status.setStyleSheet("font-size: 13px; color: #6c7086; background: transparent;")
        layout.addWidget(self._status)

        self._actions_layout = QHBoxLayout()
        self._actions_layout.setContentsMargins(0, 8, 0, 0)
        layout.addLayout(self._actions_layout)

    def set_status(self, text: str, color: str = "#6c7086") -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"font-size: 13px; color: {color}; background: transparent;")

    def add_action_button(self, label: str, callback: object) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(32)
        btn.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                font-size: 13px;
                background-color: #45475a;
                border: 1px solid #585b70;
                border-radius: 4px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #585b70;
                border-color: #89b4fa;
            }
            QPushButton:pressed {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
            """)
        btn.clicked.connect(callback)
        self._actions_layout.addWidget(btn)
        return btn


# ── Gmail MFA setup dialog ───────────────────────────────────────────────────


_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_GOOGLE_CLOUD_CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"


class _CredentialsHelpDialog(QDialog):
    """Step-by-step guide to obtain a google_credentials.json file from the
    Google Cloud Console.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Where do I get google_credentials.json?")
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "You need an OAuth client from Google Cloud Console. It's a one-time "
            "setup that takes about 5 minutes."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(intro)

        steps_html = (
            "<ol style='margin-left: -20px;'>"
            f"<li>Open the <a href='{_GOOGLE_CLOUD_CREDENTIALS_URL}' style='color: #89b4fa;'>"
            "Google Cloud Console credentials page</a> and sign in.</li>"
            "<li>Create or select a project (any name works — it's just for you).</li>"
            "<li>Enable the <b>Gmail API</b> for the project. "
            "If you also want Drive / Sheets export, enable those APIs too.</li>"
            "<li>Open the <b>OAuth consent screen</b> — choose <b>External</b>, "
            "fill in the required fields, and add yourself as a <b>test user</b>.</li>"
            "<li>Back on the Credentials page, click <b>Create Credentials → "
            "OAuth client ID</b>. Application type: <b>Desktop app</b>.</li>"
            "<li>Click <b>Download JSON</b> on the new client. That's your "
            "<code>google_credentials.json</code>.</li>"
            "<li>Return here and click <b>Browse…</b> to select the file.</li>"
            "</ol>"
        )
        steps = QLabel(steps_html)
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.TextFormat.RichText)
        steps.setOpenExternalLinks(True)
        steps.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        layout.addWidget(steps)

        note = QLabel(
            "This data stays local — the token file is written to the app directory "
            "and never leaves your machine."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c7086; font-size: 12px;")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        open_btn = QPushButton("Open Google Cloud Console")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(_GOOGLE_CLOUD_CREDENTIALS_URL))
        btn_row.addWidget(open_btn)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class _GmailSetupSignals(QObject):
    token_done = Signal(bool, str)  # ok, detail


class _GmailSetupDialog(QDialog):
    """Walks the user through Gmail OAuth setup: pick credentials, open
    the authorization URL, paste the resulting code, exchange for a token.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gmail MFA Setup")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._auth_url = ""
        self._oauth = None
        self._signals = _GmailSetupSignals()
        self._signals.token_done.connect(self._on_token_done)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Gmail MFA automation uses OAuth to read your Garmin MFA emails. "
            "You'll need a Google Cloud OAuth client (Desktop app) — download the "
            "JSON credentials file, then follow the steps below."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6c7086;")
        layout.addWidget(intro)

        # ── Step 1: credentials file ──
        step1_row = QHBoxLayout()
        step1 = QLabel("Step 1 — Google credentials file")
        step1.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-top: 8px;")
        step1_row.addWidget(step1)
        step1_row.addStretch()
        help_btn = QPushButton("How do I get this?")
        help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        help_btn.setFlat(True)
        help_btn.setStyleSheet(
            "QPushButton { color: #89b4fa; border: none; text-decoration: underline; }"
            "QPushButton:hover { color: #b4befe; }"
        )
        help_btn.clicked.connect(self._open_credentials_help)
        step1_row.addWidget(help_btn)
        layout.addLayout(step1_row)

        creds_row = QHBoxLayout()
        self._creds_status = QLabel()
        self._creds_status.setWordWrap(True)
        creds_row.addWidget(self._creds_status, stretch=1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._browse_for_creds)
        creds_row.addWidget(self._browse_btn)
        layout.addLayout(creds_row)

        # ── Step 2: authorization URL ──
        step2 = QLabel("Step 2 — Authorize in browser")
        step2.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-top: 8px;")
        layout.addWidget(step2)

        self._auth_btn = QPushButton("Open authorization URL")
        self._auth_btn.clicked.connect(self._open_auth_url)
        layout.addWidget(self._auth_btn)

        # ── Step 3: paste code ──
        step3 = QLabel("Step 3 — Paste the authorization code")
        step3.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-top: 8px;")
        layout.addWidget(step3)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("4/0A…")
        self._code_input.returnPressed.connect(self._complete_setup)
        layout.addWidget(self._code_input)

        # ── Error/status feedback ──
        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._complete_btn = QPushButton("Complete setup")
        self._complete_btn.setDefault(True)
        self._complete_btn.clicked.connect(self._complete_setup)
        btn_row.addWidget(self._complete_btn)
        layout.addLayout(btn_row)

        self._refresh_creds_state()

    # ── State ──
    def _refresh_creds_state(self) -> None:
        if GMAIL_CREDS_FILE.exists():
            self._creds_status.setText(f"✓ {GMAIL_CREDS_FILE.name} in place")
            self._creds_status.setStyleSheet("color: #a6e3a1;")
            self._auth_btn.setEnabled(True)
            self._code_input.setEnabled(True)
            self._complete_btn.setEnabled(True)
        else:
            self._creds_status.setText("No credentials file yet — click Browse to pick one")
            self._creds_status.setStyleSheet("color: #f9e2af;")
            self._auth_btn.setEnabled(False)
            self._code_input.setEnabled(False)
            self._complete_btn.setEnabled(False)

    def _show_error(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.show()

    def _show_info(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.setStyleSheet("color: #89b4fa;")
        self._error.show()

    def _open_credentials_help(self) -> None:
        _CredentialsHelpDialog(self).exec()

    # ── Step 1 ──
    def _browse_for_creds(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select google_credentials.json",
            str(Path.home()),
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        src = Path(path)
        try:
            data = json.loads(src.read_text())
            if "installed" not in data:
                self._show_error(
                    "That file doesn't look like a Google OAuth Desktop app credentials file "
                    '(missing the "installed" key). Create a Desktop app OAuth client in '
                    "Google Cloud Console and download its JSON."
                )
                return
        except Exception as exc:
            self._show_error(f"Couldn't read that file: {exc}")
            return
        try:
            shutil.copy2(src, GMAIL_CREDS_FILE)
        except Exception as exc:
            self._show_error(f"Couldn't copy credentials: {exc}")
            return
        self._error.hide()
        self._refresh_creds_state()

    # ── Step 2 ──
    def _open_auth_url(self) -> None:
        try:
            self._build_auth_url()
        except Exception as exc:
            self._show_error(f"Couldn't build authorization URL: {exc}")
            return
        QDesktopServices.openUrl(self._auth_url)
        self._show_info("Browser opened — complete consent, then paste the code below.")

    def _build_auth_url(self) -> None:
        from requests_oauthlib import OAuth2Session

        data = json.loads(GMAIL_CREDS_FILE.read_text())["installed"]
        self._client_id = data["client_id"]
        self._client_secret = data["client_secret"]
        self._auth_uri = data["auth_uri"]
        self._token_uri = data["token_uri"]
        self._oauth = OAuth2Session(
            self._client_id,
            scope=" ".join(_OAUTH_SCOPES),
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",
        )
        url, _state = self._oauth.authorization_url(
            self._auth_uri,
            access_type="offline",
            prompt="consent",
        )
        self._auth_url = url

    # ── Step 3 ──
    def _complete_setup(self) -> None:
        code = self._code_input.text().strip()
        if not code:
            self._show_error("Paste the authorization code from the browser first.")
            return
        if self._oauth is None:
            try:
                self._build_auth_url()
            except Exception as exc:
                self._show_error(f"Couldn't prepare OAuth session: {exc}")
                return
        self._complete_btn.setEnabled(False)
        self._show_info("Exchanging code for token…")
        Thread(target=self._exchange_token, args=(code,), daemon=True).start()

    def _exchange_token(self, code: str) -> None:
        import os

        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        try:
            token = self._oauth.fetch_token(
                self._token_uri,
                code=code,
                client_secret=self._client_secret,
                include_client_id=True,
            )
            token_data = {
                "token": token.get("access_token"),
                "refresh_token": token.get("refresh_token"),
                "token_uri": self._token_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scopes": _OAUTH_SCOPES,
                "expiry": None,
            }
            GMAIL_TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
            self._signals.token_done.emit(True, "")
        except Exception as exc:
            self._signals.token_done.emit(False, str(exc))

    def _on_token_done(self, ok: bool, detail: str) -> None:
        if ok:
            self.accept()
        else:
            self._complete_btn.setEnabled(True)
            self._show_error(f"Token exchange failed: {detail}")


# ── Drive folder picker ──────────────────────────────────────────────────────


class _DriveFolderPickerSignals(QObject):
    children_done = Signal(str, list, str)  # parent_id, folders, error


class _DriveFolderPickerDialog(QDialog):
    """Hierarchical Drive folder browser. Starts at My Drive, double-click
    a subfolder to drill in, click 'Select this folder' to pick the
    current location. Writes the chosen folder_id back to .drive_config.json.
    """

    ROOT_ID = "root"
    ROOT_NAME = "My Drive"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Drive folder")
        self.setMinimumWidth(540)
        self.setMinimumHeight(440)
        self.setModal(True)

        self.selected_folder_id: str = ""
        self.selected_folder_name: str = ""

        # Navigation state — root-to-current path of {id, name}
        self._path: list[dict[str, str]] = [{"id": self.ROOT_ID, "name": self.ROOT_NAME}]
        self._children_cache: dict[str, list[dict[str, str]]] = {}
        self._current_children: list[dict[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Browse to the folder you want to archive CSVs in, then click "
            "'Select this folder'. Double-click a subfolder to drill in."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6c7086;")
        layout.addWidget(intro)

        # ── Path row ──
        path_row = QHBoxLayout()
        self._up_btn = QPushButton("↑ Up")
        self._up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._up_btn.clicked.connect(self._go_up)
        path_row.addWidget(self._up_btn)
        self._path_label = QLabel()
        self._path_label.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        path_row.addWidget(self._path_label, stretch=1)
        layout.addLayout(path_row)

        # ── Filter ──
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter subfolders…")
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # ── Subfolder list ──
        from PySide6.QtWidgets import QListWidget

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._enter_selected)
        layout.addWidget(self._list, stretch=1)

        self._status = QLabel()
        self._status.setStyleSheet("color: #6c7086; font-size: 12px;")
        layout.addWidget(self._status)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._select_btn = QPushButton("Select this folder")
        self._select_btn.setDefault(True)
        self._select_btn.clicked.connect(self._select_current)
        btn_row.addWidget(self._select_btn)
        layout.addLayout(btn_row)

        self._signals = _DriveFolderPickerSignals()
        self._signals.children_done.connect(self._on_children_loaded)

        self._navigate_to_current()

    # ── Navigation ──

    def _current_parent_id(self) -> str:
        return self._path[-1]["id"]

    def _current_parent_name(self) -> str:
        return self._path[-1]["name"]

    def _navigate_to_current(self) -> None:
        """Reload the listing for self._path[-1]."""
        self._refresh_path_label()
        self._up_btn.setEnabled(len(self._path) > 1)
        self._filter.clear()

        parent_id = self._current_parent_id()
        if parent_id in self._children_cache:
            self._current_children = self._children_cache[parent_id]
            self._populate_list(self._current_children)
            self._status.setText(self._children_status_text(len(self._current_children)))
            self._status.setStyleSheet("color: #6c7086; font-size: 12px;")
            return

        self._list.clear()
        self._status.setText("Loading…")
        self._status.setStyleSheet("color: #6c7086; font-size: 12px;")
        Thread(target=self._load_children, args=(parent_id,), daemon=True).start()

    def _load_children(self, parent_id: str) -> None:
        try:
            from garmin_extract._google_drive import _load_credentials, list_folder_children

            creds = _load_credentials()
            folders = list_folder_children(creds, parent_id)
            self._signals.children_done.emit(parent_id, folders, "")
        except Exception as exc:
            self._signals.children_done.emit(parent_id, [], str(exc))

    def _on_children_loaded(self, parent_id: str, folders: list, error: str) -> None:
        # Cache regardless of current position, so backtracking is fast
        if not error:
            self._children_cache[parent_id] = folders
        # Only update UI if the user is still here
        if parent_id != self._current_parent_id():
            return
        if error:
            self._status.setText(f"Could not load folders: {error}")
            self._status.setStyleSheet("color: #f38ba8; font-size: 12px;")
            return
        self._current_children = folders
        self._status.setText(self._children_status_text(len(folders)))
        self._populate_list(folders)

    def _children_status_text(self, count: int) -> str:
        return f"{count} subfolder{'' if count == 1 else 's'} — double-click to open"

    def _refresh_path_label(self) -> None:
        self._path_label.setText(" › ".join(p["name"] for p in self._path))

    def _populate_list(self, folders: list) -> None:
        self._list.clear()
        for f in folders:
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(f["name"])
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        if not text:
            self._populate_list(self._current_children)
            return
        filtered = [f for f in self._current_children if text in f["name"].lower()]
        self._populate_list(filtered)

    def _enter_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        folder = item.data(Qt.ItemDataRole.UserRole)
        self._path.append({"id": folder["id"], "name": folder["name"]})
        self._navigate_to_current()

    def _go_up(self) -> None:
        if len(self._path) > 1:
            self._path.pop()
            self._navigate_to_current()

    def _select_current(self) -> None:
        self.selected_folder_id = self._current_parent_id()
        self.selected_folder_name = self._current_parent_name()
        self.accept()


# ── Scheduled Pulls dialog ───────────────────────────────────────────────────


class _ScheduledPullsDialog(QDialog):
    """Configure a daily Windows Task Scheduler entry that runs a pull at a
    user-chosen time, optionally followed by Drive/Sheets export.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scheduled Pulls")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "Schedule a daily pull via Windows Task Scheduler. The task runs "
            "garmin-extract with --pull at the time you choose."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6c7086;")
        layout.addWidget(intro)

        self._status = QLabel("Checking current schedule…")
        self._status.setStyleSheet("color: #cdd6f4; margin-top: 4px;")
        layout.addWidget(self._status)

        # ── Time picker ──
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Run daily at"))
        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        self._time_edit.setTime(QTime(6, 0))
        time_row.addWidget(self._time_edit)
        time_row.addStretch()
        layout.addLayout(time_row)

        # ── Export toggles ──
        drive_row = QHBoxLayout()
        self._push_drive = QCheckBox("Archive raw CSV files to Google Drive")
        self._push_drive.toggled.connect(self._on_drive_toggled)
        drive_row.addWidget(self._push_drive, stretch=1)
        drive_help = self._make_help_button(
            "Archive raw CSV files to Google Drive",
            (
                "Uploads garmin_daily.csv and garmin_activities.csv as actual "
                ".csv files into the Drive folder you choose. Each run overwrites "
                "the files in place.\n\n"
                "Best for: backups, version history, downloading the raw data, "
                "or feeding the CSVs into another tool.\n\n"
                "Clicking a CSV in Drive opens a read-only Sheets preview. To "
                "edit it as a Sheet, Drive makes a one-off copy — that copy will "
                "not update on future pulls."
            ),
        )
        drive_row.addWidget(drive_help)
        layout.addLayout(drive_row)

        # Drive folder row (only meaningful when Drive is checked)
        drive_folder_row = QHBoxLayout()
        drive_folder_row.setContentsMargins(22, 0, 0, 0)  # indent under checkbox
        self._drive_folder_label = QLabel("Folder: Garmin Extract")
        self._drive_folder_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        drive_folder_row.addWidget(self._drive_folder_label, stretch=1)
        self._drive_folder_btn = QPushButton("Change…")
        self._drive_folder_btn.setFlat(True)
        self._drive_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drive_folder_btn.setStyleSheet(
            "QPushButton { color: #89b4fa; border: none; text-decoration: underline; }"
            "QPushButton:hover { color: #b4befe; }"
            "QPushButton:disabled { color: #45475a; text-decoration: none; }"
        )
        self._drive_folder_btn.clicked.connect(self._pick_drive_folder)
        drive_folder_row.addWidget(self._drive_folder_btn)
        layout.addLayout(drive_folder_row)

        sheets_row = QHBoxLayout()
        self._push_sheets = QCheckBox("Populate Google Sheet with data (for viewing/charting)")
        sheets_row.addWidget(self._push_sheets, stretch=1)
        sheets_help = self._make_help_button(
            "Populate Google Sheet with data",
            (
                "Writes the CSV data into a persistent Google Sheet named "
                "'Garmin Data' with two tabs: Daily and Activities. The Sheet's "
                "URL stays the same run after run — the cells just get refreshed.\n\n"
                "Best for: bookmarking one URL and coming back to see fresh data, "
                "building charts / pivot tables / dashboards on top of the sheet, "
                "or sharing a single live view with someone.\n\n"
                "Different from the Drive upload: this is a native Sheet, not a "
                "CSV file, so any charts or formatting you add stay attached and "
                "keep updating."
            ),
        )
        sheets_row.addWidget(sheets_help)
        layout.addLayout(sheets_row)

        local_note = QLabel(
            "CSVs are always saved locally to reports/ first. " "These options export them as well."
        )
        local_note.setWordWrap(True)
        local_note.setStyleSheet("color: #6c7086; font-size: 12px; margin-top: 4px;")
        layout.addWidget(local_note)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        # Initialize Drive folder UI state
        self._on_drive_toggled(False)
        self._refresh_drive_folder_label()

        # ── Buttons ──
        btn_row = QHBoxLayout()
        self._disable_btn = QPushButton("Disable")
        self._disable_btn.clicked.connect(self._on_disable)
        self._disable_btn.setEnabled(False)
        btn_row.addWidget(self._disable_btn)
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self._save_btn = QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        layout.addLayout(btn_row)

        self._load_current_state()

    def _load_current_state(self) -> None:
        from garmin_extract._windows_scheduler import get_task_status, parse_flags_from_command

        state = get_task_status()
        if not state["installed"]:
            self._status.setText("Not yet scheduled — pick a time and click Save.")
            self._status.setStyleSheet("color: #f9e2af;")
            return

        start = state.get("start_time") or ""
        next_run = state.get("next_run_time") or ""
        self._status.setText(
            f"✓ Scheduled daily at {start}" + (f"  (next run: {next_run})" if next_run else "")
        )
        self._status.setStyleSheet("color: #a6e3a1;")
        self._disable_btn.setEnabled(True)

        # Pre-fill time + flags from the installed task
        try:
            hh, mm = start.split(":", 1)[0:2] if ":" in start else ("6", "0")
            hh_int, mm_int = int(hh[:2]), int(mm[:2])
            self._time_edit.setTime(QTime(hh_int, mm_int))
        except Exception:
            pass
        cmd = state.get("task_to_run") or ""
        if cmd:
            drive, sheets = parse_flags_from_command(cmd)
            self._push_drive.setChecked(drive)
            self._push_sheets.setChecked(sheets)

    def _show_error(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.show()

    def _make_help_button(self, title: str, body: str) -> QPushButton:
        """Small circular '?' button that pops an info dialog with *body*."""
        btn = QPushButton("?")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            "QPushButton {"
            " color: #89b4fa; background-color: transparent;"
            " border: 1px solid #45475a; border-radius: 11px; font-weight: bold;"
            "}"
            "QPushButton:hover { border-color: #89b4fa; color: #b4befe; }"
        )
        btn.clicked.connect(lambda: self._show_help(title, body))
        return btn

    def _show_help(self, title: str, body: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(body)
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()

    def _on_drive_toggled(self, checked: bool) -> None:
        self._drive_folder_label.setEnabled(checked)
        self._drive_folder_btn.setEnabled(checked)

    def _refresh_drive_folder_label(self) -> None:
        """Load the configured folder name from config and update the label."""
        try:
            from garmin_extract._google_drive import load_config

            cfg = load_config()
            folder_id = cfg.get("folder_id")
            if not folder_id:
                self._drive_folder_label.setText("Folder: Garmin Extract (default)")
                return
            # Resolve name in a thread to avoid blocking on network
            Thread(target=self._resolve_folder_name, args=(folder_id,), daemon=True).start()
        except Exception:
            pass

    def _resolve_folder_name(self, folder_id: str) -> None:
        try:
            from garmin_extract._google_drive import _load_credentials, get_folder_name

            creds = _load_credentials()
            name = get_folder_name(creds, folder_id) or folder_id[:12] + "…"
            # Update label on the main thread via QTimer.singleShot
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self._drive_folder_label.setText(f"Folder: {name}"))
        except Exception:
            pass

    def _pick_drive_folder(self) -> None:
        dlg = _DriveFolderPickerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_folder_id:
            from garmin_extract._google_drive import load_config, save_config

            cfg = load_config()
            cfg["folder_id"] = dlg.selected_folder_id
            save_config(cfg)
            self._drive_folder_label.setText(f"Folder: {dlg.selected_folder_name}")

    def _on_save(self) -> None:
        from garmin_extract._windows_scheduler import create_or_update_task

        t = self._time_edit.time()
        ok, detail = create_or_update_task(
            hour=t.hour(),
            minute=t.minute(),
            push_drive=self._push_drive.isChecked(),
            push_sheets=self._push_sheets.isChecked(),
        )
        if ok:
            self.accept()
        else:
            self._show_error(f"Could not schedule: {detail}")

    def _on_disable(self) -> None:
        from garmin_extract._windows_scheduler import delete_task

        ok, detail = delete_task()
        if ok:
            self.accept()
        else:
            self._show_error(f"Could not remove scheduled task: {detail}")


# ── Automation page ──────────────────────────────────────────────────────────


class AutomationPage(QWidget):
    """The Automation page shown in the main window's stacked widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Wrap content in a scroll area so the page gracefully scrolls when
        # cards + buttons exceed the viewport height instead of compressing.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        heading = QLabel("Automation")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        sub = QLabel("Gmail MFA, scheduled pulls, Drive / Sheets")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        layout.addSpacing(16)

        # ── Garmin Credentials card (Windows only) ────
        self._creds_card: _SectionCard | None = None
        if _WINDOWS:
            self._creds_card = _SectionCard(
                "Garmin Credentials", "Email and password for automated pulls"
            )
            self._creds_card.add_action_button("Configure", self._open_credentials)
            layout.addWidget(self._creds_card)
            layout.addSpacing(4)

        # ── Gmail MFA card ────────────────────────────
        self._gmail_card = _SectionCard("Gmail MFA", "Automatic MFA code retrieval from Gmail")
        self._gmail_card.add_action_button("Configure", self._open_gmail_setup)
        layout.addWidget(self._gmail_card)

        layout.addSpacing(4)

        # ── Scheduled Pulls card ──────────────────────
        self._sched_card = _SectionCard(
            "Scheduled Pulls",
            "Run a daily pull automatically via Windows Task Scheduler",
        )
        if _WINDOWS:
            self._sched_card.add_action_button("Configure", self._open_scheduled_pulls)
        else:
            self._sched_card.set_status("Available on Windows only", "#6c7086")
        layout.addWidget(self._sched_card)

        layout.addSpacing(4)

        # ── Drive / Sheets card ───────────────────────
        self._drive_card = _SectionCard("Google Drive / Sheets", "Export data to Google services")
        self._drive_upload_btn = self._drive_card.add_action_button(
            "Upload CSVs to Drive", self._do_drive
        )
        self._drive_sheets_btn = self._drive_card.add_action_button(
            "Sync to Sheets", self._do_sheets
        )
        self._drive_both_btn = self._drive_card.add_action_button("Both", self._do_both)
        layout.addWidget(self._drive_card)

        layout.addStretch()

        # ── Status feedback ───────────────────────────
        self._feedback = QLabel()
        self._feedback.setStyleSheet("color: #6c7086; font-size: 13px;")
        self._feedback.setWordWrap(True)
        layout.addWidget(self._feedback)

        # Wire up signals and run initial checks
        self._signals = _AutoSignals()
        self._signals.gmail_done.connect(self._on_gmail_done)
        self._signals.drive_auth_done.connect(self._on_drive_auth_done)
        self._signals.drive_op_done.connect(self._on_drive_op_done)
        if _WINDOWS:
            self._signals.creds_done.connect(self._on_creds_done)
            self._signals.sched_done.connect(self._on_sched_done)
        self.refresh_status()

    def refresh_status(self) -> None:
        Thread(target=self._check_gmail, daemon=True).start()
        Thread(target=self._check_drive, daemon=True).start()
        if _WINDOWS:
            Thread(target=self._check_creds, daemon=True).start()
            Thread(target=self._check_sched, daemon=True).start()

    # ── Credentials (Windows only) ────────────────────────────────────────

    def _check_creds(self) -> None:
        from garmin_extract._credentials import check_credentials

        ok, detail = check_credentials()
        self._signals.creds_done.emit(ok, detail)

    def _on_creds_done(self, ok: bool, detail: str) -> None:
        if self._creds_card is None:
            return
        import re

        clean = re.sub(r"\[/?[^\]]*\]", "", detail)
        color = "#a6e3a1" if ok else "#6c7086"
        self._creds_card.set_status(("\u2713 " if ok else "") + clean, color)

    def _open_credentials(self) -> None:
        from garmin_extract.gui.screens.setup import CredentialsDialog

        dlg = CredentialsDialog(self)
        dlg.exec()
        self.refresh_status()

    def _open_gmail_setup(self) -> None:
        dlg = _GmailSetupDialog(self)
        dlg.exec()
        self.refresh_status()

    # ── Scheduled Pulls (Windows only) ───────────────────────────────────

    def _check_sched(self) -> None:
        from garmin_extract._windows_scheduler import get_task_status

        state = get_task_status()
        if state["installed"]:
            start = state.get("start_time") or ""
            detail = f"Scheduled daily at {start}" if start else "Scheduled"
            self._signals.sched_done.emit(True, detail)
        else:
            self._signals.sched_done.emit(False, "Not scheduled")

    def _on_sched_done(self, installed: bool, detail: str) -> None:
        if installed:
            self._sched_card.set_status("\u2713 " + detail, "#a6e3a1")
        else:
            self._sched_card.set_status(detail, "#6c7086")

    def _open_scheduled_pulls(self) -> None:
        dlg = _ScheduledPullsDialog(self)
        dlg.exec()
        self.refresh_status()

    def _check_gmail(self) -> None:
        status, detail = _check_gmail_automation()
        if status == "ok":
            self._signals.gmail_done.emit(status, detail, "#a6e3a1")
        elif status == "partial":
            self._signals.gmail_done.emit(status, detail, "#f9e2af")
        else:
            self._signals.gmail_done.emit(status, detail, "#6c7086")

    def _on_gmail_done(self, status: str, detail: str, color: str) -> None:
        if status == "ok":
            self._gmail_card.set_status("\u2713 " + detail, color)
        elif status == "partial":
            self._gmail_card.set_status("\u26a0 " + detail, color)
        else:
            self._gmail_card.set_status(detail, color)

    def _check_drive(self) -> None:
        status, detail = _check_drive_auth()
        cfg = _load_drive_config()
        last = cfg.get("last_export", "")
        last_text = ""
        if last:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(last).astimezone(None)
                last_text = f"Last export: {dt.strftime('%Y-%m-%d %H:%M')}"
            except Exception:
                last_text = f"Last export: {last[:19]}"

        if status == "ok":
            auth_text = "\u2713 Drive and Sheets authorized"
        elif status == "missing_scopes":
            auth_text = f"\u26a0 {detail}"
        else:
            auth_text = detail

        self._signals.drive_auth_done.emit(auth_text, last_text)

    def _on_drive_auth_done(self, auth_text: str, last_text: str) -> None:
        combined = auth_text
        if last_text:
            combined += f"  |  {last_text}"
        self._drive_card.set_status(combined)

    # ── Drive/Sheets actions ─────────────────────────────────────────────

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._drive_upload_btn.setEnabled(enabled)
        self._drive_sheets_btn.setEnabled(enabled)
        self._drive_both_btn.setEnabled(enabled)

    def _do_drive(self) -> None:
        self._set_buttons_enabled(False)
        self._feedback.setText("Uploading CSVs to Drive...")
        Thread(target=self._run_drive, daemon=True).start()

    def _do_sheets(self) -> None:
        self._set_buttons_enabled(False)
        self._feedback.setText("Syncing to Google Sheets...")
        Thread(target=self._run_sheets, daemon=True).start()

    def _do_both(self) -> None:
        self._set_buttons_enabled(False)
        self._feedback.setText("Uploading CSVs and syncing Sheets...")
        Thread(target=self._run_both, daemon=True).start()

    def _run_drive(self) -> None:
        try:
            from garmin_extract._google_drive import upload_csvs_to_drive

            result = upload_csvs_to_drive()
            if result["ok"]:
                names = ", ".join(f["name"] for f in result["files"])
                self._signals.drive_op_done.emit(f"\u2713 Uploaded: {names}")
            else:
                self._signals.drive_op_done.emit(f"Error: {result['error']}")
        except Exception as exc:
            self._signals.drive_op_done.emit(f"Error: {exc}")

    def _run_sheets(self) -> None:
        try:
            from garmin_extract._google_drive import sync_to_sheets

            result = sync_to_sheets()
            if result["ok"]:
                self._signals.drive_op_done.emit("\u2713 Google Sheet updated")
            else:
                self._signals.drive_op_done.emit(f"Error: {result['error']}")
        except Exception as exc:
            self._signals.drive_op_done.emit(f"Error: {exc}")

    def _run_both(self) -> None:
        try:
            from garmin_extract._google_drive import sync_to_sheets, upload_csvs_to_drive

            lines = []
            drive_result = upload_csvs_to_drive()
            if drive_result["ok"]:
                names = ", ".join(f["name"] for f in drive_result["files"])
                lines.append(f"\u2713 Drive: {names}")
            else:
                lines.append(f"Drive error: {drive_result['error']}")

            sheets_result = sync_to_sheets()
            if sheets_result["ok"]:
                lines.append("\u2713 Sheets updated")
            else:
                lines.append(f"Sheets error: {sheets_result['error']}")

            self._signals.drive_op_done.emit("  |  ".join(lines))
        except Exception as exc:
            self._signals.drive_op_done.emit(f"Error: {exc}")

    def _on_drive_op_done(self, text: str) -> None:
        self._feedback.setText(text)
        self._set_buttons_enabled(True)
        self.refresh_status()
