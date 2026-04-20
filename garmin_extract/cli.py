"""
CLI entry point for garmin-extract.

Parses arguments and routes to either the Textual TUI (default) or the
print menu (--no-tui / headless fallback). All interactive flows live
in those two layers; this module only handles dispatch.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from garmin_extract import __version__


def _is_gui_available() -> bool:
    """Return True if running on Windows with PySide6 installed."""
    if sys.platform != "win32":
        return False
    try:
        import PySide6  # noqa: F401

        return True
    except ImportError:
        return False


def _is_tui_capable() -> bool:
    """Return True if the current environment can support a Textual TUI."""
    # Explicit opt-outs
    if os.environ.get("CI") or os.environ.get("GARMIN_NO_TUI"):
        return False
    # TERM is a Unix concept — Windows PowerShell/cmd don't set it, but Textual works fine there
    if sys.platform != "win32":
        term = os.environ.get("TERM", "")
        if term in ("dumb", ""):
            return False
    # No TTY (e.g. piped output, cron)
    if not sys.stdout.isatty():
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="garmin-extract",
        description="Automated Garmin Connect data pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run without flags to launch the interactive interface.\n"
            "Use --no-tui for headless, CI, or cron environments."
        ),
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Use the print menu instead of the TUI",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Skip the PySide6 GUI on Windows — use the TUI or print menu",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making changes (print menu only — Phase 2 for TUI)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase verbosity (stackable: -vv)",
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help=(
            "Pull yesterday's data, rebuild CSVs, and optionally push to "
            "Drive/Sheets. Non-interactive — safe for cron and Task Scheduler."
        ),
    )
    parser.add_argument(
        "--push-drive",
        action="store_true",
        help="Upload CSV reports to Google Drive (non-interactive, safe for cron)",
    )
    parser.add_argument(
        "--push-sheets",
        action="store_true",
        help="Sync CSV reports to Google Sheets (non-interactive, safe for cron)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _run_export(push_drive: bool, push_sheets: bool) -> None:
    """Run Drive/Sheets export non-interactively. Exits with 0 on success, 1 on any failure."""
    from garmin_extract._google_drive import sync_to_sheets, upload_csvs_to_drive

    exit_code = 0

    if push_drive:
        result = upload_csvs_to_drive()
        if result["ok"]:
            names = ", ".join(f["name"] for f in result["files"])
            print(f"Drive: uploaded {names} → {result['folder_link']}")
        else:
            print(f"Drive error: {result['error']}", file=sys.stderr)
            exit_code = 1

    if push_sheets:
        result = sync_to_sheets()
        if result["ok"]:
            print(f"Sheets: {result['sheet_url']}")
        else:
            print(f"Sheets error: {result['error']}", file=sys.stderr)
            exit_code = 1

    sys.exit(exit_code)


def _run_scheduled_pull(push_drive: bool, push_sheets: bool) -> None:
    """Run the full scheduled-pull sequence: pull yesterday, build CSVs, optional export.

    Mirrors scripts/pull-garmin.sh for Windows Task Scheduler. Exits 0 if every
    stage succeeds, 1 on any failure.
    """
    import subprocess

    from garmin_extract._paths import app_root, bundle_root

    scripts_root = bundle_root()
    cwd = str(app_root())
    puller = str(scripts_root / "pullers" / "garmin.py")
    csv_builder = str(scripts_root / "reports" / "build_garmin_csvs.py")

    print(f"[pull] {datetime.now().isoformat(timespec='seconds')}", flush=True)
    pull = subprocess.run([sys.executable, "-u", puller], cwd=cwd)
    if pull.returncode != 0:
        print(f"Pull failed (exit {pull.returncode})", file=sys.stderr)
        sys.exit(1)

    csv = subprocess.run([sys.executable, "-u", csv_builder], cwd=cwd)
    if csv.returncode != 0:
        print(f"CSV build failed (exit {csv.returncode})", file=sys.stderr)
        sys.exit(1)

    if push_drive or push_sheets:
        _run_export(push_drive=push_drive, push_sheets=push_sheets)
        return  # _run_export calls sys.exit

    sys.exit(0)


def main() -> None:
    args = build_parser().parse_args()

    if args.pull:
        _run_scheduled_pull(push_drive=args.push_drive, push_sheets=args.push_sheets)
        return  # _run_scheduled_pull calls sys.exit

    if args.push_drive or args.push_sheets:
        _run_export(push_drive=args.push_drive, push_sheets=args.push_sheets)
        return  # _run_export calls sys.exit; this is a safety return

    if args.no_tui:
        from garmin_extract.menu import main as run_menu

        run_menu(dry_run=args.dry_run, verbose=args.verbose)
    elif not args.no_gui and _is_gui_available():
        from garmin_extract.gui.app import run

        run(dry_run=args.dry_run, verbose=args.verbose)
    elif _is_tui_capable():
        from garmin_extract.app import GarminExtractApp

        GarminExtractApp(dry_run=args.dry_run, verbose=args.verbose).run()
    else:
        from garmin_extract.menu import main as run_menu

        run_menu(dry_run=args.dry_run, verbose=args.verbose)
