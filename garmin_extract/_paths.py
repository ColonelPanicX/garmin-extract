"""Path helpers — resolve app root correctly for both dev installs and PyInstaller bundles.

In a normal install, files like `.env`, `.mfa_code`, `pullers/`, `reports/` live at
the project root (the directory containing `pyproject.toml`). Computing that with
`Path(__file__).parent.parent` works fine.

Inside a PyInstaller onedir bundle, Python modules live in `dist/garmin-extract/_internal/`
while user-facing files should live alongside `garmin-extract.exe`. `__file__` points
inside `_internal/`, so the parent-parent trick resolves to the wrong directory.

`app_root()` handles both cases by checking `sys.frozen`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Return the directory where user-facing files (config, data, scripts) live.

    - Dev install: project root (containing pyproject.toml)
    - Frozen (PyInstaller onedir): the directory containing the .exe
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # Dev install: this file is at <root>/garmin_extract/_paths.py
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Return the directory containing bundled data files (pullers/, reports/, scripts/).

    - Dev install: same as app_root() — the project root
    - Frozen: `sys._MEIPASS` (PyInstaller's _internal directory) where data files land
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent / "_internal"
    return Path(__file__).resolve().parent.parent
