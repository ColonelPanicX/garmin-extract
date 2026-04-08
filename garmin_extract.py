#!/usr/bin/env python3
"""
garmin_extract.py — interactive entry point for garmin-extract.

Walks through first-time setup and provides a menu for day-to-day operations.
Run with: python garmin_extract.py
"""

import getpass
import os
import platform
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT   = Path(__file__).parent
ENV    = ROOT / ".env"
PYTHON = sys.executable


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def hr(char="─", width=52):
    print(char * width)

def header(title):
    print()
    hr()
    print(f"  {title}")
    hr()
    print()

def run(cmd):
    subprocess.run(cmd)

def load_env():
    vals = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals

def save_env(vals):
    lines = [
        "# Garmin Connect credentials",
        f"GARMIN_EMAIL={vals.get('GARMIN_EMAIL', '')}",
        f"GARMIN_PASSWORD={vals.get('GARMIN_PASSWORD', '')}",
        "",
        "# Google Drive folder ID (from Drive URL: drive.google.com/drive/folders/<ID>)",
        "# Required only when using the Google Sheets export script",
        f"GOOGLE_DRIVE_FOLDER_ID={vals.get('GOOGLE_DRIVE_FOLDER_ID', 'your_folder_id_here')}",
    ]
    ENV.write_text("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Prerequisite helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_chrome():
    system = platform.system()
    if system == "Windows":
        candidates = [
            "chrome",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif system == "Darwin":
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


def _find_xvfb():
    try:
        r = subprocess.run(["which", "Xvfb"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _missing_packages():
    checks = [
        ("seleniumbase",      "seleniumbase"),
        ("dotenv",            "python-dotenv"),
        ("google.oauth2",     "google-auth"),
        ("googleapiclient",   "google-api-python-client"),
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

def check_prerequisites():
    header("Setup Wizard")
    system  = platform.system()
    issues  = []

    # ── Step 1: Python ───────────────────────────────────────────────────────
    print("Step 1 of 5 — Python version")
    print()
    v  = sys.version_info
    ok = v >= (3, 12)

    if ok:
        print(f"  ✓  Python {v.major}.{v.minor}.{v.micro}")
    else:
        print(f"  ✗  Python {v.major}.{v.minor}.{v.micro} — version 3.12 or newer is required.")
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
        input("\n  Press Enter to return to the menu...")
        return

    # ── Step 2: Google Chrome ────────────────────────────────────────────────
    print()
    hr()
    print()
    print("Step 2 of 5 — Google Chrome")
    print()
    found, version = _find_chrome()

    if found:
        print(f"  ✓  {version}")
    else:
        print("  ✗  Chrome not found.")
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
            print('    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \\')
            print("        | sudo tee /etc/apt/sources.list.d/google-chrome.list")
            print("    sudo apt-get update")
            print("    sudo apt-get install -y google-chrome-stable")
            print("    sudo apt-get --fix-broken install -y")
            print()
            go = input("  Install Chrome now? [Y/n]: ").strip().lower()
            if go != "n":
                print()
                cmds = [
                    "wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -",
                    'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" '
                    '| sudo tee /etc/apt/sources.list.d/google-chrome.list',
                    "sudo apt-get update",
                    "sudo apt-get install -y google-chrome-stable",
                    "sudo apt-get --fix-broken install -y",
                ]
                success = True
                for cmd in cmds:
                    r = subprocess.run(cmd, shell=True)
                    if r.returncode != 0:
                        success = False
                        break
                found, version = _find_chrome()
                if found:
                    print(f"\n  ✓  Chrome installed: {version}")
                else:
                    print("\n  ✗  Installation may not have completed. Check the output above.")
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

    needs_xvfb = (system == "Linux" and not os.environ.get("DISPLAY"))

    if not needs_xvfb:
        if system == "Linux":
            print("  ✓  Not needed — a display is already available.")
        else:
            print(f"  ✓  Not needed on {system}.")
    else:
        xvfb_ok = _find_xvfb()
        if xvfb_ok:
            print("  ✓  Xvfb is installed.")
        else:
            print("  ✗  Xvfb not found.")
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
            go = input("  Install Xvfb now? [Y/n]: ").strip().lower()
            if go != "n":
                print()
                r = subprocess.run(["sudo", "apt-get", "install", "-y", "xvfb"])
                if r.returncode == 0 and _find_xvfb():
                    print("\n  ✓  Xvfb installed.")
                else:
                    print("\n  ✗  Installation may not have completed.")
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
        print("  ✓  All required packages are installed.")
    else:
        print(f"  ✗  Missing: {', '.join(missing)}")
        print()
        print("  These are the libraries this tool depends on:")
        print()
        print("  · seleniumbase          — controls Chrome")
        print("  · python-dotenv         — reads your .env credentials file")
        print("  · google-auth           — handles Google sign-in for Gmail MFA")
        print("  · google-api-python-client — connects to Gmail and Google Sheets")
        print("  · requests-oauthlib     — handles the Google authorization flow")
        print()
        print("  All packages are listed in requirements.txt and will be")
        print("  installed from the official Python package repository (PyPI).")
        print()
        go = input("  Install packages now? [Y/n]: ").strip().lower()
        if go != "n":
            print()
            r = subprocess.run(
                [PYTHON, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
            )
            missing = _missing_packages()
            if not missing:
                print("\n  ✓  All packages installed.")
            else:
                print(f"\n  ✗  Still missing after install: {', '.join(missing)}")
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
        print(f"  ✓  Credentials on file: {env['GARMIN_EMAIL']}")
    else:
        print("  Your Garmin Connect email and password are needed so the tool")
        print("  can log in to Garmin on your behalf.")
        print()
        print("  These are saved to a local file called .env in this directory.")
        print("  That file is excluded from version control and never shared.")
        print()
        email = input("  Garmin Connect email: ").strip()
        if not email:
            print("\n  Skipped. Run option 2 to add credentials later.")
            issues.append("Garmin credentials")
        else:
            password = getpass.getpass("  Garmin Connect password: ")
            if not password:
                print("\n  Skipped. Run option 2 to add credentials later.")
                issues.append("Garmin credentials")
            else:
                env["GARMIN_EMAIL"]    = email
                env["GARMIN_PASSWORD"] = password
                save_env(env)
                print("\n  ✓  Saved to .env")

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
        print('    will print:  Run: echo YOUR_CODE > .mfa_code')
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

    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Configure Garmin credentials
# ─────────────────────────────────────────────────────────────────────────────

def configure_credentials():
    header("Configure Garmin Credentials")
    print("  Stored in .env (gitignored — never committed).\n")
    env = load_env()

    cur_email = env.get("GARMIN_EMAIL", "")
    cur_pass  = env.get("GARMIN_PASSWORD", "")

    if cur_email:
        print(f"  Current email:    {cur_email}")
        new = input("  New email         (Enter to keep): ").strip()
        email = new or cur_email
    else:
        email = input("  Garmin email: ").strip()

    if cur_pass:
        print(f"  Current password: {'*' * min(len(cur_pass), 12)}")
        new = getpass.getpass("  New password      (Enter to keep): ")
        password = new or cur_pass
    else:
        password = getpass.getpass("  Garmin password: ")

    if not email or not password:
        print("\n  No changes made.")
        input("\n  Press Enter to continue...")
        return

    env["GARMIN_EMAIL"]    = email
    env["GARMIN_PASSWORD"] = password
    save_env(env)
    print("\n  Saved to .env")
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Gmail MFA setup
# ─────────────────────────────────────────────────────────────────────────────

def setup_gmail_mfa():
    header("Gmail MFA Automation Setup")
    print("  When Garmin requires a security code (~every 30 days), this module")
    print("  polls your Gmail inbox and submits it automatically. Without it,")
    print("  you'll be prompted to paste the code manually.\n")
    hr()

    creds_file = ROOT / "google_credentials.json"
    if not creds_file.exists():
        print()
        print("  google_credentials.json not found.\n")
        print("  To create it:")
        print("    1. Go to console.cloud.google.com")
        print("    2. Create a project")
        print("    3. Enable: Gmail API, Google Sheets API, Google Drive API")
        print("    4. Credentials → Create → OAuth 2.0 Client ID → Desktop app")
        print("    5. Download JSON → save as google_credentials.json in this directory")
        print()
        print("  Then run this option again to complete authorization.")
        input("\n  Press Enter to continue...")
        return

    print("  google_credentials.json found. Starting authorization flow...\n")
    result = subprocess.run([PYTHON, str(ROOT / "scripts" / "setup_gmail_auth.py")])
    if result.returncode == 0:
        print("\n  Gmail MFA automation is now active.")
    else:
        print("\n  Setup did not complete — check the output above.")
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pull Garmin data
# ─────────────────────────────────────────────────────────────────────────────

def pull_data():
    header("Pull Garmin Data")

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print(f"  Default: yesterday ({yesterday})")
    print("  For a range: enter a start date and number of days.\n")

    date_in = input(f"  Date [Enter for {yesterday}]: ").strip()
    target  = date_in if date_in else yesterday

    days_in = input("  Days  [Enter for 1]: ").strip()
    days    = int(days_in) if days_in.isdigit() and int(days_in) > 0 else 1

    reskip = input("  Re-pull dates that already exist? [y/N]: ").strip().lower()

    cmd = [PYTHON, str(ROOT / "pullers" / "garmin.py"), "--date", target, "--days", str(days)]
    if reskip == "y":
        cmd.append("--no-skip")

    print()
    run(cmd)
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Import from Garmin bulk export
# ─────────────────────────────────────────────────────────────────────────────

def import_export():
    header("Import from Garmin Bulk Export")
    print("  Request your export at:")
    print("  Garmin Connect → Profile → Account → Your Garmin Data")
    print("  (The .zip file arrives within 24–48 hours.)\n")

    zip_path = input("  Path to export .zip: ").strip().strip('"').strip("'")
    if not zip_path:
        print("  Cancelled.")
        input("\n  Press Enter to continue...")
        return

    if not Path(zip_path).exists():
        print(f"\n  File not found: {zip_path}")
        input("\n  Press Enter to continue...")
        return

    reskip = input("  Overwrite dates that already have data? [y/N]: ").strip().lower()
    cmd = [PYTHON, str(ROOT / "pullers" / "garmin_import_export.py"), zip_path]
    if reskip == "y":
        cmd.append("--no-skip")

    print()
    run(cmd)
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Build CSV reports
# ─────────────────────────────────────────────────────────────────────────────

def build_csvs():
    header("Build CSV Reports")
    print("  Flattens all JSON data files into:")
    print("  · reports/garmin_daily.csv       — one row per day")
    print("  · reports/garmin_activities.csv  — one row per workout\n")

    since = input("  Include data from [Enter for all time, or YYYY-MM-DD]: ").strip()
    cmd   = [PYTHON, str(ROOT / "reports" / "build_garmin_csvs.py")]
    if since:
        cmd += ["--since", since]

    print()
    run(cmd)
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Build Google Sheets
# ─────────────────────────────────────────────────────────────────────────────

def build_sheets():
    header("Build Google Sheets")

    if not (ROOT / ".google_token.json").exists():
        print("  Google credentials not configured.")
        print("  Run option 3 (Gmail MFA setup) first — the same credentials")
        print("  are used for Sheets access.")
        input("\n  Press Enter to continue...")
        return

    env = load_env()
    folder_id = env.get("GOOGLE_DRIVE_FOLDER_ID", "")

    if not folder_id or folder_id == "your_folder_id_here":
        print("  GOOGLE_DRIVE_FOLDER_ID is not set.\n")
        print("  Find your folder ID in the Drive URL:")
        print("  drive.google.com/drive/folders/<FOLDER_ID>\n")
        new_id = input("  Folder ID (Enter to cancel): ").strip()
        if not new_id:
            input("\n  Press Enter to continue...")
            return
        env["GOOGLE_DRIVE_FOLDER_ID"] = new_id
        save_env(env)
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = new_id
        print("  Saved to .env\n")

    year_in = input("  Year to process [Enter for all years]: ").strip()
    rebuild = input("  Rebuild existing sheets? [y/N]: ").strip().lower()

    cmd = [PYTHON, str(ROOT / "reports" / "build_garmin_sheets.py")]
    if year_in.isdigit():
        cmd += ["--year", year_in]
    if rebuild == "y":
        cmd.append("--rebuild")

    print()
    run(cmd)
    input("\n  Press Enter to continue...")


# ─────────────────────────────────────────────────────────────────────────────
# Main menu
# ─────────────────────────────────────────────────────────────────────────────

def _first_run_notice():
    if not ENV.exists():
        print()
        hr("═")
        print("  garmin-extract")
        hr("═")
        print()
        print("  Looks like your first run — .env not found.")
        print()
        print("  Start with option 1 (Initial Setup) to get everything")
        print("  installed and configured before pulling data.")
        input("\n  Press Enter to open the menu...")


def _submenu(title, options):
    """
    Generic sub-menu loop.
    options: list of (key, label, fn) — fn=None renders as a section header.
    """
    keys = {k: fn for k, label, fn in options if fn is not None}
    while True:
        print()
        hr("─")
        print(f"  {title}")
        hr("─")
        print()
        for key, label, fn in options:
            if fn is None:
                print(f"  {label}")
            else:
                print(f"    {key}  {label}")
        print()
        print("    b  Back")
        print()
        hr()
        choice = input("  Choice: ").strip().lower()
        if choice == "b":
            break
        elif choice in keys:
            keys[choice]()
        else:
            print("  Unrecognized choice.")


def menu_initial_setup():
    _submenu("Initial Setup", [
        ("1", "Setup wizard  (prerequisites + credentials)", check_prerequisites),
        ("2", "Update Garmin credentials",                  configure_credentials),
    ])


def menu_pull_data():
    _submenu("Pull Data", [
        ("1", "Pull Garmin data",                    pull_data),
        ("2", "Import from Garmin bulk export (.zip)", import_export),
        ("3", "Build CSV reports",                   build_csvs),
    ])


def menu_automation():
    _submenu("Configure Automation", [
        ("", "─── Unattended MFA ─────────────────────────────────", None),
        ("1", "Set up Gmail MFA  (auto-handle Garmin security codes)", setup_gmail_mfa),
        ("", "─── Reporting ───────────────────────────────────────", None),
        ("2", "Build Google Sheets",                                   build_sheets),
    ])


def main():
    _first_run_notice()

    actions = {
        "1": menu_initial_setup,
        "2": menu_pull_data,
        "3": menu_automation,
    }

    while True:
        print()
        hr("═")
        print("  garmin-extract")
        hr("═")
        print()
        print("    1  Initial Setup")
        print("    2  Pull Data")
        print("    3  Configure Automation")
        print()
        print("    q  Quit")
        print()
        hr()

        choice = input("  Choice: ").strip().lower()

        if choice == "q":
            print()
            break
        elif choice in actions:
            actions[choice]()
        else:
            print("  Unrecognized choice.")


if __name__ == "__main__":
    main()
