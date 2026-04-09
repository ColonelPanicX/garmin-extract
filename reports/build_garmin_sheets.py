#!/usr/bin/env python3
"""
Build Google Sheets from Garmin CSV exports.

Structure:
  - One spreadsheet per year: "Garmin YYYY"
  - One tab per month: "January", "February", etc.
  - One tab for activities per month: "January Activities"
  - Annual Summary tab aggregating all months

All sheets created inside the specified Drive folder.

Usage:
    python reports/build_garmin_sheets.py [--year YYYY] [--rebuild]

Options:
    --year YYYY   Only process a specific year (default: all years)
    --rebuild     Delete and recreate existing sheets (default: skip existing)
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT          = Path(__file__).parent.parent
TOKEN_FILE    = ROOT / ".google_token.json"
CREDS_FILE    = ROOT / "google_credentials.json"
DAILY_CSV     = ROOT / "reports" / "garmin_daily.csv"
ACTIVITIES_CSV = ROOT / "reports" / "garmin_activities.csv"
FOLDER_ID     = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Column display names for daily sheet
DAILY_HEADERS = [
    ("date",                  "Date"),
    ("source",                "Source"),
    ("steps",                 "Steps"),
    ("step_goal",             "Step Goal"),
    ("distance_miles",        "Distance (mi)"),
    ("calories_total",        "Calories Total"),
    ("calories_active",       "Calories Active"),
    ("calories_bmr",          "BMR Calories"),
    ("active_seconds",        "Active Time (s)"),
    ("highly_active_seconds", "Highly Active (s)"),
    ("intensity_moderate_min","Moderate Intensity (min)"),
    ("intensity_vigorous_min","Vigorous Intensity (min)"),
    ("floors_up_m",           "Floors Up (m)"),
    ("floors_down_m",         "Floors Down (m)"),
    ("hr_resting",            "Resting HR"),
    ("hr_min",                "HR Min"),
    ("hr_max",                "HR Max"),
    ("stress_avg",            "Stress Avg"),
    ("stress_max",            "Stress Max"),
    ("stress_rest_seconds",   "Stress Rest (s)"),
    ("stress_low_seconds",    "Stress Low (s)"),
    ("stress_med_seconds",    "Stress Med (s)"),
    ("stress_high_seconds",   "Stress High (s)"),
    ("battery_start",         "Body Battery Start"),
    ("battery_end",           "Body Battery End"),
    ("battery_high",          "Body Battery High"),
    ("battery_low",           "Body Battery Low"),
    ("spo2_avg",              "SpO2 Avg"),
    ("spo2_low",              "SpO2 Low"),
    ("spo2_sleep_avg",        "SpO2 Sleep Avg"),
    ("resp_waking_avg",       "Respiration Waking Avg"),
    ("resp_high",             "Respiration High"),
    ("resp_low",              "Respiration Low"),
    ("sleep_start_utc",       "Sleep Start (UTC)"),
    ("sleep_end_utc",         "Sleep End (UTC)"),
    ("sleep_total_hhmm",      "Sleep Total"),
    ("sleep_total_seconds",   "Sleep Total (s)"),
    ("sleep_deep_seconds",    "Sleep Deep (s)"),
    ("sleep_light_seconds",   "Sleep Light (s)"),
    ("sleep_rem_seconds",     "Sleep REM (s)"),
    ("sleep_awake_seconds",   "Sleep Awake (s)"),
    ("sleep_awake_count",     "Sleep Awake Count"),
    ("sleep_restless_moments","Sleep Restless Moments"),
    ("sleep_stress_avg",      "Sleep Stress Avg"),
    ("sleep_respiration_avg", "Sleep Respiration Avg"),
    ("sleep_spo2_avg",        "Sleep SpO2 Avg"),
    ("sleep_spo2_low",        "Sleep SpO2 Low"),
    ("sleep_hr_avg",          "Sleep HR Avg"),
    ("sleep_score",           "Sleep Score"),
    ("sleep_score_deep",      "Sleep Score Deep"),
    ("sleep_score_rem",       "Sleep Score REM"),
    ("sleep_score_recovery",  "Sleep Score Recovery"),
    ("sleep_score_duration",  "Sleep Score Duration"),
    ("hrv_weekly_avg",        "HRV Weekly Avg"),
    ("hrv_last_night",        "HRV Last Night"),
    ("hrv_status",            "HRV Status"),
    ("hydration_ml",          "Hydration (ml)"),
    ("hydration_goal_ml",     "Hydration Goal (ml)"),
    ("hydration_sweat_ml",    "Sweat Loss (ml)"),
    ("vo2max",                "VO2 Max"),
    ("training_load",         "Training Load"),
    ("training_status",       "Training Status"),
    ("training_readiness",    "Training Readiness"),
    ("fitness_age",           "Fitness Age"),
    ("chronological_age",     "Chronological Age"),
    # Lifestyle logging columns are dynamic — behavior names vary per user
    # and are discovered at runtime by build_garmin_csvs.py.
    # These will be added here when Sheets export is revisited.
]

ACTIVITY_HEADERS = [
    ("date",             "Date"),
    ("activity_id",      "Activity ID"),
    ("name",             "Name"),
    ("type",             "Type"),
    ("sport",            "Sport"),
    ("start_local",      "Start Time"),
    ("duration_seconds", "Duration (s)"),
    ("distance_miles",   "Distance (mi)"),
    ("calories",         "Calories"),
    ("avg_hr",           "Avg HR"),
    ("max_hr",           "Max HR"),
    ("avg_speed",        "Avg Speed"),
    ("steps",            "Steps"),
    ("avg_cadence",      "Avg Cadence"),
    ("avg_power",        "Avg Power (W)"),
    ("elevation_gain_m", "Elevation Gain (m)"),
    ("source",           "Source"),
]

# Summary columns: (display_name, csv_field, aggregation)
# aggregation: "avg", "sum", "last", "count_nonempty"
SUMMARY_COLS = [
    ("Steps Avg",          "steps",                 "avg"),
    ("Distance Avg (mi)",  "distance_miles",        "avg"),
    ("Calories Avg",       "calories_total",        "avg"),
    ("Resting HR Avg",     "hr_resting",            "avg"),
    ("Stress Avg",         "stress_avg",            "avg"),
    ("Body Battery End Avg","battery_end",           "avg"),
    ("Sleep Total Avg",    "sleep_total_hhmm",      "sleep_avg"),
    ("Sleep Score Avg",    "sleep_score",           "avg"),
    ("HRV Avg",            "hrv_last_night",        "avg"),
    ("VO2 Max (last)",     "vo2max",                "last"),
    ("Active Days",        "steps",                 "count_nonempty"),
    ("Activities",         "_activities",           "count"),
]


def _build_service(api, version):
    """Build a Google API service using stored token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(TOKEN_FILE) as f:
        tok = json.load(f)

    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri"),
        client_id=tok.get("client_id"),
        client_secret=tok.get("client_secret"),
        scopes=tok.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tok["token"] = creds.token
        TOKEN_FILE.write_text(json.dumps(tok, indent=2))

    return build(api, version, credentials=creds)


def load_daily():
    """Returns dict: year -> month -> [row_dict]"""
    by_year_month = defaultdict(lambda: defaultdict(list))
    with open(DAILY_CSV) as f:
        for row in csv.DictReader(f):
            d = row["date"]
            try:
                dt = datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
            by_year_month[dt.year][dt.month].append(row)
    return by_year_month


def load_activities():
    """Returns dict: year -> month -> [row_dict]"""
    by_year_month = defaultdict(lambda: defaultdict(list))
    with open(ACTIVITIES_CSV) as f:
        for row in csv.DictReader(f):
            d = row["date"]
            try:
                dt = datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
            by_year_month[dt.year][dt.month].append(row)
    return by_year_month


def _safe_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def _hhmm_to_minutes(v):
    """Convert 'h:mm' string to total minutes."""
    if not v or ":" not in v:
        return None
    try:
        h, m = v.split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _minutes_to_hhmm(total_minutes):
    if total_minutes is None:
        return ""
    h = int(total_minutes) // 60
    m = int(total_minutes) % 60
    return f"{h}:{m:02d}"


def _aggregate(rows, field, method):
    if method == "count":
        return str(len(rows))
    if method == "count_nonempty":
        return str(sum(1 for r in rows if _safe_float(r.get(field)) is not None))
    if method == "last":
        vals = [_safe_float(r.get(field)) for r in rows]
        vals = [v for v in vals if v is not None]
        return str(vals[-1]) if vals else ""
    if method == "sleep_avg":
        mins = [_hhmm_to_minutes(r.get(field)) for r in rows]
        mins = [m for m in mins if m is not None]
        if not mins:
            return ""
        return _minutes_to_hhmm(sum(mins) / len(mins))
    # avg or sum
    vals = [_safe_float(r.get(field)) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return ""
    result = sum(vals) / len(vals) if method == "avg" else sum(vals)
    return f"{result:.1f}" if result != int(result) else str(int(result))


def build_summary_data(daily_by_month, activities_by_month):
    """Build Annual Summary rows: one row per month."""
    header = ["Month"] + [col[0] for col in SUMMARY_COLS]
    rows = [header]
    for month_num, month_name in enumerate(MONTHS, 1):
        daily_rows = daily_by_month.get(month_num, [])
        act_rows   = activities_by_month.get(month_num, [])
        if not daily_rows and not act_rows:
            continue
        row = [month_name]
        for _, field, method in SUMMARY_COLS:
            if field == "_activities":
                row.append(_aggregate(act_rows, field, "count"))
            else:
                row.append(_aggregate(daily_rows, field, method))
        rows.append(row)
    return rows


def find_existing_sheet(drive_svc, name):
    """Return file ID if a sheet with this name exists in the folder, else None."""
    q = (
        f"name='{name}' and '{FOLDER_ID}' in parents "
        f"and mimeType='application/vnd.google-apps.spreadsheet' "
        f"and trashed=false"
    )
    res = drive_svc.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def create_spreadsheet(drive_svc, sheets_svc, name):
    """Create a new spreadsheet in the folder and return its ID."""
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [FOLDER_ID],
    }
    f = drive_svc.files().create(body=meta, fields="id").execute()
    return f["id"]


def _header_format():
    return {
        "backgroundColor": {"red": 0.2, "green": 0.4, "blue": 0.7},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "horizontalAlignment": "CENTER",
    }


def write_sheet_data(sheets_svc, spreadsheet_id, sheet_id, sheet_title, data_rows):
    """Write rows to a specific sheet tab, applying header formatting."""
    if not data_rows:
        return

    # Write values
    body = {"values": data_rows}
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_title}'!A1",
        valueInputOption="RAW",
        body=body,
    ).execute()

    # Format header row
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {"userEnteredFormat": _header_format()},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def setup_year_spreadsheet(sheets_svc, spreadsheet_id, year, daily_by_month, act_by_month):
    """
    Populate a year's spreadsheet:
    - Rename Sheet1 to "Annual Summary"
    - Add monthly tabs (daily + activities)
    - Write data to each tab
    """
    # Get current sheet list
    meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"]
                for s in meta["sheets"]}

    # Build desired tab list: Annual Summary + months with data
    months_with_data = sorted(
        set(daily_by_month.keys()) | set(act_by_month.keys())
    )
    desired_tabs = ["Annual Summary"]
    for m in months_with_data:
        desired_tabs.append(MONTHS[m - 1])
        desired_tabs.append(f"{MONTHS[m - 1]} Activities")

    # Rename Sheet1 → Annual Summary if needed
    requests = []
    if "Sheet1" in existing and "Annual Summary" not in existing:
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": existing["Sheet1"], "title": "Annual Summary"},
                "fields": "title",
            }
        })

    # Add missing tabs
    for tab in desired_tabs:
        if tab not in existing and not (tab == "Annual Summary" and "Sheet1" in existing):
            requests.append({"addSheet": {"properties": {"title": tab}}})

    if requests:
        res = sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
        # Refresh meta
        meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing = {s["properties"]["title"]: s["properties"]["sheetId"]
                    for s in meta["sheets"]}

    # Write Annual Summary
    summary_data = build_summary_data(daily_by_month, act_by_month)
    write_sheet_data(sheets_svc, spreadsheet_id,
                     existing["Annual Summary"], "Annual Summary", summary_data)
    print(f"  [OK] Annual Summary ({len(summary_data)-1} months)")

    # Write monthly tabs
    for m in months_with_data:
        month_name = MONTHS[m - 1]

        # Daily tab
        daily_rows = daily_by_month.get(m, [])
        if daily_rows:
            header = [display for _, display in DAILY_HEADERS]
            keys   = [key for key, _ in DAILY_HEADERS]
            rows   = [header] + [[r.get(k, "") for k in keys] for r in daily_rows]
            write_sheet_data(sheets_svc, spreadsheet_id,
                             existing[month_name], month_name, rows)
            print(f"  [OK] {month_name} ({len(daily_rows)} days)")

        # Activities tab
        act_tab = f"{month_name} Activities"
        act_rows = act_by_month.get(m, [])
        if act_rows:
            header = [display for _, display in ACTIVITY_HEADERS]
            keys   = [key for key, _ in ACTIVITY_HEADERS]
            rows   = [header] + [[r.get(k, "") for k in keys] for r in act_rows]
            write_sheet_data(sheets_svc, spreadsheet_id,
                             existing[act_tab], act_tab, rows)
            print(f"  [OK] {act_tab} ({len(act_rows)} activities)")

        time.sleep(0.5)  # stay under Sheets API rate limits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Only process this year")
    parser.add_argument("--rebuild", action="store_true",
                        help="Skip existing spreadsheets (default: skip)")
    args = parser.parse_args()

    if not FOLDER_ID:
        print("ERROR: GOOGLE_DRIVE_FOLDER_ID not set. Add it to .env")
        sys.exit(1)

    print("Loading CSVs...")
    daily      = load_daily()
    activities = load_activities()

    years = sorted(daily.keys() | activities.keys())
    if args.year:
        years = [y for y in years if y == args.year]
    if not years:
        print("No data found.")
        sys.exit(1)

    print("Connecting to Google APIs...")
    drive_svc  = _build_service("drive",  "v3")
    sheets_svc = _build_service("sheets", "v4")

    for year in years:
        name = f"Garmin {year}"
        print(f"\n{'='*50}")
        print(f"Processing {name}...")

        sheet_id = find_existing_sheet(drive_svc, name)
        if sheet_id and not args.rebuild:
            print(f"  Already exists (ID: {sheet_id}) — skipping. Use --rebuild to overwrite.")
            continue
        if sheet_id and args.rebuild:
            print(f"  Deleting existing sheet for rebuild...")
            drive_svc.files().delete(fileId=sheet_id).execute()
            sheet_id = None

        print(f"  Creating spreadsheet...")
        sheet_id = create_spreadsheet(drive_svc, sheets_svc, name)
        print(f"  Created: https://docs.google.com/spreadsheets/d/{sheet_id}")

        setup_year_spreadsheet(
            sheets_svc, sheet_id, year,
            daily.get(year, {}),
            activities.get(year, {}),
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
