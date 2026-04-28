# garmin-extract

Pull 30+ daily health metrics from Garmin Connect automatically — including on headless servers where every other Garmin library gets blocked by Cloudflare.

## Why this exists

Garmin has no public API for personal health data. Every Python library that tries to authenticate directly (`garminconnect`, `garth`, raw `requests`) gets blocked by Cloudflare's bot protection before the login page even loads.

This project solves the problem by running a **real Chrome browser** (via SeleniumBase's undetected-chromedriver mode). All API calls are executed as JavaScript `fetch()` calls from inside the browser context — Python only orchestrates what the browser does. Cloudflare sees a legitimate browser with a real TLS fingerprint and lets it through.

Once logged in, the browser saves the session to a local profile and reuses it on subsequent runs. Re-authentication is only needed about once every 30 days.

## Features

- **30+ metrics per day** — steps, heart rate, sleep, HRV, stress, body battery, SpO2, respiration, training readiness, nutrition, activities, and more
- **Per-activity detail** — splits, HR zones, power zones, exercise sets, weather
- **One-time profile pull** — devices, personal records, training plans, gear
- **Fetch New** — automatically pulls only the gap between your latest local data and yesterday
- **Historical backfill** from Garmin's bulk data export (`.zip`)
- **CSV export** — `garmin_daily.csv` (daily metrics) and `garmin_activities.csv` (per-workout)
- **Google Drive / Sheets export** — archive raw CSVs to a Drive folder *and / or* populate a live Google Sheet for dashboards and sharing
- **Automatic MFA via Gmail** — reads your Garmin security code from Gmail so session renewals need no human action
- **Scheduled Pulls** — daily unattended pulls via Windows Task Scheduler (GUI) or `cron` on Linux
- **Secure credential storage** — passwords saved to OS keyring by default (Credential Manager on Windows, Keychain on macOS, SecretService on Linux)
- Partial failures are non-fatal — the daily file is written with whatever succeeded
- Idempotent — safe to run multiple times; already-pulled dates are skipped by default

## Install

### Windows

1. Download the latest `garmin-extract-windows-vX.Y.Z.zip` from the [Releases page](https://github.com/ColonelPanicX/garmin-extract/releases)
2. Extract the zip to a folder of your choice (e.g. `C:\Program Files\garmin-extract`)
3. Double-click `garmin-extract.exe`

That's it. Chrome, Brave, or Edge is required — the app detects whichever is installed (preferring Chrome, then Brave, then Edge).

> **Chrome hangs on startup?** Known issue tracked in [#74](https://github.com/ColonelPanicX/garmin-extract/issues/74). Brave and Edge work cleanly as a workaround.

### macOS

*Coming later.* macOS builds are not yet published.

### Headless Linux

Headless Linux requires a one-time setup of prerequisites, then running from source. A packaged Linux build is not yet available.

```bash
# Install Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
    | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable

# Install garmin-extract
git clone https://github.com/ColonelPanicX/garmin-extract.git
cd garmin-extract
uv sync
uv run python -m garmin_extract
```

On first launch, the TUI detects headless Linux and walks you through the remaining prerequisites (Xvfb install, Garmin credentials, Gmail MFA). Because there's no display for a manual login, **all three must be configured** before a pull can run — the preflight gates the **Continue** button until everything is green. The TUI can install Xvfb on apt/dnf/pacman/apk systems; on unrecognized distros, install `xvfb` (or your distro's equivalent) manually.

## First-time setup

The app walks you through setup on first launch. Expected order:

1. **Garmin Credentials** *(optional)* — enter your Garmin email and password. Saved to the OS keyring (encrypted at rest). Skip this if you'd rather log in manually each time.
2. **Gmail MFA** *(optional but strongly recommended)* — Automation → Gmail MFA → Configure. A 3-step wizard walks you through obtaining an OAuth credentials file from Google Cloud Console, authorizing the app, and saving a long-lived token. Once configured, Garmin's email MFA prompts are handled automatically — pulls run fully unattended.
3. **First pull** — Pull Data → Fetch new. On the first pull, the browser opens, you log in (or the app does it for you if you saved credentials), MFA is handled, and a session is saved to `.garmin_browser_profile/`. Subsequent runs reuse that session for ~30 days.

## Daily use

Launch the app and go to **Pull Data**:

- **Fetch new** — pulls every date between your most recent local data and yesterday
- **Yesterday** — just yesterday's data
- **Last 7 days** / **Last 30 days** — common ranges
- **Specific date or range** — enter a start date (and optionally a day count)
- **Full history** — every date between a start date you choose and yesterday
- **Import from Garmin bulk export** — ingest the `.zip` that Garmin emails you if you request your data export
- **Rebuild CSV reports** — regenerate `garmin_daily.csv` and `garmin_activities.csv` from existing local JSON

The **Latest Sync** header at the top of the Pull Data screen shows how many days behind you are at a glance.

## Automation

### Gmail MFA

Automation → Gmail MFA → Configure opens a 3-step wizard. Once configured, the app polls Gmail for the MFA code when Garmin asks for one — no manual input required. The same OAuth token grants access to Google Drive and Sheets.

> **OAuth app publishing:** Google expires refresh tokens after **7 days** when your OAuth consent screen is in *Testing* status. To avoid weekly re-auth, go to Google Cloud Console → APIs & Services → OAuth consent screen → Publishing status → **Publish App**. No Google review is required for personal/internal use. After publishing, refresh tokens last indefinitely. Re-run `setup_gmail_auth.py` (or the in-app wizard) once after publishing to get a long-lived token.

### Scheduled Pulls (Windows)

Automation → Scheduled Pulls → Configure:

- Pick a daily time
- Optionally tick **Archive raw CSV files to Google Drive** and / or **Populate Google Sheet with data**
- Save

The app creates a Windows Task Scheduler entry that runs `garmin-extract --pull` at the chosen time. Verify it in Task Scheduler under the name `garmin-extract-daily`.

### Scheduled Pulls (Linux)

Add the shell wrapper to your crontab:

```cron
0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh
```

The script supports `--push-drive` / `--push-sheets` / `--push-both` flags to bundle exports with the pull.

### Google Drive / Sheets export

Automation → Google Drive / Sheets. Two complementary exports — pick the one that matches your use case:

| Use case | Pick |
|---|---|
| Backups you can download later | **Upload CSVs to Drive** (archival) |
| Bookmark one Sheet to see today's data | **Sync to Sheets** (live dashboard) |
| Share a live view with someone | **Sync to Sheets** |
| Build pivot tables / charts that auto-update | **Sync to Sheets** |
| Export to another tool that reads CSV | **Upload CSVs to Drive** |
| Both, for belt-and-suspenders | **Both** |

- **Upload CSVs to Drive** — uploads `garmin_daily.csv` and `garmin_activities.csv` as raw files into a folder you choose. Each run overwrites the files in place. Clicking a CSV in Drive opens a read-only Sheets preview; converting it to an editable Sheet produces a one-off copy that won't update on future pulls.
- **Sync to Sheets** — writes the data into a persistent `Garmin Data` spreadsheet with `Daily` and `Activities` tabs. The URL stays stable run after run — only the cells change. Charts and formatting you add keep updating.

Configure once, run on demand from the Automation page, or bundle with Scheduled Pulls for fully unattended export.

## Troubleshooting

- **Chrome hangs on startup with "failed to close window in 20 seconds"** — known issue ([#74](https://github.com/ColonelPanicX/garmin-extract/issues/74)). Workaround: use Brave or Edge. The app's browser detection order is Chrome → Brave → Edge; installing Brave alongside Chrome doesn't fix it (Chrome wins detection), but uninstalling Chrome falls through to Brave.
- **Login keeps failing after a long time** — your Garmin session has expired (happens roughly every 30 days). The app will re-authenticate automatically if credentials and Gmail MFA are configured. If not, the browser will open for manual login.
- **Gmail MFA doesn't fire** — make sure the OAuth token actually has the `gmail.readonly` scope. Re-run the Gmail MFA wizard if in doubt. The Automation page shows the current Gmail MFA status on mount.
- **`invalid_grant: Token has been expired or revoked`** — your OAuth refresh token expired. This happens every 7 days when the Google Cloud OAuth consent screen is in *Testing* status. Fix: publish the app (Google Cloud Console → OAuth consent screen → Publish App), then re-run the Gmail MFA wizard once to get a long-lived token.
- **Metrics start coming back empty or 404** — Garmin's internal API endpoints are reverse-engineered from the Connect web app and occasionally change with app updates. If this happens, the endpoints will need to be re-mapped using Chrome DevTools → Network tab while browsing Garmin Connect.

More detail in the [Troubleshooting wiki page](https://github.com/ColonelPanicX/garmin-extract/wiki/Troubleshooting).

## Known limitations

- **Tested primarily on Windows and Ubuntu 24.04.** macOS is not yet officially supported.
- Requires a Garmin account with **email MFA enabled** (this is standard on all accounts).
- The API endpoints are **reverse-engineered from the Garmin Connect SPA** and may change with Garmin app updates.

## Changelog

Full release history is on the [Changelog wiki page](https://github.com/ColonelPanicX/garmin-extract/wiki/Changelog).

## License

MIT
