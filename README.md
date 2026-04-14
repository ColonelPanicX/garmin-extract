# garmin-extract

Pull 30+ daily health metrics from Garmin Connect automatically — including on headless servers where every other Garmin library gets blocked by Cloudflare.

## Why this exists

Garmin has no public API for personal health data. Every Python library that tries to authenticate directly (`garminconnect`, `garth`, raw `requests`) gets blocked by Cloudflare's bot protection before the login page even loads.

This project solves the problem by running a **real Chrome browser** (via SeleniumBase's undetected-chromedriver mode). All API calls are executed as JavaScript `fetch()` calls from inside the browser context — Python only orchestrates what the browser does. Cloudflare sees a legitimate browser with a real TLS fingerprint and lets it through. On headless Linux servers, Chrome runs inside a virtual framebuffer (Xvfb); on desktop systems it runs directly.

Once logged in, Chrome saves the session to a local browser profile and reuses it on subsequent runs. Re-authentication is only needed about once every 30 days.

## Features

- **Interactive TUI** — a full terminal interface that walks you through setup, data pulls, and automation without touching the command line
- **30+ metrics per day** — steps, heart rate, sleep, HRV, stress, body battery, SpO2, respiration, training readiness, nutrition, activities, and more
- **Per-activity detail** — 8 additional endpoints per workout (splits, HR zones, power zones, exercise sets, weather, and more)
- **One-time profile pull** — devices, personal records, training plans, and gear saved to `profile.json`
- **Historical backfill** from Garmin's bulk data export (`.zip` file)
- **CSV export** — `garmin_daily.csv` (daily metrics) and `garmin_activities.csv` (per-workout)
- Partial failures are non-fatal — the daily file is written with whatever succeeded
- Idempotent — safe to run multiple times; already-pulled dates are skipped by default

**Optional automation:**
- Fully automatic MFA via Gmail API — the tool reads your Garmin security code from Gmail so session renewals require no human action
- Scheduled daily pulls configured from inside the TUI

## Requirements

- **Windows, macOS, or Linux** (headless or desktop) — tested on Ubuntu 24.04
- Google Chrome installed
- `xvfb` on headless Linux only (not needed on Windows, macOS, or Linux with a display)
- Python 3.12+
- A Garmin account with email MFA enabled (standard on all accounts)
- A Gmail account for MFA automation (optional but strongly recommended for unattended operation)

## Quickstart

### 1. Install Chrome

**Linux:**
```bash
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
    | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable
```

**Headless Linux only** — also install Xvfb:
```bash
sudo apt install -y xvfb
```

**Windows / macOS:** Download from [google.com/chrome](https://www.google.com/chrome/).

### 2. Clone and install

```bash
git clone https://github.com/ColonelPanicX/garmin-extract.git
cd garmin-extract
```

**With [uv](https://docs.astral.sh/uv/) (recommended):**
```bash
uv sync
uv run python -m garmin_extract
```

**With pip:**
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
python -m garmin_extract
```

### 3. Follow the TUI

The interactive TUI is the recommended way to get started. On launch you'll land on the main menu:

```
  garmin-extract  v1.1.0
  Automated Garmin Connect data pipeline

  ┌─────────────────────────────────────────────────────┐
  │   [1]  Initial Setup                                │
  │   [2]  Pull Data                                    │
  │   [3]  Automation                                   │
  └─────────────────────────────────────────────────────┘
```

**First-time setup order:**

1. **Initial Setup → Prerequisites** — verifies Chrome, Xvfb (Linux), Python version, and packages. Installs missing prerequisites on Linux.
2. **Initial Setup → Garmin Credentials** — enter your Garmin email and password. Saved to `.env`.
3. **Initial Setup → Gmail OAuth** *(optional but recommended)* — authorizes the Gmail API so MFA codes are fetched automatically. See [Gmail MFA automation](#gmail-mfa-automation).
4. **Pull Data** — choose a date range and pull. On the first pull, Chrome launches, logs in, handles MFA, and saves a session to `.garmin_browser_profile/`. Subsequent runs reuse that session.

### 4. Schedule automatic pulls *(optional)*

From the main menu, go to **Automation → Scheduled Pulls**. Press `i` to enable a daily pull at 6:00 AM (default), or `e` to choose a different hour. Output is logged to `/tmp/garmin-pull.log`.

Alternatively, add the shell wrapper directly to your crontab:
```
0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh
```

## Usage

### TUI

```bash
uv run python -m garmin_extract      # recommended
python garmin_extract.py             # alternate shim
```

### CLI (scripting / headless)

```bash
uv run python -m garmin_extract --no-tui   # print menu, no TUI
```

### Daily puller (direct)

```bash
python pullers/garmin.py                               # yesterday (default)
python pullers/garmin.py --date 2026-03-01             # specific date
python pullers/garmin.py --date 2026-03-01 --days 30   # 30-day range
python pullers/garmin.py --no-skip                     # re-pull existing dates
```

### Historical backfill

Request your data export from **Garmin Connect → Profile → Account → Your Garmin Data**. The export arrives within 24–48 hours as a `.zip` file.

```bash
python pullers/garmin_import_export.py path/to/export.zip
python pullers/garmin_import_export.py path/to/export.zip --no-skip
```

Reads six data categories from the zip and writes one JSON file per day. Skips dates that already have a live-pulled file (which contain richer data).

### CSV export

```bash
python reports/build_garmin_csvs.py
python reports/build_garmin_csvs.py --since 2025-01-01
```

Outputs:
- `reports/garmin_daily.csv` — one row per day (steps, HR, sleep, stress, HRV, body battery, SpO2, training load, nutrition, lifestyle logging, and more)
- `reports/garmin_activities.csv` — one row per workout (name, type, duration, distance, HR, power, etc.)

## Gmail MFA automation

When Garmin requires an MFA code (approximately every 30 days), this module polls your Gmail inbox automatically, finds the security code email, and submits the code to the browser — no human required.

### Setup via TUI

Go to **Initial Setup → Gmail OAuth** and follow the on-screen steps:

1. Place your `google_credentials.json` (downloaded from Google Cloud Console) in the project root
2. Select **Authorize Gmail** — an authorization URL is displayed inside the dialog
3. Open the URL in any browser (does not need to be on the same machine), authorize, and paste the code back
4. Done — a token is saved to `.google_token.json` and does not expire unless revoked

**To create credentials:** Go to [console.cloud.google.com](https://console.cloud.google.com) → New project → Enable Gmail API → Credentials → OAuth 2.0 Client ID → Desktop app → Download JSON.

### Setup via CLI

```bash
python scripts/setup_gmail_auth.py
```

### Fallback

If Gmail automation is not configured (or fails), the TUI shows an MFA dialog prompting you to enter the code manually. At the CLI, the pipeline prints:

```
MFA REQUIRED — check your email
Run: echo YOUR_CODE > /path/to/.mfa_code
Waiting up to 5 minutes...
```

### Verify status

Go to **Automation → Gmail MFA** to see whether the automation is active, partial, or unconfigured — and what to do if something is wrong.

## Data output

### JSON format

Each pull writes `data/garmin/YYYY-MM-DD.json` containing all metrics as top-level keys, plus a `_meta` block:

```json
{
  "stats":              { ... },
  "sleep":              { ... },
  "heart_rates":        { ... },
  "hrv":                "EMPTY",
  "activities":         [ ... ],
  "_meta": {
    "date":         "2026-04-07",
    "pulled_at":    "2026-04-08T06:01:23Z",
    "source":       "garmin-browser",
    "display_name": "<garmin-user-uuid>",
    "uuid":         ""
  }
}
```

Failed metrics are recorded inline rather than aborting the pull:
```json
{ "training_readiness": { "ok": false, "status": 404, "data": null } }
```

### Metrics pulled (per date)

| Key | Description |
|---|---|
| `stats` | 91-field daily summary: steps, calories, active time, HR zones, stress summary, SpO2 |
| `heart_rates` | Full 24h heart rate timeline with min/max/resting |
| `sleep` | Sleep stages (deep/light/REM/awake seconds), scores, SpO2, respiration, HR |
| `hrv` | Overnight HRV weekly average and last-night value |
| `stress` | Full stress timeline and body battery values |
| `body_battery` | Daily body battery start/end/high/low stats |
| `activities` | Logged workout activities |
| `spo2` | Blood oxygen: daily average, daily low, sleep average |
| `respiration` | Respiration rate: waking average, sleep average, intraday timeline |
| `training_readiness` | Training readiness score and contributing factors |
| `training_status` | Training load balance, VO2Max trend, status label |
| `fitness_age` | Calculated fitness age vs. chronological age |
| `hydration` | Daily hydration intake vs. goal |
| `nutrition_food_log` | Food log entries for the day |
| `nutrition_meals` | Meal-level nutrition summary |
| `menstrual_cycle` | Menstrual cycle tracking data |
| `lifestyle` | Lifestyle behavior logging (alcohol, caffeine, sleep aids, etc.) |
| ...and more | Steps, floors, intensity minutes, resting HR, body composition, blood pressure, etc. |

**Per-activity detail** (pulled for each logged workout): splits, typed splits, split summaries, HR time in zones, power time in zones, exercise sets, weather.

**One-time profile pull** (per session): devices, user profile, personal records, training plans, workouts, gear → `data/garmin/profile.json`.

## Known limitations

- Tested on **Ubuntu 24.04**. Windows and macOS are supported but less tested.
- Requires a Garmin account with **email MFA enabled** (this is standard on all accounts).
- The API endpoints are **reverse-engineered from the Garmin Connect SPA**. They may change with Garmin app updates. If metrics start returning 404/empty responses, the endpoints may need to be re-mapped using Chrome DevTools → Network tab.
- Google Drive / Sheets export is not yet implemented (planned for a future release).

## Changelog

### v1.1.0 — 2026-04-14 — Full TUI, expanded API, setup wizard, automation

**Full Textual TUI** replacing the print menu as the primary interface:
- `MainMenuScreen` → `DataPullScreen` → `PullProgressScreen` with live per-metric or per-day progress depending on date range
- MFA modal inside the TUI — prompts for a code when Gmail automation is not available
- `Initial Setup` screen with prerequisite checks, Garmin credential management, and Gmail OAuth wizard (including in-dialog URL display for headless environments)
- `Automation` screen with Gmail MFA status view and `Scheduled Pulls` manager (enable, disable, change pull time)

**Expanded Garmin API coverage:**
- Added nutrition (food log, meals), menstrual cycle tracking
- Per-activity detail: 8 endpoints per logged workout (splits, HR/power zones, exercise sets, weather)
- One-time profile pull per session: devices, personal records, training plans, workouts, gear → `profile.json`

**Bug fixes:**
- Fixed Python output buffering (`-u` flag) that caused subprocess output to stall in the TUI
- Fixed `call_from_thread` usage in Textual screen workers
- Fixed Gmail MFA CSS hex color false-match (`#000000` no longer matched as a security code)

---

### 2026-04-09 — CSV normalization and lifestyle logging fix

**Human-readable column headers:** All columns in `garmin_daily.csv` and `garmin_activities.csv` now use plain English names with units in parentheses (e.g. `Resting Heart Rate (bpm)`, `Deep Sleep (seconds)`, `Floors Ascended (meters)`).

**Lifestyle logging fix:** The lifestyle behavior extraction was reading from the wrong part of the JSON structure and silently producing empty columns. It now correctly reads from `lifestyle.dailyLogsReport[]`. Logged behaviors appear as `Yes`/`No` per day; behaviors not logged on a given day show `N/A`. Quantity-tracked behaviors (e.g. Alcohol) also get an `(amount)` column with the summed value. Behavior columns are discovered dynamically from the user's actual data — no behavior names are hardcoded.

**Sleep timestamps:** `Sleep Start (UTC)` and `Sleep End (UTC)` were previously stored as raw millisecond epoch values. They are now converted to ISO 8601 strings (`YYYY-MM-DDTHH:MM:SSZ`).

---

### 2026-04-08 — Gmail MFA false-match and re-submission loop fixes

Two bugs were found and fixed in production after the initial deployment.

#### Gmail MFA: CSS hex color false-match (`pullers/_gmail_mfa.py`)

**Symptom:** The Gmail MFA poller was extracting `000000` from old Garmin emails instead of the real 6-digit code, then submitting it repeatedly.

**Root causes:**
1. `_get_message_text()` was returning the HTML part of the email before the plain-text part. Garmin emails include `#000000` (black CSS color) in their HTML body, and the fallback `\b(\d{6})\b` regex matched the hex digits.
2. The poll loop had no memory of which emails it had already processed — so if the first poll returned a bad email, every subsequent poll would find and re-process it.

**Fixes:**
- `_get_message_text()` now explicitly prefers `text/plain` over `text/html`.
- The fallback regex is now `(?<!#)\b(\d{6})\b` — a negative lookbehind that excludes CSS hex colors.
- Codes where all digits are identical (`000000`, `111111`, etc.) are rejected outright.
- `wait_for_mfa_gmail()` maintains a `seen_ids` set — each message ID is only processed once per poll session.
- The `after:` Gmail search filter now uses the exact script start time with no buffer, preventing stale emails from surfacing.

#### MFA re-submission loop (`pullers/garmin.py`)

**Symptom:** After a valid MFA code was submitted, the login poll loop continued iterating. On slow redirects, it found the MFA input again and called `wait_for_mfa()` a second time — submitting a fresh (and wrong) code. Combined with the Gmail bug above, this produced 8+ failed submissions per login attempt.

**Fix:** Both MFA code paths (URL-based `/mfa` detection and selector-based detection) now wait up to 15 seconds for the browser to redirect away from the MFA page before continuing. A `break` after submission ensures `wait_for_mfa()` is called at most once per login attempt.

**Verified in production:** Garmin pull for 2026-04-08 completed successfully. MFA code `184037` was extracted from Gmail on the first try, login completed in a single pass, and all 25 metrics were pulled.

## License

MIT
