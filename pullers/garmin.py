#!/usr/bin/env python3
"""
Garmin Connect data puller — browser-based.

All API calls run through Chrome's fetch() via SeleniumBase, which means
Cloudflare never blocks us. The browser logs in once via SSO and keeps a
persistent session; subsequent runs load the saved profile and skip login.

On headless Linux (no $DISPLAY), Chrome runs inside a virtual framebuffer
(Xvfb). On desktop Linux, Windows, and macOS it runs directly.

Usage:
    python pullers/garmin.py                         # yesterday
    python pullers/garmin.py --date 2026-04-06       # specific date
    python pullers/garmin.py --days 7                # last 7 days
    python pullers/garmin.py --date 2026-03-01 --days 30
    python pullers/garmin.py --no-skip               # re-pull existing dates
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT        = Path(__file__).parent.parent
DATA_DIR    = ROOT / "data" / "garmin"
PROFILE_DIR = ROOT / ".garmin_browser_profile"
MFA_FILE    = ROOT / ".mfa_code"
RATE_LIMIT  = 0.5  # seconds between API calls


# ---------------------------------------------------------------------------
# Xvfb (headless Linux only)
# ---------------------------------------------------------------------------

def needs_virtual_display() -> bool:
    """Return True only on headless Linux — where Chrome needs a fake screen."""
    return platform.system() == "Linux" and not os.environ.get("DISPLAY")


def start_xvfb(display=":99"):
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x720x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = display
    time.sleep(1)
    return proc


# ---------------------------------------------------------------------------
# MFA handoff (file-based, works without interactive stdin)
# ---------------------------------------------------------------------------

def wait_for_mfa() -> str:
    # Try Gmail automation first
    try:
        from _gmail_mfa import wait_for_mfa_gmail, is_configured
        if is_configured():
            print("MFA REQUIRED — polling Gmail automatically...")
            code = wait_for_mfa_gmail(timeout=300)
            if code:
                print(f"MFA code retrieved from Gmail: {code}")
                return code
            print("Gmail poll failed or timed out — falling back to manual entry.")
    except ImportError:
        pass

    # Manual file-based fallback
    MFA_FILE.unlink(missing_ok=True)
    print("=" * 50)
    print("MFA REQUIRED — check your email")
    print(f"Run: echo YOUR_CODE > {MFA_FILE}")
    print("Waiting up to 5 minutes...")
    print("=" * 50)
    for _ in range(300):
        if MFA_FILE.exists():
            code = MFA_FILE.read_text().strip()
            MFA_FILE.unlink(missing_ok=True)
            print("MFA code received.")
            return code
        time.sleep(1)
    print("ERROR: Timed out waiting for MFA code.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------

def ensure_logged_in(sb):
    """Check session and log in if needed."""
    # Remove stale Chrome lock files that prevent profile reuse
    lock = PROFILE_DIR / "SingletonLock"
    if lock.exists():
        lock.unlink()

    sb.uc_open_with_reconnect("https://connect.garmin.com/modern/", reconnect_time=3)
    sb.sleep(3)

    if "sign-in" in sb.get_current_url() or "sso.garmin.com" in sb.get_current_url():
        print("Session expired or new — logging in...")
        _do_login(sb)
    else:
        print("Existing session active.")


def _do_login(sb):
    sb.uc_open_with_reconnect(
        "https://sso.garmin.com/portal/sso/en-US/sign-in"
        "?clientId=GarminConnect&consumeServiceTicket=false",
        reconnect_time=3,
    )
    sb.sleep(3)

    email    = os.environ["GARMIN_EMAIL"]
    password = os.environ["GARMIN_PASSWORD"]

    sb.type("#email", email)
    sb.type("#password", password)
    sb.sleep(1)
    sb.save_screenshot("/tmp/garmin_pre_submit.png")
    sb.click("button[type='submit']")

    # Wait up to 30s for login to complete or MFA to appear
    for i in range(30):
        sb.sleep(1)
        url = sb.get_current_url()
        page = sb.get_page_source()

        if i % 5 == 4:  # screenshot every 5s
            sb.save_screenshot(f"/tmp/garmin_login_{i}.png")
            print(f"  [{i+1}s] URL: {url[:100]}")

        # Check for MFA input field — Garmin's email MFA page has "Security Code" label
        mfa_selectors = [
            "input[name='verificationCode']",
            "input[type='tel']",
            "#mfa-code",
            "input[autocomplete='one-time-code']",
            "input[name='securityCode']",
            "input[id='securityCode']",
            "input[placeholder*='code' i]",
            "input[placeholder*='security' i]",
        ]
        # Also detect by URL — if we're on the /mfa page, find any visible text input
        if "/mfa" in url:
            try:
                inputs = sb.driver.find_elements("css selector", "input[type='text'], input[type='number'], input:not([type])")
                for inp in inputs:
                    if inp.is_displayed():
                        sb.save_screenshot("/tmp/garmin_mfa_page.png")
                        print(f"MFA page — found input: name={inp.get_attribute('name')} id={inp.get_attribute('id')}")
                        mfa = wait_for_mfa()
                        inp.clear()
                        inp.send_keys(mfa)
                        # Check "Remember this browser" to persist the session
                        try:
                            remember = sb.driver.find_element("css selector", "input[type='checkbox']")
                            if remember and not remember.is_selected():
                                remember.click()
                                print("Checked 'Remember this browser'")
                        except Exception:
                            pass
                        for btn in ["button[type='submit']", "input[type='submit']", "button"]:
                            try:
                                btns = sb.driver.find_elements("css selector", btn)
                                for b in btns:
                                    if b.is_displayed() and b.text.strip():
                                        b.click()
                                        break
                            except Exception:
                                continue
                        # Wait up to 15s for redirect away from MFA page before looping
                        for _ in range(15):
                            sb.sleep(1)
                            if "/mfa" not in sb.get_current_url():
                                break
                        break  # submitted once — don't re-enter MFA loop
            except Exception as e:
                print(f"MFA input search error: {e}")
            continue

        for sel in mfa_selectors:
            try:
                if sb.is_element_visible(sel):
                    sb.save_screenshot("/tmp/garmin_mfa_page.png")
                    print(f"MFA input detected: {sel}")
                    mfa = wait_for_mfa()
                    sb.type(sel, mfa)
                    for btn in ["button[type='submit']", "[data-testid='g__button']"]:
                        try:
                            if sb.is_element_visible(btn):
                                sb.click(btn)
                                break
                        except Exception:
                            continue
                    # Wait up to 15s for redirect away from MFA page before looping
                    for _ in range(15):
                        sb.sleep(1)
                        if "/mfa" not in sb.get_current_url():
                            break
                    break  # submitted once — don't re-enter MFA loop
            except Exception:
                continue

        if url.startswith("https://connect.garmin.com"):
            break

    sb.save_screenshot("/tmp/garmin_post_login.png")
    print(f"Post-login URL: {sb.get_current_url()[:100]}")

    # If not on connect.garmin.com yet, navigate there to complete session
    if not sb.get_current_url().startswith("https://connect.garmin.com"):
        print("Navigating to connect.garmin.com to complete session...")
        sb.uc_open_with_reconnect("https://connect.garmin.com/modern/", reconnect_time=3)
        sb.sleep(5)
        sb.save_screenshot("/tmp/garmin_after_navigate.png")

    # Ensure we land on the app page which contains the csrf-token meta
    if not sb.get_current_url().startswith("https://connect.garmin.com/app"):
        sb.uc_open_with_reconnect("https://connect.garmin.com/app/home", reconnect_time=3)
    sb.sleep(5)  # let the SPA fully render and set csrf-token meta

    csrf = sb.driver.execute_script(
        "return document.querySelector('meta[name=\"csrf-token\"]')?.content || 'none'"
    )
    print(f"Login complete. URL: {sb.get_current_url()[:80]}")
    print(f"CSRF token: {csrf[:20]}...")


# ---------------------------------------------------------------------------
# Browser fetch helper
# ---------------------------------------------------------------------------

def browser_fetch(sb, url: str, params: dict = None) -> dict:
    """Execute a GET request from inside the browser via fetch(), with CSRF token."""
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    full_url = f"https://connect.garmin.com/gc-api{url}"

    script = """
    const [url, done] = [arguments[0], arguments[arguments.length - 1]];
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: {
            'NK': 'NT',
            'X-app-ver': '4.70.2.0',
            'Accept': 'application/json, text/plain, */*',
            'connect-csrf-token': csrf,
        }
    })
    .then(r => r.text().then(text => {
        try { done({ok: r.ok, status: r.status, data: JSON.parse(text)}); }
        catch(e) { done({ok: r.ok, status: r.status, data: text}); }
    }))
    .catch(err => done({ok: false, status: 0, error: err.toString()}));
    """
    result = sb.driver.execute_async_script(script, full_url)
    time.sleep(RATE_LIMIT)
    return result


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

def get_user_uuid(sb) -> str:
    """Extract Garmin UUID from the SPA's JS context."""
    try:
        uuid = sb.driver.execute_script("""
            return window.__userInfo?.uuid
                || window.__userInfo?.userUuid
                || document.cookie.match(/GarminUserPrefs=([^;]+)/)?.[1]
                || null;
        """)
        if uuid:
            return uuid
    except Exception:
        pass

    # Fall back: fetch socialProfile without UUID (returns current user)
    result = browser_fetch(sb, "/userprofile-service/socialProfile")
    if result.get("ok") and isinstance(result.get("data"), dict):
        uuid = result["data"].get("userUuid") or result["data"].get("uuid")
        if uuid:
            return uuid

    return ""


def get_display_name(sb) -> str:
    """Return (displayName, uuid) for the logged-in Garmin user."""
    # socialProfile without UUID returns the current user's profile
    endpoints = [
        ("/userprofile-service/socialProfile",
         lambda d: (d.get("displayName"), d.get("userUuid") or d.get("uuid"))),
        ("/userprofile-service/userprofile/personal-information",
         lambda d: (d.get("displayName") or d.get("userName"), d.get("userUuid"))),
    ]
    for path, extractor in endpoints:
        result = browser_fetch(sb, path)
        print(f"  {path}: ok={result.get('ok')} status={result.get('status')} "
              f"data={str(result.get('data'))[:150]}")
        if result.get("ok") and isinstance(result.get("data"), dict):
            name, uuid = extractor(result["data"])
            if name:
                return name, uuid or ""

    # Last resort: JS context
    try:
        name = sb.driver.execute_script(
            "return window.__userInfo?.displayName || window.garmin?.user?.displayName || null"
        )
        if name:
            return name, ""
    except Exception as e:
        print(f"  JS extraction failed: {e}")

    return "", ""


def build_metrics(sb, d: date, display_name: str, uuid: str = "") -> list:
    cdate = d.isoformat()
    # Some endpoints use displayName, some use UUID — use whichever is available
    uid = uuid or display_name
    return [
        ("stats",               f"/usersummary-service/usersummary/daily/{display_name}",
                                {"calendarDate": cdate}),
        ("user_summary_chart",  f"/wellness-service/wellness/dailySummaryChart/{display_name}",
                                {"date": cdate}),
        ("heart_rates",         f"/wellness-service/wellness/dailyHeartRate/{display_name}",
                                {"date": cdate}),
        ("resting_hr",          f"/userstats-service/wellness/daily/{display_name}",
                                {"fromDate": cdate, "untilDate": cdate, "metricId": 60}),
        ("hrv",                 f"/hrv-service/hrv/{cdate}", {}),
        ("stress",              f"/wellness-service/wellness/dailyStress/{cdate}", {}),
        ("body_battery",        "/wellness-service/wellness/bodyBattery/reports/daily",
                                {"startDate": cdate, "endDate": cdate}),
        ("body_battery_events", f"/wellness-service/wellness/bodyBattery/events/{cdate}", {}),
        ("sleep",               f"/wellness-service/wellness/dailySleepData/{display_name}",
                                {"date": cdate, "nonSleepBufferMinutes": 60}),
        ("steps",               f"/usersummary-service/stats/steps/daily/{cdate}/{cdate}", {}),
        ("floors",              f"/wellness-service/wellness/floorsChartData/daily/{cdate}", {}),
        ("spo2",                f"/wellness-service/wellness/daily/spo2/{cdate}", {}),
        ("respiration",         f"/wellness-service/wellness/daily/respiration/{cdate}", {}),
        ("intensity_minutes",   f"/wellness-service/wellness/daily/im/{cdate}", {}),
        ("all_day_events",      "/wellness-service/wellness/dailyEvents",
                                {"calendarDate": cdate}),
        ("activities",          f"/activitylist-service/activities/search/activities",
                                {"startDate": cdate, "endDate": cdate, "start": 0, "limit": 20}),
        ("weigh_ins",           f"/weight-service/weight/dayview/{cdate}",
                                {"includeAll": "true"}),
        ("body_composition",    "/weight-service/weight/dateRange",
                                {"startDate": cdate, "endDate": cdate}),
        ("blood_pressure",      f"/bloodpressure-service/bloodpressure/range/{cdate}/{cdate}", {}),
        ("max_metrics",         f"/metrics-service/metrics/maxmet/daily/{cdate}/{cdate}", {}),
        ("training_readiness",  f"/metrics-service/metrics/trainingreadiness/{cdate}", {}),
        ("training_status",     f"/metrics-service/metrics/trainingstatus/aggregated/{cdate}", {}),
        ("fitness_age",         f"/fitnessage-service/fitnessage/{cdate}", {}),
        ("hydration",           f"/usersummary-service/usersummary/hydration/daily/{cdate}", {}),
        ("lifestyle",           f"/lifestylelogging-service/dailyLog/{cdate}", {}),
    ]


# ---------------------------------------------------------------------------
# Pull one date
# ---------------------------------------------------------------------------

def pull_date(sb, d: date, display_name: str, uuid: str = "") -> dict:
    metrics = build_metrics(sb, d, display_name, uuid)
    pad = max(len(name) for name, _, _ in metrics)
    results = {}

    for name, path, params in metrics:
        try:
            result = browser_fetch(sb, path, params or None)
            results[name] = result.get("data") if result.get("ok") else result
            status = "✓" if result.get("ok") else f"✗ HTTP {result.get('status')}"
        except Exception as e:
            results[name] = {"_error": str(e)}
            status = f"✗ {e}"
        print(f"    {status:<4} {name:<{pad}}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Pull all Garmin Connect health metrics via browser."
    )
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=date.today() - timedelta(days=1),
        metavar="YYYY-MM-DD",
        help="Start date (default: yesterday).",
    )
    parser.add_argument(
        "--days", type=int, default=1,
        help="Number of days to pull from --date (default: 1).",
    )
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Re-pull dates that already have a data file.",
    )
    return parser.parse_args()


def main():
    try:
        from seleniumbase import SB
    except ImportError:
        print("ERROR: seleniumbase not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    email    = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")
        sys.exit(1)

    args = parse_args()
    dates = [args.date + timedelta(days=i) for i in range(args.days)]

    xvfb = None
    if needs_virtual_display():
        print("Starting Xvfb...")
        xvfb = start_xvfb()

    try:
        print("Launching browser...")
        PROFILE_DIR.mkdir(exist_ok=True)
        with SB(uc=True, headless=False, user_data_dir=str(PROFILE_DIR)) as sb:
            ensure_logged_in(sb)

            print("Getting display name...")
            display_name, uuid = get_display_name(sb)
            if not display_name:
                print("ERROR: Could not retrieve display name — login may have failed.")
                sys.exit(1)
            print(f"Logged in as: {display_name} (uuid={uuid or 'unknown'})\n")

            for d in dates:
                out_path = DATA_DIR / f"{d.isoformat()}.json"
                DATA_DIR.mkdir(parents=True, exist_ok=True)

                if not args.no_skip and out_path.exists():
                    print(f"[{d}] Already pulled — skipping (--no-skip to re-pull)")
                    continue

                print(f"[{d}] Pulling {len(build_metrics(sb, d, display_name, uuid))} metrics...")
                results = pull_date(sb, d, display_name, uuid)
                results["_meta"] = {
                    "date": d.isoformat(),
                    "pulled_at": datetime.utcnow().isoformat() + "Z",
                    "source": "garmin-browser",
                    "display_name": display_name,
                    "uuid": uuid,
                }

                with open(out_path, "w") as f:
                    json.dump(results, f, indent=2, default=str)
                print(f"  → {out_path}\n")

    finally:
        if xvfb:
            xvfb.terminate()

    print("Done.")


if __name__ == "__main__":
    main()
