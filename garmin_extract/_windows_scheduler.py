"""Windows Task Scheduler integration via the `schtasks` CLI.

This module manages a single daily scheduled task named `TASK_NAME` that
runs `garmin-extract --pull` at a user-chosen time. Supports optional
--push-drive / --push-sheets flags for combined pull + export.

All functions return (ok, detail) tuples. None of them raise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "garmin-extract-daily"


def _build_command(push_drive: bool, push_sheets: bool) -> str:
    """Return the command string that Task Scheduler will run.

    Frozen build: `"C:\\path\\to\\garmin-extract.exe" --pull [...]`
    Source mode: `"C:\\path\\to\\venv\\Scripts\\python.exe" -m garmin_extract --pull [...]`
    """
    exe = str(Path(sys.executable).resolve())
    parts = [f'"{exe}"']
    if not getattr(sys, "frozen", False):
        parts += ["-m", "garmin_extract"]
    parts.append("--pull")
    if push_drive:
        parts.append("--push-drive")
    if push_sheets:
        parts.append("--push-sheets")
    return " ".join(parts)


def get_task_status() -> dict:
    """Return the current state of the scheduled task.

    Returns a dict with keys:
      - installed: bool
      - next_run_time: str | None  (raw from schtasks)
      - start_time: str | None     (HH:MM from Start Time field)
      - task_to_run: str | None    (the command line)
      - raw: str                   (full schtasks output for debugging)
    """
    result = {
        "installed": False,
        "next_run_time": None,
        "start_time": None,
        "task_to_run": None,
        "raw": "",
    }
    try:
        proc = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return result

    result["raw"] = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return result

    result["installed"] = True
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "Next Run Time":
            result["next_run_time"] = value
        elif key == "Start Time":
            result["start_time"] = value
        elif key == "Task To Run":
            result["task_to_run"] = value
    return result


def create_or_update_task(
    hour: int, minute: int, push_drive: bool, push_sheets: bool
) -> tuple[bool, str]:
    """Create or overwrite the daily scheduled task.

    `hour` 0-23, `minute` 0-59. Runs daily at that local time.
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return False, f"Invalid time: {hour:02d}:{minute:02d}"

    cmd = [
        "schtasks",
        "/create",
        "/tn",
        TASK_NAME,
        "/tr",
        _build_command(push_drive, push_sheets),
        "/sc",
        "daily",
        "/st",
        f"{hour:02d}:{minute:02d}",
        "/f",  # force overwrite if it already exists
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "schtasks not found — are you on Windows?"

    if proc.returncode == 0:
        return True, f"Scheduled daily at {hour:02d}:{minute:02d}"
    return False, (proc.stderr or proc.stdout).strip() or f"schtasks exit {proc.returncode}"


def delete_task() -> tuple[bool, str]:
    """Remove the scheduled task. No-op if not installed."""
    try:
        proc = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "schtasks not found — are you on Windows?"

    if proc.returncode == 0:
        return True, "Scheduled task removed"
    # `schtasks /delete` exits non-zero if the task doesn't exist — treat as success
    combined = (proc.stderr + proc.stdout).lower()
    if "cannot find" in combined or "does not exist" in combined:
        return True, "No scheduled task to remove"
    return False, (proc.stderr or proc.stdout).strip() or f"schtasks exit {proc.returncode}"


def parse_flags_from_command(cmd: str) -> tuple[bool, bool]:
    """Given a stored `task_to_run` string, return (push_drive, push_sheets)."""
    lowered = cmd.lower()
    return "--push-drive" in lowered, "--push-sheets" in lowered
