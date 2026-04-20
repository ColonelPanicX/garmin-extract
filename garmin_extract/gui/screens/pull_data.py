"""Pull Data page — all 8 pull options plus date/file dialogs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _date_range_label(days: int) -> str:
    today = date.today()
    start = today - timedelta(days=days)
    end = today - timedelta(days=1)
    return f"{start.isoformat()}  \u2192  {end.isoformat()}"


def _parse_date(s: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _find_fetch_new_range() -> tuple[str, int] | None:
    """Returns (start_iso, days) or None if up to date. Raises FileNotFoundError."""
    import re

    data_dir = Path(__file__).parent.parent.parent.parent / "data" / "garmin"
    if not data_dir.exists():
        raise FileNotFoundError("no data directory")
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
    dates = sorted(f.stem for f in data_dir.glob("*.json") if date_re.match(f.name))
    if not dates:
        raise FileNotFoundError("no date files")
    latest = date.fromisoformat(dates[-1])
    yesterday = date.today() - timedelta(days=1)
    start = latest + timedelta(days=1)
    if start > yesterday:
        return None
    return start.isoformat(), (yesterday - start).days + 1


def _get_latest_sync_status() -> tuple[str, int] | None:
    """Returns (latest_iso, days_behind). None if no local data.

    days_behind is 0 when latest ≥ yesterday (in sync), otherwise the
    count of days between the latest local record and yesterday.
    """
    import re

    data_dir = Path(__file__).parent.parent.parent.parent / "data" / "garmin"
    if not data_dir.exists():
        return None
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
    dates = sorted(f.stem for f in data_dir.glob("*.json") if date_re.match(f.name))
    if not dates:
        return None
    latest = date.fromisoformat(dates[-1])
    yesterday = date.today() - timedelta(days=1)
    return dates[-1], max(0, (yesterday - latest).days)


# ── Section header widget ────────────────────────────────────────────────────


class _SectionHeader(QLabel):
    """A dim section header label (SYNC, RECENT, CUSTOM, etc.)."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #6c7086;"
            " letter-spacing: 1px; background: transparent;"
            " border-bottom: 1px solid #45475a; padding-bottom: 4px;"
        )


# ── Latest Sync card ─────────────────────────────────────────────────────────


class _LatestSyncCard(QWidget):
    """Shows the most recent local data date and staleness. Call refresh()
    after a pull to update."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(_SectionHeader("LATEST SYNC"))
        self._status = QLabel()
        layout.addWidget(self._status)
        layout.addSpacing(4)
        self.refresh()

    def refresh(self) -> None:
        result = _get_latest_sync_status()
        if result is None:
            text = "No local data — run Fetch new to start"
            color = "#f9e2af"
        else:
            date_iso, days = result
            if days == 0:
                text = f"{date_iso}  (up to date)"
                color = "#a6e3a1"
            else:
                word = "day" if days == 1 else "days"
                text = f"{date_iso}  ({days} {word} out of sync)"
                color = "#f9e2af"
        self._status.setText(text)
        self._status.setStyleSheet(f"font-size: 14px; color: {color}; background: transparent;")


# ── Action button widget ─────────────────────────────────────────────────────


class _ActionButton(QPushButton):
    """A menu-style button matching the TUI's pull options."""

    def __init__(self, label: str, hint: str = "", parent: QWidget | None = None) -> None:
        display = f"{label}    {hint}" if hint else label
        super().__init__(display, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 10px 16px;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                font-size: 14px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #313244;
                border-color: #45475a;
            }
            QPushButton:pressed {
                background-color: #45475a;
            }
            """)


# ── Date input dialog ────────────────────────────────────────────────────────


class _DateDialog(QDialog):
    """Dialog for entering a start date and optional day count."""

    def __init__(
        self,
        title: str,
        show_days: bool = False,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setModal(True)

        self.result_start: str = ""
        self.result_days: int = 1

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet("color: #6c7086; font-size: 13px;")
            layout.addWidget(hint_label)

        layout.addWidget(QLabel("Start date"))
        self._date_input = QLineEdit()
        self._date_input.setPlaceholderText("YYYY-MM-DD  or  MM/DD/YYYY")
        layout.addWidget(self._date_input)

        if show_days:
            layout.addWidget(QLabel("Number of days"))
            self._days_input = QLineEdit()
            self._days_input.setPlaceholderText("Default: 1")
            layout.addWidget(self._days_input)
        else:
            self._days_input = None

        self._error = QLabel()
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.hide()
        layout.addWidget(self._error)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("Pull")
        ok.clicked.connect(self._validate)
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

        self._date_input.returnPressed.connect(self._validate)

    def _validate(self) -> None:
        raw = self._date_input.text().strip()
        parsed = _parse_date(raw)
        if not parsed:
            self._error.setText(f"Cannot parse '{raw}' — try 2025-04-07")
            self._error.show()
            return

        self.result_start = parsed

        if self._days_input:
            days_raw = self._days_input.text().strip()
            self.result_days = int(days_raw) if days_raw.isdigit() and int(days_raw) > 0 else 1
        else:
            start_dt = datetime.strptime(parsed, "%Y-%m-%d").date()
            yesterday = date.today() - timedelta(days=1)
            self.result_days = (yesterday - start_dt).days + 1
            if self.result_days <= 0:
                self._error.setText("Start date must be before today.")
                self._error.show()
                return

        self.accept()


# ── Pull Data page ───────────────────────────────────────────────────────────


class PullDataPage(QWidget):
    """The Pull Data page shown in the main window's stacked widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(4)

        heading = QLabel("Pull Data")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        sub = QLabel("Download your Garmin health metrics")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        layout.addSpacing(16)

        # ── LATEST SYNC ───────────────────────────────
        self._latest_sync = _LatestSyncCard()
        layout.addWidget(self._latest_sync)

        layout.addSpacing(8)

        # ── SYNC ──────────────────────────────────────
        layout.addWidget(_SectionHeader("SYNC"))
        btn = _ActionButton("Fetch new", "pull all dates not yet in local data")
        btn.clicked.connect(self._fetch_new)
        layout.addWidget(btn)

        layout.addSpacing(8)

        # ── RECENT ────────────────────────────────────
        layout.addWidget(_SectionHeader("RECENT"))
        btn = _ActionButton("Yesterday", _yesterday())
        btn.clicked.connect(self._pull_yesterday)
        layout.addWidget(btn)

        btn = _ActionButton("Last 7 days", _date_range_label(7))
        btn.clicked.connect(self._pull_7)
        layout.addWidget(btn)

        btn = _ActionButton("Last 30 days", _date_range_label(30))
        btn.clicked.connect(self._pull_30)
        layout.addWidget(btn)

        layout.addSpacing(8)

        # ── CUSTOM ────────────────────────────────────
        layout.addWidget(_SectionHeader("CUSTOM"))
        btn = _ActionButton("Specific date or range")
        btn.clicked.connect(self._pull_custom)
        layout.addWidget(btn)

        btn = _ActionButton("Full history", "(from a date you choose)")
        btn.clicked.connect(self._pull_history)
        layout.addWidget(btn)

        layout.addSpacing(8)

        # ── IMPORT ────────────────────────────────────
        layout.addWidget(_SectionHeader("IMPORT"))
        btn = _ActionButton("Import from Garmin bulk export", ".zip")
        btn.clicked.connect(self._import_zip)
        layout.addWidget(btn)

        layout.addSpacing(8)

        # ── REPORTS ───────────────────────────────────
        layout.addWidget(_SectionHeader("REPORTS"))
        btn = _ActionButton("Rebuild CSV reports", "from existing data")
        btn.clicked.connect(self._rebuild_csvs)
        layout.addWidget(btn)

        layout.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────

    def _start_pull(self, start_date: str, days: int, label: str, **kwargs: object) -> None:
        """Open the pull progress dialog."""
        from garmin_extract.gui.screens.pull_progress import PullProgressDialog

        dlg = PullProgressDialog(
            start_date=start_date,
            days=days,
            label=label,
            no_skip=bool(kwargs.get("no_skip")),
            rebuild_only=bool(kwargs.get("rebuild_only")),
            zip_path=str(kwargs.get("zip_path", "")),
            parent=self,
        )
        dlg.exec()
        self._latest_sync.refresh()

    def _fetch_new(self) -> None:
        try:
            result = _find_fetch_new_range()
        except FileNotFoundError:
            dlg = _DateDialog(
                "Full History Pull",
                hint="No local data found. Choose a start date to begin pulling.",
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                end = date.fromisoformat(dlg.result_start) + timedelta(days=dlg.result_days - 1)
                self._start_pull(
                    dlg.result_start,
                    dlg.result_days,
                    f"Full history  ({dlg.result_start} \u2192 {end.isoformat()})",
                )
            return

        if result is None:
            QMessageBox.information(
                self, "Fetch New", "Already up to date \u2014 no new dates to pull."
            )
            return

        start, days = result
        end = (date.fromisoformat(start) + timedelta(days=days - 1)).isoformat()
        self._start_pull(start, days, f"Fetch new  ({start} \u2192 {end})")

    def _pull_yesterday(self) -> None:
        yest = _yesterday()
        self._start_pull(yest, 1, f"Yesterday  ({yest})")

    def _pull_7(self) -> None:
        start = (date.today() - timedelta(days=7)).isoformat()
        self._start_pull(start, 7, f"Last 7 days  ({_date_range_label(7)})")

    def _pull_30(self) -> None:
        start = (date.today() - timedelta(days=30)).isoformat()
        self._start_pull(start, 30, f"Last 30 days  ({_date_range_label(30)})")

    def _pull_custom(self) -> None:
        dlg = _DateDialog(
            "Custom Date Pull",
            show_days=True,
            hint="Formats: YYYY-MM-DD  \u00b7  MM/DD/YYYY  \u00b7  MM/DD/YY",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._start_pull(
                dlg.result_start,
                dlg.result_days,
                f"Custom  ({dlg.result_start}, {dlg.result_days}d)",
            )

    def _pull_history(self) -> None:
        dlg = _DateDialog(
            "Full History Pull",
            hint=(
                "Pulls every day from your chosen start date through yesterday.\n"
                "Formats: YYYY-MM-DD  \u00b7  MM/DD/YYYY  \u00b7  MM/DD/YY"
            ),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            self._start_pull(
                dlg.result_start,
                dlg.result_days,
                f"Full history  ({dlg.result_start} \u2192 {yesterday})",
            )

    def _import_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Garmin Export",
            "",
            "Zip files (*.zip);;All files (*)",
        )
        if not path:
            return
        self._start_pull("", 0, "Garmin bulk export import", zip_path=path)

    def _rebuild_csvs(self) -> None:
        self._start_pull("", 0, "Rebuilding CSV reports", rebuild_only=True)
