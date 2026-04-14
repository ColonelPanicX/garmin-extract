#!/usr/bin/env python3
"""
Backward-compatibility shim.

The tool now lives in the garmin_extract/ package.
Preferred entry points:
  python -m garmin_extract          # TUI (default)
  python -m garmin_extract --no-tui # print menu
  garmin-extract                    # after: uv pip install -e .
"""

from garmin_extract.cli import main

if __name__ == "__main__":
    main()
