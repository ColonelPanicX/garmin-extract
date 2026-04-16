"""Pull Progress screen — live log, metrics panel, MFA modal, cancel."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from threading import Thread

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from garmin_extract._paths import app_root, bundle_root

ROOT = app_root()  # user-facing files (.mfa_code, .env, data/)
SCRIPTS_ROOT = bundle_root()  # subprocess script files (pullers/, reports/)
MFA_FILE = ROOT / ".mfa_code"


# ── Signals ──────────────────────────────────────────────────────────────────


class _PullSignals(QObject):
    log_line = Signal(str)
    day_start = Signal(str, int)  # date_str, n_metrics
    day_skipped = Signal(str)  # date_str
    metric_done = Signal(str, bool)  # name, is_ok
    mfa_needed = Signal()
    finished = Signal(int)  # return code
    error = Signal(str)


# ── MFA dialog ───────────────────────────────────────────────────────────────


class _MfaDialog(QDialog):
    """Modal dialog to capture an MFA code."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MFA Code Required")
        self.setMinimumWidth(400)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("MFA Code Required")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f9e2af;")
        layout.addWidget(title)

        hint = QLabel("Check your email for a 6-digit code and enter it below.")
        hint.setStyleSheet("color: #6c7086;")
        layout.addWidget(hint)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("000000")
        self._code_input.setMaxLength(6)
        self._code_input.returnPressed.connect(self._submit)
        layout.addWidget(self._code_input)

        self._error = QLabel()
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.hide()
        layout.addWidget(self._error)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("Submit")
        ok.clicked.connect(self._submit)
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

    def _submit(self) -> None:
        code = self._code_input.text().strip()
        if not code:
            self._error.setText("Please enter the 6-digit code.")
            self._error.show()
            return
        MFA_FILE.write_text(code + "\n")
        self.accept()


# ── Runtime credentials dialog ───────────────────────────────────────────────


class _RuntimeCredsDialog(QDialog):
    """Dialog for entering credentials at runtime when none are saved."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enter Garmin Connect Credentials")
        self.setMinimumWidth(450)
        self.setModal(True)

        self.result_email = ""
        self.result_password = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel("No saved credentials found. These will not be stored.")
        hint.setStyleSheet("color: #6c7086;")
        layout.addWidget(hint)

        layout.addWidget(QLabel("Email"))
        self._email = QLineEdit()
        self._email.setPlaceholderText("you@example.com")
        layout.addWidget(self._email)

        layout.addWidget(QLabel("Password"))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("Garmin Connect password")
        self._password.returnPressed.connect(self._submit)
        layout.addWidget(self._password)

        self._error = QLabel()
        self._error.setStyleSheet("color: #f38ba8;")
        self._error.hide()
        layout.addWidget(self._error)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("Continue")
        ok.clicked.connect(self._submit)
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

    def _submit(self) -> None:
        email = self._email.text().strip()
        password = self._password.text().strip()
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
        self.result_email = email
        self.result_password = password
        self.accept()


# ── Day state for multi-day pulls ────────────────────────────────────────────


@dataclass
class _DayState:
    date_str: str
    total: int = 0
    done: int = 0
    failed: int = 0
    status: str = "pending"  # pending | active | done | skipped


# ── Pull Progress Dialog ─────────────────────────────────────────────────────


class PullProgressDialog(QDialog):
    """Full pull progress view — split log + metrics panel, progress bar, cancel."""

    def __init__(
        self,
        start_date: str,
        days: int,
        label: str,
        no_skip: bool = False,
        rebuild_only: bool = False,
        zip_path: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(label)
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        self.setModal(True)

        self._start_date = start_date
        self._days = days
        self._label = label
        self._no_skip = no_skip
        self._rebuild_only = rebuild_only
        self._zip_path = zip_path
        self._proc: subprocess.Popen | None = None
        self._mfa_shown = False
        self._email = ""
        self._password = ""

        # Display mode
        if days > 1:
            self._mode = "day"
            self._day_states = self._init_day_states()
            self._current_day_index = -1
            self._metrics_per_day = 0
        elif days == 1:
            self._mode = "metric"
            self._live_metrics: list[tuple[str, str]] = []
            self._day_total = 0
            self._day_done = 0
        else:
            self._mode = "simple"

        self._overall_done = 0
        self._overall_total = max(days, 1)

        self._build_ui()
        self._wire_signals()

        # Check credentials then start
        if self._rebuild_only or self._zip_path:
            self._start_pull()
        else:
            self._check_creds_and_start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Split view: log + metrics ─────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Log panel (left)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background-color: #1e1e2e; color: #cdd6f4; font-family: monospace;"
            " font-size: 13px; border: none; border-right: 1px solid #45475a;"
        )
        splitter.addWidget(self._log)

        # Metrics panel (right)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)

        self._header = QLabel(self._label)
        self._header.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #89b4fa; background: transparent;"
        )
        right_layout.addWidget(self._header)

        self._subheader = QLabel()
        self._subheader.setStyleSheet("color: #6c7086; background: transparent;")
        right_layout.addWidget(self._subheader)

        self._metric_list = QTextEdit()
        self._metric_list.setReadOnly(True)
        self._metric_list.setStyleSheet(
            "background-color: transparent; color: #cdd6f4;" " font-size: 13px; border: none;"
        )
        self._metric_list.setText(self._initial_panel_body())
        right_layout.addWidget(self._metric_list)

        splitter.addWidget(right)
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)

        # ── Bottom bar: progress + status + cancel ────
        bottom = QWidget()
        bottom.setStyleSheet("background-color: #313244; border-top: 1px solid #45475a;")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 8, 12, 8)
        bottom_layout.setSpacing(4)

        self._progress = QProgressBar()
        self._progress.setMaximum(self._overall_total)
        self._progress.setValue(0)
        self._progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #45475a;
                border-radius: 4px;
                text-align: center;
                color: #cdd6f4;
                background-color: #1e1e2e;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
            """)
        bottom_layout.addWidget(self._progress)

        status_row = QHBoxLayout()
        self._status = QLabel("Starting...")
        self._status.setStyleSheet("color: #6c7086; background: transparent;")
        status_row.addWidget(self._status, stretch=1)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 16px;
                background-color: #45475a;
                border: 1px solid #585b70;
                border-radius: 4px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #f38ba8;
                color: #1e1e2e;
            }
            """)
        self._cancel_btn.clicked.connect(self._cancel)
        status_row.addWidget(self._cancel_btn)

        bottom_layout.addLayout(status_row)
        layout.addWidget(bottom)

    def _wire_signals(self) -> None:
        self._signals = _PullSignals()
        self._signals.log_line.connect(self._on_log_line)
        self._signals.day_start.connect(self._on_day_start)
        self._signals.day_skipped.connect(self._on_day_skipped)
        self._signals.metric_done.connect(self._on_metric_done)
        self._signals.mfa_needed.connect(self._on_mfa_needed)
        self._signals.finished.connect(self._on_finished)
        self._signals.error.connect(self._on_error)

    # ── credential check ─────────────────────────────────────────────────

    def _check_creds_and_start(self) -> None:
        from garmin_extract._credentials import load_credentials

        email, password = load_credentials()
        if password:
            self._email = email
            self._password = password
            self._start_pull()
        else:
            dlg = _RuntimeCredsDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._email = dlg.result_email
                self._password = dlg.result_password
                self._start_pull()
            else:
                self.reject()

    # ── subprocess ────────────────────────────────────────────────────────

    def _start_pull(self) -> None:
        cmd = self._build_cmd()
        Thread(target=self._run_pull, args=(cmd,), daemon=True).start()

    def _build_cmd(self) -> list[str]:
        if self._rebuild_only:
            return [sys.executable, "-u", str(SCRIPTS_ROOT / "reports" / "build_garmin_csvs.py")]
        if self._zip_path:
            return [
                sys.executable,
                "-u",
                str(SCRIPTS_ROOT / "pullers" / "garmin_import_export.py"),
                "--zip",
                self._zip_path,
            ]
        cmd = [
            sys.executable,
            "-u",
            str(SCRIPTS_ROOT / "pullers" / "garmin.py"),
            "--date",
            self._start_date,
            "--days",
            str(self._days),
        ]
        if self._no_skip:
            cmd.append("--no-skip")
        return cmd

    def _run_pull(self, cmd: list[str]) -> None:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"  # force UTF-8 I/O in subprocess (Windows cp1252 can't encode ✓)
        if self._email:
            env["GARMIN_EMAIL"] = self._email
        if self._password:
            env["GARMIN_PASSWORD"] = self._password

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                encoding="utf-8",
                cwd=str(ROOT),
                env=env,
            )
            self._proc = proc
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                self._signals.log_line.emit(line)
                self._parse_line(line)
            proc.wait()
            self._proc = None
            self._signals.finished.emit(proc.returncode)
        except Exception as exc:
            self._proc = None
            self._signals.error.emit(str(exc))

    def _parse_line(self, line: str) -> None:
        """Parse subprocess output and emit appropriate signals."""
        stripped = line.strip()

        # "[2025-04-06] Pulling N metrics..."
        if stripped.startswith("[") and "] Pulling " in stripped and "metrics" in stripped:
            try:
                date_str = stripped[1 : stripped.index("]")]
                parts = stripped.split()
                idx = next((i for i, p in enumerate(parts) if p == "Pulling"), -1)
                n = int(parts[idx + 1]) if idx >= 0 else 0
                self._signals.day_start.emit(date_str, n)
            except (ValueError, IndexError):
                pass
            return

        # "[2025-04-06] Already pulled — skipping"
        if "Already pulled" in stripped and "skipping" in stripped:
            try:
                date_str = stripped[1 : stripped.index("]")]
                self._signals.day_skipped.emit(date_str)
            except ValueError:
                pass
            return

        # "✓/✗  metric_name"
        if stripped.startswith("\u2713") or stripped.startswith("\u2717"):
            parts = stripped.split()
            if parts:
                self._signals.metric_done.emit(parts[-1], stripped.startswith("\u2713"))
            return

        # MFA prompt
        if "Run: echo YOUR_CODE" in stripped:
            self._signals.mfa_needed.emit()

    # ── day state init ───────────────────────────────────────────────────

    def _init_day_states(self) -> list[_DayState]:
        states: list[_DayState] = []
        try:
            start = date.fromisoformat(self._start_date)
            for i in range(self._days):
                states.append(_DayState((start + timedelta(days=i)).isoformat()))
        except ValueError:
            pass
        return states

    def _initial_panel_body(self) -> str:
        if self._mode == "day":
            return self._render_day_list()
        if self._mode == "metric":
            return "Waiting for first metric..."
        return "Starting..."

    # ── signal handlers (main thread) ────────────────────────────────────

    def _on_log_line(self, line: str) -> None:
        self._log.append(line)

    def _on_day_start(self, date_str: str, n_metrics: int) -> None:
        if self._mode == "day":
            idx = next(
                (i for i, s in enumerate(self._day_states) if s.date_str == date_str),
                -1,
            )
            if idx == -1:
                self._day_states.append(_DayState(date_str))
                idx = len(self._day_states) - 1
            self._current_day_index = idx
            self._day_states[idx].status = "active"
            self._day_states[idx].total = n_metrics

            if self._metrics_per_day == 0 and n_metrics > 0:
                self._metrics_per_day = n_metrics
                self._overall_total = self._days * n_metrics
                self._progress.setMaximum(self._overall_total)

            self._refresh_panel()
            self._status.setText(f"Day {idx + 1} of {self._days}  \u00b7  {date_str}")

        elif self._mode == "metric":
            self._day_total = n_metrics
            self._day_done = 0
            self._live_metrics = []
            if n_metrics > 0:
                self._progress.setMaximum(n_metrics)
            self._subheader.setText(date_str)
            self._refresh_panel()
            self._status.setText(f"Pulling {date_str}...")

    def _on_day_skipped(self, date_str: str) -> None:
        if self._mode == "day":
            idx = next(
                (i for i, s in enumerate(self._day_states) if s.date_str == date_str),
                -1,
            )
            if idx >= 0:
                self._day_states[idx].status = "skipped"
                advance = self._metrics_per_day if self._metrics_per_day else 1
                self._overall_done += advance
                self._progress.setValue(self._overall_done)
                self._refresh_panel()
                self._status.setText(f"Skipped {date_str}  (already pulled)")

    def _on_metric_done(self, name: str, is_ok: bool) -> None:
        if self._mode == "metric":
            self._live_metrics.append((name, "done" if is_ok else "fail"))
            self._day_done += 1
            self._progress.setValue(self._day_done)
            self._refresh_panel()
            self._status.setText(f"{self._day_done} / {self._day_total or '?'} metrics")

        elif self._mode == "day" and self._current_day_index >= 0:
            ds = self._day_states[self._current_day_index]
            if is_ok:
                ds.done += 1
            else:
                ds.failed += 1

            tally = ds.done + ds.failed
            if ds.total == 0 or tally <= ds.total:
                self._overall_done += 1
                self._progress.setValue(self._overall_done)

            if ds.total > 0 and tally >= ds.total:
                ds.status = "done"

            self._refresh_panel()
            self._status.setText(
                f"Day {self._current_day_index + 1} of {self._days}"
                f"  \u00b7  {min(tally, ds.total) if ds.total else tally}"
                f"/{ds.total or '?'} metrics"
            )

    def _on_mfa_needed(self) -> None:
        if not self._mfa_shown:
            self._mfa_shown = True
            _MfaDialog(self).exec()

    def _on_finished(self, returncode: int) -> None:
        if self._mode == "simple":
            self._progress.setMaximum(1)
            self._progress.setValue(1)
            if returncode == 0:
                self._metric_list.setText("\u2713 Complete")
            else:
                self._metric_list.setText("\u2717 Failed")

        if returncode == 0:
            self._status.setText("Complete \u2713")
            self._log.append("\nDone.")
        else:
            self._status.setText(f"Finished with errors (exit {returncode})")
            self._log.append(f"\nProcess exited with code {returncode}.")

        self._cancel_btn.setText("Close")
        self._cancel_btn.clicked.disconnect()
        self._cancel_btn.clicked.connect(self.accept)

    def _on_error(self, msg: str) -> None:
        self._log.append(f"\nError: {msg}")
        self._status.setText("Error")
        self._cancel_btn.setText("Close")
        self._cancel_btn.clicked.disconnect()
        self._cancel_btn.clicked.connect(self.accept)

    # ── panel rendering ──────────────────────────────────────────────────

    def _refresh_panel(self) -> None:
        if self._mode == "day":
            self._metric_list.setText(self._render_day_list())
        elif self._mode == "metric":
            self._metric_list.setText(self._render_metric_list())

    def _render_day_list(self) -> str:
        lines: list[str] = []
        for ds in self._day_states:
            if ds.status == "done":
                tally = min(ds.done + ds.failed, ds.total) if ds.total else ds.done + ds.failed
                count = f"({tally}/{ds.total})" if ds.total else ""
                failed = f"  {ds.failed} failed" if ds.failed else ""
                lines.append(f"\u2713 {ds.date_str}  {count}{failed}")
            elif ds.status == "active":
                count = f"{ds.done + ds.failed}/{ds.total}" if ds.total else "\u2026"
                lines.append(f"\u25cf {ds.date_str}  ({count})")
            elif ds.status == "skipped":
                lines.append(f"\u21b7 {ds.date_str}  (skipped)")
            else:
                lines.append(f"\u25cb  {ds.date_str}")
        return "\n".join(lines)

    def _render_metric_list(self) -> str:
        if not self._live_metrics:
            return "Waiting for first metric..."
        lines: list[str] = []
        for name, state in self._live_metrics:
            icon = "\u2713" if state == "done" else "\u2717"
            lines.append(f"{icon} {name}")
        return "\n".join(lines)

    # ── cancel ───────────────────────────────────────────────────────────

    def _cancel(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.reject()

    def closeEvent(self, event: object) -> None:  # noqa: N802
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        super().closeEvent(event)
