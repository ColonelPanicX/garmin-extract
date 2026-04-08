# garmin-extract

Pull 25 daily health metrics from Garmin Connect automatically — including on headless servers where every other Garmin library gets blocked by Cloudflare.

## Why this exists

Garmin has no public API for personal health data. Every Python library that tries to authenticate directly (`garminconnect`, `garth`, raw `requests`) gets blocked by Cloudflare's bot protection before the login page even loads.

This project solves the problem by running a **real Chrome browser** (via SeleniumBase's undetected-chromedriver mode). All API calls are executed as JavaScript `fetch()` calls from inside the browser context — Python only orchestrates what the browser does. Cloudflare sees a legitimate browser with a real TLS fingerprint and lets it through. On headless Linux servers, Chrome runs inside a virtual framebuffer (Xvfb); on desktop systems it runs directly.

Once logged in, Chrome saves the session to a local browser profile and reuses it on subsequent runs. Re-authentication is only needed about once every 30 days.

## Features

- **25 daily health metrics** pulled from the Garmin Connect SPA's live API endpoints
- **Historical backfill** from Garmin's bulk data export (`.zip` file)
- **CSV export** — `garmin_daily.csv` (65 daily columns) and `garmin_activities.csv` (per-workout)
- Partial failures are non-fatal — the daily file is written with whatever succeeded
- Idempotent — safe to run multiple times; already-pulled dates are skipped by default

**Optional automation features** (see [Configure Automation](#configure-automation)):
- Fully automatic MFA via Gmail API — the tool reads your Garmin security code from Gmail so session renewals require no human action
- Google Sheets integration — populates Drive-hosted spreadsheets by year and month
- Cron / Task Scheduler setup for daily unattended pulls

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
sudo apt --fix-broken install -y
```

**Headless Linux only** — also install Xvfb:
```bash
sudo apt install -y xvfb
```

**Windows / macOS:** Download from [google.com/chrome](https://www.google.com/chrome/).

### 2. Clone and install

```bash
git clone https://github.com/your-username/garmin-extract.git
cd garmin-extract

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the interactive menu

```bash
python garmin_extract.py
```

On first run (no `.env` present), you'll see:

```
  Looks like your first run — .env not found.

  Suggested setup order:
    1  Check prerequisites
    2  Configure Garmin credentials
    3  Set up Gmail MFA  (recommended)
    4  Pull your first day of data
```

Run **1** to verify your environment, **2** to enter your Garmin credentials, **3** to configure Gmail MFA (optional but recommended for unattended pulls), then **4** to pull data.

On the first pull, Chrome launches, logs in to Garmin, handles MFA, and saves a persistent browser session to `.garmin_browser_profile/`. Subsequent runs reuse that session and skip login entirely. Output is written to `data/garmin/YYYY-MM-DD.json`.

### 4. Automate daily pulls

**Linux / macOS (cron):**
```cron
0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh
```
The shell wrapper auto-detects its own location — no hardcoded paths. Logs go to `/tmp/garmin-pull.log`.

**Windows:** Use Task Scheduler to run `python pullers\garmin.py` at your preferred time.

## Usage

### Daily puller

```bash
python pullers/garmin.py                          # yesterday (default)
python pullers/garmin.py --date 2026-03-01        # specific date
python pullers/garmin.py --date 2026-03-01 --days 30  # 30-day range from date
python pullers/garmin.py --no-skip                # re-pull dates that already exist
```

### Historical backfill

Request your data export from **Garmin Connect → Profile → Account → Your Garmin Data**. The export arrives within 24–48 hours as a `.zip` file.

```bash
python pullers/garmin_import_export.py path/to/export.zip
python pullers/garmin_import_export.py path/to/export.zip --no-skip  # overwrite existing
```

This reads six data categories from the zip and writes one JSON file per day. Skips dates that already have a live-pulled file (which contain richer data).

### CSV export

```bash
python reports/build_garmin_csvs.py
python reports/build_garmin_csvs.py --since 2025-01-01
```

Outputs:
- `reports/garmin_daily.csv` — one row per day (steps, HR, sleep, stress, HRV, body battery, SpO2, training, lifestyle logging, and more)
- `reports/garmin_activities.csv` — one row per workout (name, type, duration, distance, HR, power, etc.)

The script handles both live-pull and export-import JSON formats transparently.

## Gmail MFA automation

When Garmin requires an MFA code (approximately every 30 days), this module polls your Gmail inbox automatically, finds the security code email, and submits the code to the browser — no human required.

### Setup

**Step 1:** Create a Google Cloud project and OAuth 2.0 credentials:

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project
3. Enable the **Gmail API**, **Google Sheets API**, and **Google Drive API**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → **Desktop app**
5. Download the JSON file and save it as `google_credentials.json` in the project root

**Step 2:** Run the one-time auth setup:

```bash
python scripts/setup_gmail_auth.py
```

This prints a Google authorization URL. Open it in any browser (does not need to be on the same machine), authorize the requested scopes, then paste the resulting code back when prompted. A token is saved to `.google_token.json`.

**Step 3:** Done. The token contains a refresh token that does not expire unless explicitly revoked.

### Fallback

If Gmail automation is not configured (or fails), the pipeline falls back to a file-based method:

```
MFA REQUIRED — check your email
Run: echo YOUR_CODE > /path/to/.mfa_code
Waiting up to 5 minutes...
```

Write the code to the file and the pipeline continues.

## Google Sheets (optional)

`reports/build_garmin_sheets.py` creates year-per-spreadsheet, month-per-tab Google Sheets populated from the CSV exports.

```bash
python reports/build_garmin_sheets.py              # all years
python reports/build_garmin_sheets.py --year 2026  # specific year
python reports/build_garmin_sheets.py --rebuild    # delete and recreate existing sheets
```

Requires `GOOGLE_DRIVE_FOLDER_ID` set in `.env` (the folder ID from a Google Drive URL) and the Gmail MFA setup completed (same Google credentials are reused).

## Data output

### JSON format

Each pull writes `data/garmin/YYYY-MM-DD.json` containing all 25 metrics as top-level keys, plus a `_meta` block:

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

### Metrics pulled

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
| `lifestyle` | Lifestyle behavior logging (alcohol, caffeine, sleep aids, etc.) |
| ...and 11 more | Steps, floors, intensity minutes, resting HR, body composition, blood pressure, etc. |

## Known limitations

- Tested on **Ubuntu 24.04**. Windows and macOS are supported but less tested. On headless Linux, Xvfb is required and detected automatically.
- Requires a Garmin account with **email MFA enabled** (this is standard on all accounts).
- The API endpoints are **reverse-engineered from the Garmin Connect SPA**. They may change with Garmin app updates. If metrics start returning 404/empty responses, the endpoints may need to be re-mapped using Chrome DevTools → Network tab.
- The `garminconnect` Python library (cyberjunky) added a new mobile SSO OAuth flow in April 2026. If it can bypass Cloudflare without a real browser, it could replace the entire Xvfb/Chrome/SeleniumBase stack. This is under evaluation — the browser-based approach remains production until confirmed.

## License

MIT
