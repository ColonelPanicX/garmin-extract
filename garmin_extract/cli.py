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
    # Dumb / missing terminal
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
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

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
