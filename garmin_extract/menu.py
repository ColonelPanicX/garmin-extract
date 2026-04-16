"""
Print menu for garmin-extract.

The Layer 1 (print-menu) interface. Launched via --no-tui or whenever
the environment cannot support the Textual TUI (headless, CI, cron).

All interactive flows live here. The engine (pullers/, reports/) is
invoked via subprocess so this module stays UI-only.

TODO (Phase 2): thread dry_run through all action functions.
"""

from __future__ import annotations

import getpass
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

# garmin_extract/menu.py → parent = garmin_extract/ → parent = project root
ROOT = Path(__file__).parent.parent
ENV = ROOT / ".env"
PYTHON = sys.executable

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Navigation signals
# ─────────────────────────────────────────────────────────────────────────────


class BackSignal(Exception):
    """User pressed 'b' — go back one level."""


class ExitToMainSignal(Exception):
    """User pressed 'x' — return to main menu."""


class QuitSignal(Exception):
    """User pressed 'q' — exit the application."""


def prompt_with_navigation(prompt_text: str) -> str:
    """Wrap any input prompt; raise navigation signals on b / x / q."""
    response = input(prompt_text).strip()
    lower = response.lower()
    if lower == "b":
        raise BackSignal
    if lower == "x":
        raise ExitToMainSignal
    if lower == "q":
        raise QuitSignal
    return response


def _continue(prompt: str = "\n  Press Enter to continue...") -> None:
    """Pause with a continue prompt. Navigation signals propagate normally."""
    prompt_with_navigation(prompt)


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────


def hr(char: str = "─", width: int = 52) -> None:
    print(char * width)


def header(title: str) -> None:
    content = f"  {title}  "
    width = max(50, len(content))
    padding = width - len(content)
    print()
    console.print(f"╔{'═' * width}╗")
    console.print(f"║[bold]{content}{' ' * padding}[/]║")
    console.print(f"╚{'═' * width}╝")
    print()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd)


def load_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def save_env(vals: dict[str, str]) -> None:
    lines = [
        "# Garmin Connect credentials",
        f"GARMIN_EMAIL={vals.get('GARMIN_EMAIL', '')}",
        f"GARMIN_PASSWORD={vals.get('GARMIN_PASSWORD', '')}",
    ]
    ENV.write_text("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Prerequisite helpers
# ─────────────────────────────────────────────────────────────────────────────


def _find_chrome() -> tuple[bool, str | None]:
    system = platform.system()

    # Windows: chrome.exe --version launches Chrome instead of printing version.
    # Check standard install paths and read VersionInfo via PowerShell.
    if system == "Windows":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in paths:
            if not Path(path).is_file():
                continue
            try:
                ps = f"(Get-Item '{path}').VersionInfo.ProductVersion"
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = r.stdout.strip() if r.returncode == 0 else ""
                label = f"Google Chrome {version}" if version else "Google Chrome"
                return True, label
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                return True, "Google Chrome (version unknown)"
        return False, None

    # macOS / Linux: chrome --version prints version and exits
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "google-chrome",
        ]
    else:
        candidates = ["google-chrome-stable", "google-chrome", "chromium-browser", "chromium"]

    for cmd in candidates:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return True, r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return False, None


def _find_xvfb() -> bool:
    try:
        r = subprocess.run(["which", "Xvfb"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _missing_packages() -> list[str]:
    checks = [
        ("seleniumbase", "seleniumbase"),
        ("dotenv", "python-dotenv"),
        ("google.oauth2", "google-auth"),
        ("googleapiclient", "google-api-python-client"),
        ("requests_oauthlib", "requests-oauthlib"),
    ]
    missing = []
    for mod, pkg in checks:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return missing


# ─────────────────────────────────────────────────────────────────────────────
# 1. Setup wizard
# ─────────────────────────────────────────────────────────────────────────────


def check_prerequisites() -> None:  # noqa: C901
    header("Setup Wizard")
    system = platform.system()
    issues: list[str] = []

    # ── Step 1: Python ───────────────────────────────────────────────────────
    print("Step 1 of 5 — Python version")
    print()
    v = sys.version_info
    ok = v >= (3, 12)

    if ok:
        console.print(f"  [green]✓[/]  Python {v.major}.{v.minor}.{v.micro}")
    else:
        console.print(
            f"  [red]✗[/]  Python {v.major}.{v.minor}.{v.micro}"
            " — version 3.12 or newer is required."
        )
        print()
        print("  Python is the programming language this tool is written in.")
        print("  Version 3.12 added features this code depends on.")
        print()
        if system == "Windows":
            print("  Download the latest Python from: https://www.python.org/downloads/")
            print()
            print("  During installation, make sure to check:")
            print('  ☑  "Add Python to PATH"')
            print()
            print("  After installing, close this window, open a new terminal, and")
            print("  run this script again.")
        elif system == "Darwin":
            print("  Install with Homebrew:  brew install python@3.12")
            print("  Or download from:       https://www.python.org/downloads/")
        else:
            print("  Install with:  sudo apt install python3.12")
        print()
        print("  Cannot continue until Python 3.12+ is available.")
        issues.append("Python 3.12+")
        _continue("\n  Press Enter to return to the menu...")
        return

    # ── Step 2: Google Chrome ────────────────────────────────────────────────
    print()
    hr()
    print()
    print("Step 2 of 5 — Google Chrome")
    print()
    found, version = _find_chrome()

    if found:
        console.print(f"  [green]✓[/]  {version}")
    else:
        console.print("  [red]✗[/]  Chrome not found.")
        print()
        print("  Why Chrome is required:")
        print()
        print("  Garmin's login page is protected by Cloudflare, a security")
        print("  service that blocks any automated script trying to log in.")
        print("  The only way through is to use a real browser. This tool")
        print("  runs Chrome invisibly in the background — Garmin sees a")
        print("  normal browser session and lets it through.")
        print()

        if system == "Linux":
            print("  Chrome is not installed. We can install it now.")
            print("  This requires administrator (sudo) access and will run:")
            print()
            print("    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \\")
            print("        | sudo apt-key add -")
            print(
                '    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \\'
            )
            print("        | sudo tee /etc/apt/sources.list.d/google-chrome.list")
            print("    sudo apt-get update")
            print("    sudo apt-get install -y google-chrome-stable")
            print("    sudo apt-get --fix-broken install -y")
            print()
            go = prompt_with_navigation("  Install Chrome now? [Y/n]: ")
            if go.lower() != "n":
                print()
                cmds = [
                    "wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -",  # noqa: E501
                    'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" '
                    "| sudo tee /etc/apt/sources.list.d/google-chrome.list",
                    "sudo apt-get update",
                    "sudo apt-get install -y google-chrome-stable",
                    "sudo apt-get --fix-broken install -y",
                ]
                for cmd in cmds:
                    r = subprocess.run(cmd, shell=True)
                    if r.returncode != 0:
                        break
                found, version = _find_chrome()
                if found:
                    console.print(f"\n  [green]✓[/]  Chrome installed: {version}")
                else:
                    console.print(
                        "\n  [red]✗[/]  Installation may not have completed."
                        " Check the output above."
                    )
                    issues.append("Chrome")
            else:
                print()
                print("  Skipped. Install Chrome and re-run option 1.")
                issues.append("Chrome")

        elif system == "Darwin":
            print("  To install Chrome on macOS:")
            print()
            print("    1. Open a web browser and go to: https://www.google.com/chrome/")
            print("    2. Click 'Download Chrome'")
            print("    3. Open the downloaded .dmg file")
            print("    4. Drag Chrome into your Applications folder")
            print("    5. Eject the disk image")
            print()
            print("  After installing Chrome, re-run this setup (option 1).")
            issues.append("Chrome")

        else:  # Windows
            print("  To install Chrome on Windows:")
            print()
            print("    1. Open a web browser and go to: https://www.google.com/chrome/")
            print("    2. Click 'Download Chrome'")
            print("    3. Run the downloaded installer")
            print("    4. Follow the on-screen steps")
            print()
            print("  After installing Chrome, re-run this setup (option 1).")
            issues.append("Chrome")

    # ── Step 3: Xvfb (headless Linux only) ──────────────────────────────────
    print()
    hr()
    print()
    print("Step 3 of 5 — Virtual display (Xvfb)")
    print()

    needs_xvfb = system == "Linux" and not os.environ.get("DISPLAY")

    if not needs_xvfb:
        if system == "Linux":
            console.print("  [green]✓[/]  Not needed — a display is already available.")
        else:
            console.print(f"  [green]✓[/]  Not needed on {system}.")
    else:
        xvfb_ok = _find_xvfb()
        if xvfb_ok:
            console.print("  [green]✓[/]  Xvfb is installed.")
        else:
            console.print("  [red]✗[/]  Xvfb not found.")
            print()
            print("  Your system has no monitor or desktop environment (it's a")
            print("  headless server). Chrome needs a screen to run, even when")
            print("  it's running invisibly in the background.")
            print()
            print("  Xvfb (X Virtual Framebuffer) creates a fake, hidden screen")
            print("  so Chrome has somewhere to render without a real display.")
            print()
            print("  We can install it now:")
            print("    sudo apt-get install -y xvfb")
            print()
            go = prompt_with_navigation("  Install Xvfb now? [Y/n]: ")
            if go.lower() != "n":
                print()
                r = subprocess.run(["sudo", "apt-get", "install", "-y", "xvfb"])
                if r.returncode == 0 and _find_xvfb():
                    console.print("\n  [green]✓[/]  Xvfb installed.")
                else:
                    console.print("\n  [red]✗[/]  Installation may not have completed.")
                    issues.append("Xvfb")
            else:
                print()
                print("  Skipped. Install Xvfb and re-run option 1.")
                issues.append("Xvfb")

    # ── Step 4: Python packages ──────────────────────────────────────────────
    print()
    hr()
    print()
    print("Step 4 of 5 — Python packages")
    print()
    missing = _missing_packages()

    if not missing:
        console.print("  [green]✓[/]  All required packages are installed.")
    else:
        console.print(f"  [red]✗[/]  Missing: {', '.join(missing)}")
        print()
        print("  These are the libraries this tool depends on:")
        print()
        print("  · seleniumbase          — controls Chrome")
        print("  · python-dotenv         — reads your .env credentials file")
        print("  · google-auth           — handles Google sign-in for Gmail MFA")
        print("  · google-api-python-client — connects to Gmail")
        print("  · requests-oauthlib     — handles the Google authorization flow")
        print()
        print("  All packages are listed in requirements.txt and will be")
        print("  installed from the official Python package repository (PyPI).")
        print()
        go = prompt_with_navigation("  Install packages now? [Y/n]: ")
        if go.lower() != "n":
            print()
            r = subprocess.run(
                [PYTHON, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
            )
            missing = _missing_packages()
            if not missing:
                console.print("\n  [green]✓[/]  All packages installed.")
            else:
                console.print(f"\n  [red]✗[/]  Still missing after install: {', '.join(missing)}")
                print("  Check the output above for errors.")
                issues.append("Python packages")
        else:
            print()
            print("  Skipped. Run:  pip install -r requirements.txt")
            issues.append("Python packages")

    # ── Step 5: Garmin credentials ───────────────────────────────────────────
    print()
    hr()
    print()
    print("Step 5 of 5 — Garmin credentials")
    print()
    env = load_env()

    if env.get("GARMIN_EMAIL") and env.get("GARMIN_PASSWORD"):
        console.print(f"  [green]✓[/]  Credentials on file: {env['GARMIN_EMAIL']}")
    else:
        print("  Your Garmin Connect email and password are needed so the tool")
        print("  can log in to Garmin on your behalf.")
        print()
        print("  These are saved to a local file called .env in this directory.")
        print("  That file is excluded from version control and never shared.")
        print()
        email = prompt_with_navigation("  Garmin Connect email: ")
        if not email:
            print("\n  Skipped. Run option 2 to add credentials later.")
            issues.append("Garmin credentials")
        else:
            password = getpass.getpass("  Garmin Connect password: ")
            if not password:
                print("\n  Skipped. Run option 2 to add credentials later.")
                issues.append("Garmin credentials")
            else:
                env["GARMIN_EMAIL"] = email
                env["GARMIN_PASSWORD"] = password
                save_env(env)
                console.print("\n  [green]✓[/]  Saved to .env")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    hr()
    print()

    if not issues:
        print("  Setup complete.")
        print()
        print("  ─── What happens on your first pull ───────────────────────")
        print()
        print("  When you run option 4 (Pull Garmin data) for the first time,")
        print("  Chrome will open invisibly, navigate to Garmin Connect, and")
        print("  log in with your credentials.")
        print()
        print("  Garmin will send a 6-digit security code to your email.")
        print("  Two ways this gets handled:")
        print()
        print("  · Automatic (recommended): set up Gmail MFA via option 3.")
        print("    The tool reads the code from your inbox and submits it")
        print("    without any action from you.")
        print()
        print("  · Manual fallback: if Gmail MFA is not set up, the tool")
        print("    will print:  Run: echo YOUR_CODE > .mfa_code")
        print("    Open your email, find the code, and run that command")
        print("    in a second terminal window.")
        print()
        print("  After the first login, the browser session is saved and")
        print("  reused. You typically won't need to authenticate again for")
        print("  about 30 days.")
        print()
        print("  ─── Recommended next step ──────────────────────────────────")
        print()
        print("  Run option 3 to set up Gmail MFA so everything runs")
        print("  fully automatically — including from a scheduled cron job.")
    else:
        print(f"  {len(issues)} item(s) still need attention:")
        for item in issues:
            print(f"    · {item}")
        print()
        print("  Follow the instructions above, then re-run option 1.")

    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Configure Garmin credentials
# ─────────────────────────────────────────────────────────────────────────────


def configure_credentials() -> None:
    header("Configure Garmin Credentials")
    print("  Stored in .env (gitignored — never committed).\n")
    env = load_env()

    cur_email = env.get("GARMIN_EMAIL", "")
    cur_pass = env.get("GARMIN_PASSWORD", "")

    if cur_email:
        print(f"  Current email:    {cur_email}")
        new_email = prompt_with_navigation("  New email         (Enter to keep): ")
        email = new_email or cur_email
    else:
        email = prompt_with_navigation("  Garmin email: ")

    if cur_pass:
        print(f"  Current password: {'*' * min(len(cur_pass), 12)}")
        new_pass = getpass.getpass("  New password      (Enter to keep): ")
        password = new_pass or cur_pass
    else:
        password = getpass.getpass("  Garmin password: ")

    if not email or not password:
        print("\n  No changes made.")
        _continue()
        return

    env["GARMIN_EMAIL"] = email
    env["GARMIN_PASSWORD"] = password
    save_env(env)
    console.print("\n  [green]✓[/]  Saved to .env")
    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Gmail MFA setup
# ─────────────────────────────────────────────────────────────────────────────


def setup_gmail_mfa() -> None:
    header("Gmail MFA Automation Setup")
    print("  When Garmin requires a security code (~every 30 days), this module")
    print("  polls your Gmail inbox and submits it automatically. Without it,")
    print("  you'll be prompted to paste the code manually.\n")
    hr()

    creds_file = ROOT / "google_credentials.json"
    if not creds_file.exists():
        print()
        console.print("  [red]✗[/]  google_credentials.json not found.\n")
        print("  To create it:")
        print("    1. Go to console.cloud.google.com")
        print("    2. Create a project")
        print("    3. Enable the Gmail API")
        print("    4. Credentials → Create → OAuth 2.0 Client ID → Desktop app")
        print("    5. Download JSON → save as google_credentials.json in this directory")
        print()
        print("  Then run this option again to complete authorization.")
        _continue()
        return

    print("  google_credentials.json found. Starting authorization flow...\n")
    result = subprocess.run([PYTHON, str(ROOT / "scripts" / "setup_gmail_auth.py")])
    if result.returncode == 0:
        console.print("\n  [green]✓[/]  Gmail MFA automation is now active.")
    else:
        console.print("\n  [red]✗[/]  Setup did not complete — check the output above.")
    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# Pull helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> str | None:
    """Accept YYYY-MM-DD, MM/DD/YYYY, MM/DD/YY, MM-DD-YYYY, MM-DD-YY."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _run_pull(start_date: str, days: int, no_skip: bool = False) -> None:
    """Run the Garmin puller, then immediately rebuild CSVs."""
    cmd = [
        PYTHON,
        str(ROOT / "pullers" / "garmin.py"),
        "--date",
        start_date,
        "--days",
        str(days),
    ]
    if no_skip:
        cmd.append("--no-skip")

    subprocess.run(cmd)

    print()
    print("  Building CSV reports...")
    subprocess.run([PYTHON, str(ROOT / "reports" / "build_garmin_csvs.py")])
    print()
    console.print("  [green]✓[/]  Done.")
    print("  · reports/garmin_daily.csv")
    print("  · reports/garmin_activities.csv")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pull data — sub-menu actions
# ─────────────────────────────────────────────────────────────────────────────


def _pull_yesterday() -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print(f"\n  Pulling {yesterday}...\n")
    _run_pull(yesterday, 1)
    _continue()


def _pull_last_n(n: int, label: str) -> None:
    start = (date.today() - timedelta(days=n)).isoformat()
    print(f"\n  Pulling {label} ({start} → yesterday)...\n")
    _run_pull(start, n)
    _continue()


def _pull_custom() -> None:
    header("Custom Date Pull")
    print("  Accepted date formats: YYYY-MM-DD  |  MM/DD/YYYY  |  MM/DD/YY\n")

    raw = prompt_with_navigation("  Start date: ")
    if not raw:
        return
    start = _parse_date(raw)
    if not start:
        print(f"\n  Could not parse '{raw}' as a date. Try: 2025-04-07 or 04/07/2025")
        _continue()
        return

    days_in = prompt_with_navigation("  Number of days to pull [Enter for 1]: ")
    days = int(days_in) if days_in.isdigit() and int(days_in) > 0 else 1

    end = (datetime.strptime(start, "%Y-%m-%d").date() + timedelta(days=days - 1)).isoformat()
    range_label = start if days == 1 else f"{start} → {end}"
    print(f"\n  Pulling {days} day(s): {range_label}")

    reskip = prompt_with_navigation("  Re-pull dates that already have data? [y/N]: ")
    print()
    _run_pull(start, days, no_skip=(reskip.lower() == "y"))
    _continue()


def _pull_everything() -> None:
    header("Pull Full History")
    print("  Pulls every day from a start date through yesterday.")
    print("  Use this to build a complete data history via the live API.\n")
    print("  Each day takes ~15 seconds to pull.")
    print("  · 1 month  ≈  7 minutes")
    print("  · 6 months ≈  45 minutes")
    print("  · 1 year   ≈  90 minutes\n")
    print("  For very large history pulls, the Garmin bulk export (option 6)")
    print("  is faster — request it from Garmin and import the .zip.\n")
    print("  Accepted date formats: YYYY-MM-DD  |  MM/DD/YYYY  |  MM/DD/YY\n")

    raw = prompt_with_navigation("  Pull data starting from: ")
    if not raw:
        return
    start_str = _parse_date(raw)
    if not start_str:
        print(f"\n  Could not parse '{raw}'. Try: 2023-01-01 or 01/01/2023")
        _continue()
        return

    start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
    yesterday = date.today() - timedelta(days=1)
    days = (yesterday - start_dt).days + 1

    if days <= 0:
        print("\n  Start date must be before today.")
        _continue()
        return

    mins = days * 15 // 60
    if mins:
        time_est = f"~{mins // 60}h {mins % 60}m" if mins >= 60 else f"~{mins} min"
    else:
        time_est = "< 1 min"

    print(f"\n  {days} days  ({start_str} → {yesterday.isoformat()})")
    print(f"  Estimated time: {time_est}\n")

    go = prompt_with_navigation("  Continue? [y/N]: ")
    if go.lower() != "y":
        print("  Cancelled.")
        _continue()
        return

    reskip = prompt_with_navigation("  Skip dates that already have data? [Y/n]: ")
    no_skip = reskip.lower() == "n"
    print()
    _run_pull(start_str, days, no_skip=no_skip)
    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Import from Garmin bulk export
# ─────────────────────────────────────────────────────────────────────────────


def import_export() -> None:
    header("Import from Garmin Bulk Export")
    print("  The Garmin bulk export is the fastest way to load years of")
    print("  historical data. Request it at:")
    print("  Garmin Connect → Profile → Account → Your Garmin Data")
    print("  (The .zip file arrives within 24–48 hours.)\n")

    zip_path = prompt_with_navigation("  Path to export .zip: ").strip('"').strip("'")
    if not zip_path:
        print("  Cancelled.")
        _continue()
        return

    if not Path(zip_path).exists():
        print(f"\n  File not found: {zip_path}")
        _continue()
        return

    reskip = prompt_with_navigation("  Overwrite dates that already have data? [y/N]: ")
    cmd = [PYTHON, str(ROOT / "pullers" / "garmin_import_export.py"), zip_path]
    if reskip.lower() == "y":
        cmd.append("--no-skip")

    print()
    subprocess.run(cmd)

    print()
    print("  Building CSV reports...")
    subprocess.run([PYTHON, str(ROOT / "reports" / "build_garmin_csvs.py")])
    print()
    console.print("  [green]✓[/]  Done.")
    print("  · reports/garmin_daily.csv")
    print("  · reports/garmin_activities.csv")
    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Build CSV reports
# ─────────────────────────────────────────────────────────────────────────────


def build_csvs() -> None:
    header("Build CSV Reports")
    print("  Flattens all JSON data files into:")
    print("  · reports/garmin_daily.csv       — one row per day")
    print("  · reports/garmin_activities.csv  — one row per workout\n")

    since = prompt_with_navigation("  Include data from [Enter for all time, or YYYY-MM-DD]: ")
    cmd = [PYTHON, str(ROOT / "reports" / "build_garmin_csvs.py")]
    if since:
        cmd += ["--since", since]

    print()
    run(cmd)
    _continue()


# ─────────────────────────────────────────────────────────────────────────────
# Menu rendering
# ─────────────────────────────────────────────────────────────────────────────

MenuAction = Callable[[], None] | None
MenuOption = tuple[str, str, MenuAction]


def _first_run_notice() -> None:
    if not ENV.exists():
        header("garmin-extract")
        print("  Looks like your first run — .env not found.")
        print()
        print("  Start with option 1 (Initial Setup) to get everything")
        print("  installed and configured before pulling data.")
        _continue("\n  Press Enter to open the menu...")


def _submenu(title: str, options: list[MenuOption]) -> None:
    """Generic sub-menu loop. BackSignal from prompt exits; others propagate up."""
    keys: dict[str, Callable[[], None]] = {k: fn for k, label, fn in options if fn is not None}
    while True:
        header(title)
        for key, label, fn in options:
            if fn is None:
                print(f"  {label}")
            else:
                print(f"    {key}  {label}")
        print()
        hr()
        print("    b  Back    x  Main menu    q  Quit")
        hr()
        try:
            choice = prompt_with_navigation("\n  Choice: ").lower()
        except BackSignal:
            return
        # ExitToMainSignal and QuitSignal propagate naturally

        if choice in keys:
            try:
                keys[choice]()
            except BackSignal:
                pass  # stay in this submenu; action was aborted
            # ExitToMainSignal and QuitSignal propagate
        else:
            print("  Unrecognized choice.")


def menu_initial_setup() -> None:
    _submenu(
        "Initial Setup",
        [
            ("1", "Setup wizard  (prerequisites + credentials)", check_prerequisites),
            ("2", "Update Garmin credentials", configure_credentials),
        ],
    )


def menu_pull_data() -> None:
    _submenu(
        "Pull Data",
        [
            ("", "─── Recent ──────────────────────────────────────────", None),
            ("1", "Yesterday", _pull_yesterday),
            ("2", "Last 7 days", lambda: _pull_last_n(7, "last 7 days")),
            ("3", "Last 30 days", lambda: _pull_last_n(30, "last 30 days")),
            ("", "─── Custom ──────────────────────────────────────────", None),
            ("4", "Specific date or date range", _pull_custom),
            ("5", "Full history  (from a date you choose to today)", _pull_everything),
            ("", "─── Historical import ───────────────────────────────", None),
            ("6", "Import from Garmin bulk export (.zip)", import_export),
            ("", "─── Reports ─────────────────────────────────────────", None),
            ("7", "Rebuild CSV reports  (from existing pulled data)", build_csvs),
        ],
    )


def menu_automation() -> None:
    _submenu(
        "Configure Automation",
        [
            ("", "─── Unattended MFA ─────────────────────────────────", None),
            ("1", "Set up Gmail MFA  (auto-handle Garmin security codes)", setup_gmail_mfa),
        ],
    )


def main(dry_run: bool = False, verbose: int = 0) -> None:
    # TODO Phase 2: thread dry_run through action functions
    _first_run_notice()

    actions: dict[str, Callable[[], None]] = {
        "1": menu_initial_setup,
        "2": menu_pull_data,
        "3": menu_automation,
    }

    while True:
        header("garmin-extract")
        print("    1  Initial Setup")
        print("    2  Pull Data")
        print("    3  Configure Automation")
        print()
        hr()
        print("    q  Quit")
        hr()

        try:
            choice = prompt_with_navigation("\n  Choice: ").lower()
        except (BackSignal, ExitToMainSignal):
            continue  # no-op at main menu level
        except QuitSignal:
            break

        if choice in actions:
            try:
                actions[choice]()
            except ExitToMainSignal:
                pass  # return to main menu loop
            except QuitSignal:
                break
        else:
            print("  Unrecognized choice.")

    print()
