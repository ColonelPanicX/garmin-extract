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
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ROOT points to the app directory — containing data/, .env, .garmin_browser_profile/.
# In a PyInstaller bundle, __file__ is inside _internal/ so we use sys.executable's
# parent (the directory containing garmin-extract.exe) instead.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent.parent

DATA_DIR = ROOT / "data" / "garmin"
PROFILE_DIR = ROOT / ".garmin_browser_profile"
MFA_FILE = ROOT / ".mfa_code"
RATE_LIMIT = 0.5  # seconds between API calls


# ---------------------------------------------------------------------------
# Xvfb (headless Linux only)
# ---------------------------------------------------------------------------


def needs_virtual_display() -> bool:
    """Return True only on headless Linux — where Chrome needs a fake screen."""
    return platform.system() == "Linux" and not os.environ.get("DISPLAY")


def has_display() -> bool:
    """Return True when a real/virtual display is available for manual interaction."""
    if platform.system() == "Windows":
        return True
    return bool(os.environ.get("DISPLAY"))


from garmin_extract._browser import detect_windows_browser  # noqa: E402


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
# MFA handoff
# ---------------------------------------------------------------------------


def wait_for_mfa() -> str:
    # Try Gmail automation first
    try:
        from _gmail_mfa import is_configured, wait_for_mfa_gmail  # noqa: I001

        if is_configured():
            print("MFA REQUIRED — polling Gmail automatically...")
            code = wait_for_mfa_gmail(timeout=300)
            if code:
                print(f"MFA code retrieved from Gmail: {code}")
                return code
            print("Gmail poll failed or timed out — falling back to manual entry.")
    except ImportError:
        pass

    # Interactive fallback — prompt inline when stdin is a real terminal.
    # Guard with EOFError: on Windows the NUL device can report isatty()=True
    # even when stdin is not interactive (e.g. subprocess with DEVNULL).
    print()
    print("MFA REQUIRED — check your email for the 6-digit code.")
    if sys.stdin.isatty():
        try:
            while True:
                code = input("  Enter code: ").strip()
                if code:
                    return code
                print("  No code entered — please try again.")
        except EOFError:
            pass  # stdin not truly interactive — fall through to file poll

    # Non-interactive fallback (cron / piped stdin) — poll a file
    MFA_FILE.unlink(missing_ok=True)
    print("=" * 50)
    print(f"Run: echo YOUR_CODE > {MFA_FILE}")
    print("Waiting up to 30 minutes...")
    print("=" * 50)
    for _ in range(1800):
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


def ensure_logged_in(sb, email: str = "", password: str = "") -> None:
    """Check session and log in if needed.

    If email/password are provided, login is automated. Otherwise the browser
    opens to the login page and waits for the user to log in manually.
    """
    # Remove stale Chrome lock files that prevent profile reuse
    lock = PROFILE_DIR / "SingletonLock"
    if lock.exists():
        lock.unlink()

    sb.uc_open_with_reconnect("https://connect.garmin.com/modern/", reconnect_time=3)
    sb.sleep(3)

    if "sign-in" in sb.get_current_url() or "sso.garmin.com" in sb.get_current_url():
        if email and password:
            print("Session expired or new — logging in...")
            _do_login(sb, email, password)
        else:
            _wait_for_manual_login(sb)
    else:
        print("Existing session active.")


def _wait_for_manual_login(sb) -> None:
    """Wait up to 5 minutes for the user to log in manually via the browser."""
    print("No credentials configured — please log in to Garmin Connect in the browser.")
    print("Waiting up to 5 minutes for login to complete...")
    for _ in range(300):
        url = sb.get_current_url()
        if "connect.garmin.com" in url and "sso.garmin.com" not in url and "sign-in" not in url:
            print("Login detected.")
            return
        time.sleep(1)
    print("ERROR: Timed out waiting for manual login.")
    sys.exit(1)


def _do_login(sb, email: str, password: str) -> None:
    sb.uc_open_with_reconnect(
        "https://sso.garmin.com/portal/sso/en-US/sign-in"
        "?clientId=GarminConnect&consumeServiceTicket=false",
        reconnect_time=6,
    )
    sb.sleep(5)

    sb.type("#email", email)
    sb.type("#password", password)
    sb.sleep(1)
    sb.save_screenshot(str(Path(tempfile.gettempdir()) / "garmin_pre_submit.png"))
    sb.click("button[type='submit']")

    # Wait up to 30s for login to complete or MFA to appear
    for i in range(30):
        sb.sleep(1)
        url = sb.get_current_url()
        sb.get_page_source()

        if i % 5 == 4:  # screenshot every 5s
            sb.save_screenshot(str(Path(tempfile.gettempdir()) / f"garmin_login_{i}.png"))
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
                inputs = sb.driver.find_elements(  # noqa: E501
                    "css selector",
                    "input[type='text'], input[type='number'], input:not([type])",
                )
                for inp in inputs:
                    if inp.is_displayed():
                        sb.save_screenshot(str(Path(tempfile.gettempdir()) / "garmin_mfa_page.png"))
                        print(
                            f"MFA page — found input: name={inp.get_attribute('name')} id={inp.get_attribute('id')}"  # noqa: E501
                        )
                        mfa = wait_for_mfa()
                        inp.clear()
                        inp.send_keys(mfa)
                        # Check "Remember this browser" to persist the session
                        try:
                            remember = sb.driver.find_element(
                                "css selector", "input[type='checkbox']"
                            )  # noqa: E501
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
                    sb.save_screenshot(str(Path(tempfile.gettempdir()) / "garmin_mfa_page.png"))
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

    sb.save_screenshot(str(Path(tempfile.gettempdir()) / "garmin_post_login.png"))
    print(f"Post-login URL: {sb.get_current_url()[:100]}")

    # If not on connect.garmin.com yet, navigate there to complete session
    if not sb.get_current_url().startswith("https://connect.garmin.com"):
        print("Navigating to connect.garmin.com to complete session...")
        sb.uc_open_with_reconnect("https://connect.garmin.com/modern/", reconnect_time=3)
        sb.sleep(5)
        sb.save_screenshot(str(Path(tempfile.gettempdir()) / "garmin_after_navigate.png"))

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
        (
            "/userprofile-service/socialProfile",
            lambda d: (d.get("displayName"), d.get("userUuid") or d.get("uuid")),
        ),
        (
            "/userprofile-service/userprofile/personal-information",
            lambda d: (d.get("displayName") or d.get("userName"), d.get("userUuid")),
        ),
    ]
    for path, extractor in endpoints:
        result = browser_fetch(sb, path)
        print(
            f"  {path}: ok={result.get('ok')} status={result.get('status')} "
            f"data={str(result.get('data'))[:150]}"
        )
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
    return [
        (
            "stats",
            f"/usersummary-service/usersummary/daily/{display_name}",
            {"calendarDate": cdate},
        ),
        (
            "user_summary_chart",
            f"/wellness-service/wellness/dailySummaryChart/{display_name}",
            {"date": cdate},
        ),
        (
            "heart_rates",
            f"/wellness-service/wellness/dailyHeartRate/{display_name}",
            {"date": cdate},
        ),
        (
            "resting_hr",
            f"/userstats-service/wellness/daily/{display_name}",
            {"fromDate": cdate, "untilDate": cdate, "metricId": 60},
        ),
        ("hrv", f"/hrv-service/hrv/{cdate}", {}),
        ("stress", f"/wellness-service/wellness/dailyStress/{cdate}", {}),
        (
            "body_battery",
            "/wellness-service/wellness/bodyBattery/reports/daily",
            {"startDate": cdate, "endDate": cdate},
        ),
        ("body_battery_events", f"/wellness-service/wellness/bodyBattery/events/{cdate}", {}),
        (
            "sleep",
            f"/wellness-service/wellness/dailySleepData/{display_name}",
            {"date": cdate, "nonSleepBufferMinutes": 60},
        ),
        ("steps", f"/usersummary-service/stats/steps/daily/{cdate}/{cdate}", {}),
        ("floors", f"/wellness-service/wellness/floorsChartData/daily/{cdate}", {}),
        ("spo2", f"/wellness-service/wellness/daily/spo2/{cdate}", {}),
        ("respiration", f"/wellness-service/wellness/daily/respiration/{cdate}", {}),
        ("intensity_minutes", f"/wellness-service/wellness/daily/im/{cdate}", {}),
        ("all_day_events", "/wellness-service/wellness/dailyEvents", {"calendarDate": cdate}),
        (
            "activities",
            "/activitylist-service/activities/search/activities",
            {"startDate": cdate, "endDate": cdate, "start": 0, "limit": 20},
        ),
        ("weigh_ins", f"/weight-service/weight/dayview/{cdate}", {"includeAll": "true"}),
        (
            "body_composition",
            "/weight-service/weight/dateRange",
            {"startDate": cdate, "endDate": cdate},
        ),
        ("blood_pressure", f"/bloodpressure-service/bloodpressure/range/{cdate}/{cdate}", {}),
        ("max_metrics", f"/metrics-service/metrics/maxmet/daily/{cdate}/{cdate}", {}),
        ("training_readiness", f"/metrics-service/metrics/trainingreadiness/{cdate}", {}),
        ("training_status", f"/metrics-service/metrics/trainingstatus/aggregated/{cdate}", {}),
        ("fitness_age", f"/fitnessage-service/fitnessage/{cdate}", {}),
        ("hydration", f"/usersummary-service/usersummary/hydration/daily/{cdate}", {}),
        ("lifestyle", f"/lifestylelogging-service/dailyLog/{cdate}", {}),
        # Nutrition
        ("nutrition_food_log", f"/nutrition-service/food/logs/{cdate}", {}),
        ("nutrition_meals", f"/nutrition-service/meals/{cdate}", {}),
        # Reproductive health (empty for users without data — handled gracefully)
        ("menstrual_cycle", f"/periodichealth-service/menstrualcycle/dayview/{cdate}", {}),
    ]


# ---------------------------------------------------------------------------
# Per-activity detail metrics
# ---------------------------------------------------------------------------


def build_activity_metrics(activity_id: str) -> list:
    """Return per-activity detail endpoints for a single activity ID."""
    base = f"/activity-service/activity/{activity_id}"
    return [
        (f"activity_{activity_id}_detail", base, {}),
        (f"activity_{activity_id}_splits", f"{base}/splits", {}),
        (f"activity_{activity_id}_typed_splits", f"{base}/typedsplits", {}),
        (f"activity_{activity_id}_split_summaries", f"{base}/split_summaries", {}),
        (f"activity_{activity_id}_hr_timezones", f"{base}/hrTimeInZones", {}),
        (f"activity_{activity_id}_power_timezones", f"{base}/powerTimeInZones", {}),
        (f"activity_{activity_id}_exercise_sets", f"{base}/exerciseSets", {}),
        (f"activity_{activity_id}_weather", f"{base}/weather", {}),
    ]


# ---------------------------------------------------------------------------
# Static / profile metrics (pulled once per session, not per date)
# ---------------------------------------------------------------------------


def build_profile_metrics(display_name: str, user_profile_number: str = "") -> list:
    """Return static endpoints that don't change per date."""
    metrics = [
        ("user_profile", "/userprofile-service/userprofile/user-settings", {}),
        ("devices", "/device-service/deviceregistration/devices", {}),
        ("primary_training_device", "/web-gateway/device-info/primary-training-device", {}),
        (
            "personal_records",
            f"/personalrecord-service/personalrecord/prs/{display_name}",
            {},
        ),
        ("training_plans", "/trainingplan-service/trainingplan/plans", {}),
        ("workouts", "/workout-service/workouts", {"start": 0, "limit": 100}),
    ]
    if user_profile_number:
        metrics.append(
            ("gear", "/gear-service/gear/filterGear", {"userProfilePk": user_profile_number})
        )
    else:
        metrics.append(("gear", "/gear-service/gear/filterGear", {}))
    return metrics


def pull_profile_data(sb, display_name: str) -> None:
    """Pull static profile/device/gear data once per session and save to profile.json."""
    # First pull user_profile to try to get the profile number for gear
    user_profile_number = ""
    try:
        result = browser_fetch(sb, "/userprofile-service/userprofile/user-settings", None)
        if result.get("ok") and result.get("data"):
            data = result["data"]
            user_profile_number = str(
                data.get("userProfileNumber") or data.get("id") or data.get("profileId") or ""
            )
    except Exception:
        pass

    metrics = build_profile_metrics(display_name, user_profile_number)
    print(f"Profile data: Pulling {len(metrics)} items...")
    pad = max(len(name) for name, _, _ in metrics)
    results: dict = {}

    for name, path, params in metrics:
        try:
            result = browser_fetch(sb, path, params or None)
            results[name] = result.get("data") if result.get("ok") else result
            status = "✓" if result.get("ok") else f"✗ HTTP {result.get('status')}"
        except Exception as e:
            results[name] = {"_error": str(e)}
            status = f"✗ {e}"
        print(f"    {status:<4} {name:<{pad}}")

    out_path = DATA_DIR / "profile.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  → {out_path}\n")


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

    # Per-activity detail: iterate over activity IDs from the activities response
    activity_ids = _extract_activity_ids(results.get("activities"))
    if activity_ids:
        n = len(activity_ids)
        print(f"    Fetching detail for {n} activit{'y' if n == 1 else 'ies'}...")
        for aid in activity_ids:
            for det_name, det_path, det_params in build_activity_metrics(str(aid)):
                try:
                    det_result = browser_fetch(sb, det_path, det_params or None)
                    results[det_name] = (
                        det_result.get("data") if det_result.get("ok") else det_result
                    )
                    status = "✓" if det_result.get("ok") else f"✗ HTTP {det_result.get('status')}"
                except Exception as e:
                    results[det_name] = {"_error": str(e)}
                    status = f"✗ {e}"
                print(f"    {status:<4} {det_name:<{pad}}")

    return results


def _extract_activity_ids(activities_data) -> list:
    """Extract activity IDs from the activities API response."""
    if not activities_data:
        return []
    # Response is either a list of activity objects or a dict with a list inside
    if isinstance(activities_data, list):
        items = activities_data
    elif isinstance(activities_data, dict):
        items = activities_data.get("activityList") or activities_data.get("activities") or []
    else:
        return []
    ids = []
    for item in items:
        if isinstance(item, dict):
            aid = item.get("activityId") or item.get("id")
            if aid:
                ids.append(str(aid))
    return ids


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
        "--days",
        type=int,
        default=1,
        help="Number of days to pull from --date (default: 1).",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-pull dates that already have a data file.",
    )
    return parser.parse_args()


def main():
    try:
        from seleniumbase import SB
    except ImportError:
        print("ERROR: seleniumbase not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email or not password:
        if not has_display():
            print("ERROR: No credentials set and no display available for manual login.")
            print("Set GARMIN_EMAIL and GARMIN_PASSWORD in .env or via keyring.")
            sys.exit(1)
        print("No credentials configured — manual browser login will be required.")

    args = parse_args()
    dates = [args.date + timedelta(days=i) for i in range(args.days)]

    xvfb = None
    if needs_virtual_display():
        print("Starting Xvfb...")
        xvfb = start_xvfb()

    browser_bin = None
    if platform.system() == "Windows":
        browser_bin = detect_windows_browser()
        if browser_bin is None:
            print("ERROR: No supported browser found. Install Chrome, Brave, or Edge and retry.")
            sys.exit(1)

    try:
        print("Launching browser...")
        PROFILE_DIR.mkdir(exist_ok=True)
        # headless=False required — UC mode's uc_open_with_reconnect closes and reopens the
        # Chrome window as part of its Cloudflare bypass; headless mode breaks that mechanism.
        sb_kwargs = dict(uc=True, headless=False, xvfb=False, user_data_dir=str(PROFILE_DIR))
        if browser_bin:
            sb_kwargs["binary_location"] = browser_bin
        with SB(**sb_kwargs) as sb:
            ensure_logged_in(sb, email, password)

            print("Getting display name...")
            display_name, uuid = get_display_name(sb)
            if not display_name:
                print("ERROR: Could not retrieve display name — login may have failed.")
                sys.exit(1)
            print(f"Logged in as: {display_name} (uuid={uuid or 'unknown'})\n")

            pull_profile_data(sb, display_name)

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
                    "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
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
