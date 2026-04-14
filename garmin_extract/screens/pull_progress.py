"""Pull progress screen — live pull display with dynamic metric parsing."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, ProgressBar, RichLog, Static

ROOT = Path(__file__).parent.parent.parent
MFA_FILE = ROOT / ".mfa_code"


# ── MFA modal ─────────────────────────────────────────────────────────────────


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


# ── day state (multi-day mode) ────────────────────────────────────────────────


@dataclass
class _DayState:
    date_str: str
    total: int = 0
    done: int = 0
    failed: int = 0
    status: str = "pending"  # pending | active | done | skipped


# ── main screen ───────────────────────────────────────────────────────────────


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

        # Determine display mode
        if days > 1:
            self._mode = "day"
            self._day_states: list[_DayState] = self._init_day_states()
            self._current_day_index: int = -1
            self._metrics_per_day: int = 0
        elif days == 1:
            self._mode = "metric"
            self._live_metrics: list[tuple[str, str]] = []  # (name, "done"|"fail")
            self._day_total: int = 0
            self._day_done: int = 0
        else:
            self._mode = "simple"

        self._overall_done: int = 0
        self._overall_total: int = max(days, 1)  # refined once first day count arrives

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="progress-layout"):
            yield RichLog(id="log-panel", highlight=True, markup=True, wrap=True)
            with Vertical(id="metric-panel"):
                yield Static(self._label, id="metric-header")
                yield Static("", id="metric-subheader")
                yield Static(self._initial_panel_body(), id="metric-list")
        with Vertical(id="status-bar"):
            yield ProgressBar(
                total=self._overall_total,
                id="progress-bar",
                show_eta=False,
            )
            yield Static("Starting...", id="status-label")
        yield Footer()

    def on_mount(self) -> None:
        cmd = self._build_cmd()
        self.run_worker(lambda: self._do_pull(cmd), thread=True, name="puller")

    # ── initial right-panel content ───────────────────────────────────────────

    def _initial_panel_body(self) -> str:
        if self._mode == "day":
            return self._render_day_list()
        if self._mode == "metric":
            return "[dim]Waiting for first metric...[/]"
        return "[dim]Starting...[/]"

    # ── command builder ────────────────────────────────────────────────────────

    def _build_cmd(self) -> list[str]:
        if self._rebuild_only:
            return [sys.executable, "-u", str(ROOT / "reports" / "build_garmin_csvs.py")]
        if self._zip_path:
            return [
                sys.executable,
                "-u",
                str(ROOT / "pullers" / "garmin_import_export.py"),
                "--zip",
                self._zip_path,
            ]
        cmd = [
            sys.executable,
            "-u",
            str(ROOT / "pullers" / "garmin.py"),
            "--date",
            self._start_date,
            "--days",
            str(self._days),
        ]
        if self._no_skip:
            cmd.append("--no-skip")
        return cmd

    # ── pre-compute day state list ────────────────────────────────────────────

    def _init_day_states(self) -> list[_DayState]:
        states: list[_DayState] = []
        try:
            start = date.fromisoformat(self._start_date)
            for i in range(self._days):
                states.append(_DayState((start + timedelta(days=i)).isoformat()))
        except ValueError:
            pass
        return states

    # ── worker (thread) ────────────────────────────────────────────────────────

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
                self.app.call_from_thread(self._on_line, line)
            proc.wait()
            self.app.call_from_thread(self._on_done, proc.returncode)
        except Exception as exc:
            self.app.call_from_thread(self._on_error, str(exc))

    # ── line parser (main thread) ──────────────────────────────────────────────

    def _on_line(self, line: str) -> None:
        self.query_one("#log-panel", RichLog).write(line)
        stripped = line.strip()

        # ── "[2025-04-06] Pulling N metrics..." ──
        if stripped.startswith("[") and "] Pulling " in stripped and "metrics" in stripped:
            self._handle_day_start(stripped)
            return

        # ── "[2025-04-06] Already pulled — skipping" ──
        if "Already pulled" in stripped and "skipping" in stripped:
            self._handle_day_skipped(stripped)
            return

        # ── "    ✓/✗  metric_name" ──
        if stripped.startswith("✓") or stripped.startswith("✗"):
            self._handle_metric_line(stripped)
            return

        # ── file-based MFA prompt ──
        if "Run: echo YOUR_CODE" in stripped and not self._mfa_shown:
            self._mfa_shown = True
            self.app.push_screen(_MfaModal())

    def _handle_day_start(self, stripped: str) -> None:
        try:
            date_str = stripped[1 : stripped.index("]")]
            # Parse metric count from "Pulling N metrics..."
            parts = stripped.split()
            count_idx = next((i for i, p in enumerate(parts) if p == "Pulling"), -1)
            n_metrics = int(parts[count_idx + 1]) if count_idx >= 0 else 0
        except (ValueError, IndexError):
            return

        if self._mode == "day":
            # Find matching day state
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
                # First real count — set progress bar total
                self._metrics_per_day = n_metrics
                self._overall_total = self._days * n_metrics
                self.query_one("#progress-bar", ProgressBar).total = self._overall_total

            self._refresh_day_list()
            self._set_status(f"Day {idx + 1} of {self._days}  ·  {date_str}")

        elif self._mode == "metric":
            self._day_total = n_metrics
            self._day_done = 0
            self._live_metrics = []
            if n_metrics > 0:
                self.query_one("#progress-bar", ProgressBar).total = n_metrics
            self.query_one("#metric-subheader", Static).update(f"[dim]{date_str}[/]")
            self._refresh_metric_list()
            self._set_status(f"Pulling {date_str}...")

    def _handle_day_skipped(self, stripped: str) -> None:
        try:
            date_str = stripped[1 : stripped.index("]")]
        except ValueError:
            return

        if self._mode == "day":
            idx = next(
                (i for i, s in enumerate(self._day_states) if s.date_str == date_str),
                -1,
            )
            if idx >= 0:
                self._day_states[idx].status = "skipped"
                # Advance progress by one day's worth of metrics (or 1 if unknown)
                advance = self._metrics_per_day if self._metrics_per_day else 1
                self._overall_done += advance
                self.query_one("#progress-bar", ProgressBar).advance(advance)
                self._refresh_day_list()
                self._set_status(f"Skipped {date_str}  (already pulled)")

    def _handle_metric_line(self, stripped: str) -> None:
        parts = stripped.split()
        if not parts:
            return
        metric_name = parts[-1]
        is_ok = stripped.startswith("✓")
        state = "done" if is_ok else "fail"

        if self._mode == "metric":
            self._live_metrics.append((metric_name, state))
            self._day_done += 1
            self.query_one("#progress-bar", ProgressBar).advance(1)
            self._refresh_metric_list()
            self._set_status(f"{self._day_done} / {self._day_total or '?'} metrics")

        elif self._mode == "day" and self._current_day_index >= 0:
            ds = self._day_states[self._current_day_index]
            if is_ok:
                ds.done += 1
            else:
                ds.failed += 1
            self._overall_done += 1
            self.query_one("#progress-bar", ProgressBar).advance(1)

            # Day complete when done + failed == total
            if ds.total > 0 and (ds.done + ds.failed) >= ds.total:
                ds.status = "done"

            self._refresh_day_list()
            self._set_status(
                f"Day {self._current_day_index + 1} of {self._days}"
                f"  ·  {ds.done + ds.failed}/{ds.total or '?'} metrics"
            )

    # ── completion / error ─────────────────────────────────────────────────────

    def _on_done(self, returncode: int) -> None:
        self._done = True
        log = self.query_one("#log-panel", RichLog)
        if returncode == 0:
            self._set_status("Complete ✓  —  press  b  to go back")
            log.write("\n[green]Done.[/green]  Press  [bold]b[/bold]  to go back.")
        else:
            self._set_status(f"Finished with errors (exit {returncode})  —  press  b  to go back")
            log.write(
                f"\n[red]Process exited with code {returncode}.[/red]"
                "  Press  [bold]b[/bold]  to go back."
            )
        self._enable_back()

    def _on_error(self, msg: str) -> None:
        self._done = True
        self.query_one("#log-panel", RichLog).write(f"\n[red]Error: {msg}[/red]")
        self._set_status("Error  —  press  b  to go back")
        self._enable_back()

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_day_list(self) -> str:
        lines: list[str] = []
        for ds in self._day_states:
            if ds.status == "done":
                count = f"({ds.done}/{ds.total})" if ds.total else ""
                failed = f"  [red]{ds.failed} failed[/]" if ds.failed else ""
                lines.append(f"[green]✓[/] {ds.date_str}  [dim]{count}[/]{failed}")
            elif ds.status == "active":
                count = f"{ds.done + ds.failed}/{ds.total}" if ds.total else "…"
                lines.append(f"[yellow]●[/] {ds.date_str}  [dim]({count})[/]")
            elif ds.status == "skipped":
                lines.append(f"[dim]↷ {ds.date_str}  (skipped)[/]")
            else:
                lines.append(f"[dim]○  {ds.date_str}[/]")
        return "\n".join(lines)

    def _render_metric_list(self) -> str:
        if not self._live_metrics:
            return "[dim]Waiting for first metric...[/]"
        lines: list[str] = []
        for name, state in self._live_metrics:
            if state == "done":
                lines.append(f"[green]✓[/] {name}")
            else:
                lines.append(f"[red]✗[/] {name}")
        return "\n".join(lines)

    def _refresh_day_list(self) -> None:
        self.query_one("#metric-list", Static).update(self._render_day_list())

    def _refresh_metric_list(self) -> None:
        self.query_one("#metric-list", Static).update(self._render_metric_list())

    def _set_status(self, text: str) -> None:
        self.query_one("#status-label", Static).update(text)

    def _enable_back(self) -> None:
        try:
            self.BINDINGS = [
                Binding("b", "back", "Back", show=True),
                Binding("q", "quit", "Quit", show=True),
            ]
            self.refresh_bindings()
        except Exception:
            pass

    # ── actions ───────────────────────────────────────────────────────────────

    def action_back(self) -> None:
        if self._done:
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
