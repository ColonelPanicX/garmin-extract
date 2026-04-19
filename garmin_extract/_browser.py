"""Browser detection — finds the best available Chromium browser on Windows."""

from __future__ import annotations

import os
from pathlib import Path


def detect_windows_browser() -> str | None:
    """Return the path to the first available Chromium browser on Windows.

    Priority: Chrome → Brave → Edge. Returns None if none are found.
    Only meaningful on Windows; always returns None on other platforms.
    """
    prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    prog_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        # Chrome
        Path(prog) / "Google/Chrome/Application/chrome.exe",
        Path(prog_x86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Google/Chrome/Application/chrome.exe",
        # Brave
        Path(prog) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        # Edge — guaranteed fallback on any Windows 10/11 machine
        Path(prog_x86) / "Microsoft/Edge/Application/msedge.exe",
        Path(prog) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None
