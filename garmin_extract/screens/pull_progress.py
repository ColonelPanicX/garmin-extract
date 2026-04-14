"""Pull progress screen — live metric-by-metric pull with split log panel."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, ProgressBar, RichLog, Static

ROOT = Path(__file__).parent.parent.parent
MFA_FILE = ROOT / ".mfa_code"

_METRICS: list[str] = [
    "stats",
    "user_summary_chart",
    "heart_rates",
    "resting_hr",
    "hrv",
    "stress",
    "body_battery",
    "body_battery_events",
    "sleep",
    "steps",
    "floors",
    "spo2",
    "respiration",
    "intensity_minutes",
    "all_day_events",
    "activities",
    "weigh_ins",
    "body_composition",
    "blood_pressure",
    "max_metrics",
    "training_readiness",
    "training_status",
    "fitness_age",
    "hydration",
    "lifestyle",
]

_LABEL: dict[str, str] = {
    "stats": "Daily Summary",
    "user_summary_chart": "Summary Chart",
    "heart_rates": "Heart Rate",
    "resting_hr": "Resting HR",
    "hrv": "HRV",
    "stress": "Stress",
    "body_battery": "Body Battery",
    "body_battery_events": "BB Events",
    "sleep": "Sleep",
    "steps": "Steps",
    "floors": "Floors",
    "spo2": "SpO\u2082",
    "respiration": "Respiration",
    "intensity_minutes": "Intensity Min",
    "all_day_events": "All-Day Events",
    "activities": "Activities",
    "weigh_ins": "Weigh-Ins",
    "body_composition": "Body Comp",
    "blood_pressure": "Blood Pressure",
    "max_metrics": "Max Metrics",
    "training_readiness": "Train Ready",
    "training_status": "Train Status",
    "fitness_age": "Fitness Age",
    "hydration": "Hydration",
    "lifestyle": "Lifestyle",
}


class _MfaModal(ModalScreen[None]):
    """Pop-up dialog to capture an MFA code and write it to .mfa_code."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]

    CSS = """
    _MfaModal {
        align: center middle;
    }

    #mfa-box {
        width: 52;
        height: auto;
        border: round $warning;
        padding: 1 2;
    }

    #mfa-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #mfa-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #mfa-error {
        color: $error;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="mfa-box"):
            yield Static("MFA Code Required", id="mfa-title")
            yield Static(
                "Check your email for a 6-digit code and enter it below.",
                id="mfa-hint",
            )
            yield Input(placeholder="000000", id="mfa-input", max_length=6)
            yield Static("", id="mfa-error")

    def on_mount(self) -> None:
        self.query_one("#mfa-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        code = event.value.strip()
        if not code:
            self.query_one("#mfa-error", Static).update("Please enter the 6-digit code.")
            return
        MFA_FILE.write_text(code + "\n")
        self.dismiss()


class PullProgressScreen(Screen[None]):
    """Full-screen live progress display for a Garmin data pull or CSV rebuild."""

    BINDINGS = [
        Binding("b", "back", "Back", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    CSS = """
    PullProgressScreen {
        layout: vertical;
    }

    #progress-layout {
        height: 1fr;
    }

    #log-panel {
        width: 2fr;
        border-right: solid $primary-darken-3;
    }

    #metric-panel {
        width: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #metric-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        height: auto;
    }

    #metric-subheader {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }

    #metric-list {
        height: auto;
        color: $text;
    }

    #status-bar {
        height: 3;
        padding: 0 1;
        border-top: solid $primary-darken-3;
    }

    #progress-bar {
        width: 1fr;
        margin: 1 0;
    }

    #status-label {
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(
        self,
        start_date: str,
        days: int,
        label: str,
        no_skip: bool = False,
        rebuild_only: bool = False,
        zip_path: str = "",
    ) -> None:
        super().__init__()
        self._start_date = start_date
        self._days = days
        self._label = label
        self._no_skip = no_skip
        self._rebuild_only = rebuild_only
        self._zip_path = zip_path

        self._done = False
        self._mfa_shown = False
        self._metric_states: dict[str, str] = {m: "pending" for m in _METRICS}
        self._overall_done = 0
        self._per_day_done = 0
        self._current_date = ""
        self._total_metrics = days * len(_METRICS) if days > 0 else len(_METRICS)

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="progress-layout"):
            yield RichLog(id="log-panel", highlight=True, markup=True, wrap=True)
            with Vertical(id="metric-panel"):
                yield Static(self._label, id="metric-header")
                yield Static("", id="metric-subheader")
                yield Static(self._render_metrics(), id="metric-list")
        with Vertical(id="status-bar"):
            yield ProgressBar(
                total=max(self._total_metrics, 1),
                id="progress-bar",
                show_eta=False,
            )
            yield Static("Starting...", id="status-label")
        yield Footer()

    def on_mount(self) -> None:
        cmd = self._build_cmd()
        self.run_worker(lambda: self._do_pull(cmd), thread=True, name="puller")

    # ── command builder ────────────────────────────────────────────────────────

    def _build_cmd(self) -> list[str]:
        if self._rebuild_only:
            return [sys.executable, str(ROOT / "reports" / "build_garmin_csvs.py")]
        if self._zip_path:
            return [
                sys.executable,
                str(ROOT / "pullers" / "garmin_import_export.py"),
                "--zip",
                self._zip_path,
            ]
        cmd = [
            sys.executable,
            str(ROOT / "pullers" / "garmin.py"),
            "--date",
            self._start_date,
            "--days",
            str(self._days),
        ]
        if self._no_skip:
            cmd.append("--no-skip")
        return cmd

    # ── worker (runs in a thread) ──────────────────────────────────────────────

    def _do_pull(self, cmd: list[str]) -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                cwd=str(ROOT),
            )
            assert proc.stdout is not None
            for raw_line in iter(proc.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                self.call_from_thread(self._on_line, line)
            proc.wait()
            self.call_from_thread(self._on_done, proc.returncode)
        except Exception as exc:
            self.call_from_thread(self._on_error, str(exc))

    # ── UI update helpers (called on main thread via call_from_thread) ─────────

    def _on_line(self, line: str) -> None:
        log = self.query_one("#log-panel", RichLog)
        log.write(line)

        stripped = line.strip()

        # New date starting: "[2025-04-06] Pulling 25 metrics..."
        if stripped.startswith("[") and "] Pulling " in stripped and "metrics" in stripped:
            try:
                self._current_date = stripped[1 : stripped.index("]")]
            except ValueError:
                pass
            self._metric_states = {m: "pending" for m in _METRICS}
            self._per_day_done = 0
            days_done = self._overall_done // len(_METRICS)
            subheader = (
                f"{self._current_date}  ·  Day {days_done + 1} of {self._days}"
                if self._days > 1
                else self._current_date
            )
            self.query_one("#metric-subheader", Static).update(f"[dim]{subheader}[/]")
            self._refresh_metric_list()
            self._set_status(f"Pulling {self._current_date}...")
            return

        # Metric line: "    ✓    metric_name" or "    ✗ HTTP 404 metric_name"
        if stripped.startswith("✓") or stripped.startswith("✗"):
            parts = stripped.split()
            if parts:
                metric = parts[-1]
                if metric in self._metric_states:
                    state = "done" if stripped.startswith("✓") else "fail"
                    self._metric_states[metric] = state
                    self._overall_done += 1
                    self._per_day_done += 1
                    self.query_one("#progress-bar", ProgressBar).advance(1)
                    self._refresh_metric_list()
                    done = sum(1 for s in self._metric_states.values() if s != "pending")
                    if self._days > 1:
                        days_done = self._overall_done // len(_METRICS)
                        self._set_status(
                            f"Day {days_done + 1} of {self._days}"
                            f"  ·  {done}/{len(_METRICS)} metrics"
                        )
                    else:
                        self._set_status(f"{done} / {len(_METRICS)} metrics")
            return

        # File-based MFA prompt detected (stdin=DEVNULL → non-interactive path)
        if "Run: echo YOUR_CODE" in stripped and not self._mfa_shown:
            self._mfa_shown = True
            self.app.push_screen(_MfaModal())
            return

        # Already-pulled skip notice
        if "Already pulled" in stripped and "skipping" in stripped:
            self._set_status(stripped)

    def _on_done(self, returncode: int) -> None:
        self._done = True
        if returncode == 0:
            self._set_status("Complete  ✓  — press  b  to go back")
            self.query_one("#log-panel", RichLog).write(
                "\n[green]Done.[/green]  Press  [bold]b[/bold]  to go back."
            )
        else:
            self._set_status(f"Finished with errors (exit {returncode})  — press  b  to go back")
            self.query_one("#log-panel", RichLog).write(
                f"\n[red]Process exited with code {returncode}.[/red]"
                "  Press  [bold]b[/bold]  to go back."
            )
        # Enable the back binding now that the pull is done
        self._enable_back()

    def _on_error(self, msg: str) -> None:
        self._done = True
        self.query_one("#log-panel", RichLog).write(f"\n[red]Error: {msg}[/red]")
        self._set_status("Error — press  b  to go back")
        self._enable_back()

    def _refresh_metric_list(self) -> None:
        self.query_one("#metric-list", Static).update(self._render_metrics())

    def _set_status(self, text: str) -> None:
        self.query_one("#status-label", Static).update(text)

    def _enable_back(self) -> None:
        """Swap the Back binding from hidden to visible once the pull is done."""
        try:
            self.BINDINGS = [
                Binding("b", "back", "Back", show=True),
                Binding("q", "quit", "Quit", show=True),
            ]
            self.refresh_bindings()
        except Exception:
            pass

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_metrics(self) -> str:
        lines: list[str] = []
        for m in _METRICS:
            state = self._metric_states[m]
            label = _LABEL.get(m, m)
            if state == "done":
                lines.append(f"[green]✓[/] {label}")
            elif state == "fail":
                lines.append(f"[red]✗[/] {label}")
            else:
                lines.append(f"[dim]○  {label}[/]")
        return "\n".join(lines)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_back(self) -> None:
        if self._done:
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
