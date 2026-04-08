#!/usr/bin/env python3
"""
Import historical Garmin data from a Garmin Connect bulk export (.zip).

Reads the export zip and writes per-day JSON files to data/garmin/
for any date not already present. Skips dates already pulled via
the live browser puller to avoid overwriting richer data.

Usage:
    python pullers/garmin_import_export.py path/to/export.zip
    python pullers/garmin_import_export.py path/to/export.zip --no-skip
"""

import argparse
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "garmin"


def load_uds_files(z: zipfile.ZipFile) -> dict:
    """Load all UDSFile entries, keyed by calendarDate."""
    by_date = {}
    for name in z.namelist():
        if "UDSFile" in name and name.endswith(".json"):
            with z.open(name) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                date = entry.get("calendarDate")
                if date:
                    by_date[date] = entry
    return by_date


def load_sleep_files(z: zipfile.ZipFile) -> dict:
    """Load all sleepData entries, keyed by calendarDate."""
    by_date = {}
    for name in z.namelist():
        if "sleepData" in name and name.endswith(".json"):
            with z.open(name) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                date = entry.get("calendarDate")
                if date:
                    by_date[date] = entry
    return by_date


def load_hydration_files(z: zipfile.ZipFile) -> dict:
    """Load all HydrationLogFile entries, keyed by calendarDate."""
    by_date = {}
    for name in z.namelist():
        if "HydrationLogFile" in name and name.endswith(".json"):
            with z.open(name) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                date = entry.get("calendarDate")
                if date:
                    by_date[date] = entry
    return by_date


def load_biometrics(z: zipfile.ZipFile) -> dict:
    """Load userBioMetrics, keyed by calendarDate (from metaData)."""
    by_date = {}
    for name in z.namelist():
        if "userBioMetrics" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.load(f)
            if isinstance(data, list):
                for entry in data:
                    meta = entry.get("metaData") or {}
                    date = (meta.get("calendarDate") or "")[:10]
                    if date:
                        by_date.setdefault(date, []).append(entry)
            break
    return by_date


def load_lifestyle(z: zipfile.ZipFile) -> dict:
    """Load LifestyleLogging entries, keyed by calendarDate.

    Returns a dict of {date: {behaviourName: {status, amount}}}
    """
    by_date = defaultdict(dict)
    for name in z.namelist():
        if "LifestyleLogging" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.load(f)
            if not (isinstance(data, list) and data):
                break
            logs = data[0].get("dailyLogList") or []
            for entry in logs:
                cal = entry.get("calendarDate")
                if not cal or len(cal) < 3:
                    continue
                date = f"{cal[0]:04d}-{cal[1]:02d}-{cal[2]:02d}"
                behaviour = entry.get("behaviourName", "").strip()
                status    = entry.get("status")
                # Sum amounts across sub-types (e.g. drinks count)
                details   = entry.get("dailyLogDetailDTOList") or []
                amount    = sum(d.get("amount", 0) for d in details) or None
                by_date[date][behaviour] = {"status": status, "amount": amount}
            break
    return dict(by_date)


def load_activities(z: zipfile.ZipFile) -> dict:
    """Load summarizedActivities, keyed by startDay (YYYY-MM-DD)."""
    by_date = defaultdict(list)
    for name in z.namelist():
        if "summarizedActivities" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                # Nested: [{"summarizedActivitiesExport": [...]}]
                inner = data[0].get("summarizedActivitiesExport", data)
                for entry in inner:
                    ts = entry.get("beginTimestamp") or entry.get("startTimeGMT")
                    if ts:
                        try:
                            date = datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
                            by_date[date].append(entry)
                        except (ValueError, OSError):
                            pass
            break
    return dict(by_date)


def main():
    parser = argparse.ArgumentParser(description="Import Garmin export zip into data/garmin/")
    parser.add_argument("zip_path", help="Path to Garmin export .zip file")
    parser.add_argument("--no-skip", action="store_true",
                        help="Overwrite dates that already have a data file")
    args = parser.parse_args()

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"ERROR: {zip_path} not found")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading export: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as z:
        print("  Loading daily summaries (UDS)...")
        uds       = load_uds_files(z)
        print(f"    {len(uds)} days")

        print("  Loading sleep data...")
        sleep     = load_sleep_files(z)
        print(f"    {len(sleep)} days")

        print("  Loading hydration data...")
        hydration = load_hydration_files(z)
        print(f"    {len(hydration)} days")

        print("  Loading biometrics...")
        bio       = load_biometrics(z)
        print(f"    {len(bio)} days")

        print("  Loading activities...")
        activities = load_activities(z)
        print(f"    {len(activities)} days with activity")

        print("  Loading lifestyle logging...")
        lifestyle = load_lifestyle(z)
        print(f"    {len(lifestyle)} days with lifestyle entries")

    # Union of all dates
    all_dates = sorted(set(uds) | set(sleep) | set(hydration) | set(lifestyle))
    print(f"\n{len(all_dates)} unique dates ({all_dates[0]} → {all_dates[-1]})")

    written = 0
    skipped = 0

    for date in all_dates:
        out_path = DATA_DIR / f"{date}.json"
        if not args.no_skip and out_path.exists():
            skipped += 1
            continue

        record = {
            "stats":      uds.get(date),
            "sleep":      sleep.get(date),
            "hydration":  hydration.get(date),
            "biometrics": bio.get(date),
            "activities": activities.get(date, []),
            "lifestyle":  lifestyle.get(date),
            "_meta": {
                "date":       date,
                "pulled_at":  datetime.utcnow().isoformat() + "Z",
                "source":     "garmin-export",
            },
        }

        with open(out_path, "w") as f:
            json.dump(record, f, indent=2, default=str)
        written += 1

    print(f"\nWrote {written} files, skipped {skipped} (already present).")
    print(f"Data directory: {DATA_DIR}")


if __name__ == "__main__":
    main()
