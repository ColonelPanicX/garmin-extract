"""Xvfb detection and install helpers — shared across menu, TUI setup, and CLI.

The "truly headless" check is cached at first call so that later callers still
see the original state after Xvfb has exported DISPLAY into the environment.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

_OS_RELEASE = Path("/etc/os-release")
_truly_headless: bool | None = None


def is_installed() -> bool:
    return shutil.which("Xvfb") is not None


def is_truly_headless() -> bool:
    """True when we started on Linux with no $DISPLAY — cached for the process lifetime."""
    global _truly_headless
    if _truly_headless is None:
        _truly_headless = platform.system() == "Linux" and not os.environ.get("DISPLAY")
    return _truly_headless


def detect_install_cmd() -> tuple[list[str], str]:
    """Return (argv, human-readable string) for installing Xvfb on this distro."""
    ids: set[str] = set()
    if _OS_RELEASE.exists():
        for line in _OS_RELEASE.read_text().splitlines():
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"')
            if k == "ID":
                ids.add(v)
            elif k == "ID_LIKE":
                ids.update(v.split())

    if ids & {"debian", "ubuntu"}:
        argv = ["sudo", "apt-get", "install", "-y", "xvfb"]
    elif ids & {"fedora", "rhel", "centos"}:
        argv = ["sudo", "dnf", "install", "-y", "xorg-x11-server-Xvfb"]
    elif ids & {"arch"}:
        argv = ["sudo", "pacman", "-S", "--noconfirm", "xorg-server-xvfb"]
    elif ids & {"alpine"}:
        argv = ["sudo", "apk", "add", "xvfb"]
    else:
        argv = ["sudo", "apt-get", "install", "-y", "xvfb"]
    return argv, " ".join(argv)


def install() -> tuple[bool, str]:
    """Run the detected install command. Returns (ok, detail)."""
    argv, human = detect_install_cmd()
    try:
        r = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return False, f"Package manager not found: {exc}"
    if r.returncode == 0 and is_installed():
        return True, "Installed"
    detail = (r.stderr or r.stdout or "").strip().splitlines()
    last = detail[-1] if detail else f"exit {r.returncode}"
    return False, f"{human} failed — {last}"
