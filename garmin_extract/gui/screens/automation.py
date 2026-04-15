"""Automation page — Gmail MFA status, scheduled pulls, Drive/Sheets export."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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


# ── Status card (reused from setup) ─────────────────────────────────────────


class _SectionCard(QFrame):
    """A card for displaying automation section status."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 16px;
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


# ── Automation page ──────────────────────────────────────────────────────────


class AutomationPage(QWidget):
    """The Automation page shown in the main window's stacked widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(8)

        heading = QLabel("Automation")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        sub = QLabel("Gmail MFA, scheduled pulls, Drive / Sheets")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        layout.addSpacing(16)

        # ── Gmail MFA card ────────────────────────────
        self._gmail_card = _SectionCard("Gmail MFA", "Automatic MFA code retrieval from Gmail")
        layout.addWidget(self._gmail_card)

        layout.addSpacing(4)

        # ── Scheduled Pulls card ──────────────────────
        self._sched_card = _SectionCard(
            "Scheduled Pulls",
            "Windows Task Scheduler — coming in issue #31",
        )
        self._sched_card.set_status("Not yet implemented", "#6c7086")
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
        self.refresh_status()

    def refresh_status(self) -> None:
        Thread(target=self._check_gmail, daemon=True).start()
        Thread(target=self._check_drive, daemon=True).start()

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
