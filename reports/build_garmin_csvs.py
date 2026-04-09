#!/usr/bin/env python3
"""
Flatten all data/garmin/YYYY-MM-DD.json files into two CSVs:

  reports/garmin_daily.csv      — one row per day, all key scalar metrics
  reports/garmin_activities.csv — one row per workout/activity

Handles both data source formats:
  garmin-browser  (live pull, 25 separate metric keys, richer)
  garmin-export   (bulk export, fewer keys, stats/stress/battery inline)

Usage:
    python reports/build_garmin_csvs.py
    python reports/build_garmin_csvs.py --since 2025-01-01
"""

import argparse
import csv
import glob
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "data" / "garmin"
OUT_DIR   = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def s(value, default=None):
    """Return value if truthy and not a container, else default."""
    if value is None or value == "" or value == "EMPTY":
        return default
    if isinstance(value, (list, dict)):
        return default
    return value


def _behavior_key(name: str) -> str:
    """Convert a Garmin lifestyle behavior name to a safe snake_case column key.

    Examples:
        "Alcohol"              → "lifestyle_alcohol"
        "Morning Caffeine"     → "lifestyle_morning_caffeine"
        "Ear Plugs/Headphones" → "lifestyle_ear_plugs_headphones"
    """
    key = name.lower()
    for ch in " /()-":
        key = key.replace(ch, "_")
    while "__" in key:
        key = key.replace("__", "_")
    return "lifestyle_" + key.strip("_")


def discover_lifestyle_behaviors(files: list) -> dict:
    """Scan JSON files and return {behavior_name: has_amounts} for every
    lifestyle behavior present anywhere in the dataset.

    has_amounts is True if any entry for that behavior includes a non-null
    amount value — used to decide whether to emit an amount column.

    Returns an empty dict if no lifestyle data exists anywhere.
    """
    behaviors: dict[str, bool] = {}
    for path in files:
        try:
            with open(path) as f:
                raw = json.load(f)
            ls = raw.get("lifestyle") or {}
            if not isinstance(ls, dict):
                continue
            for name, entry in ls.items():
                if not isinstance(entry, dict):
                    continue
                has_amount = entry.get("amount") is not None
                behaviors[name] = behaviors.get(name, False) or has_amount
        except Exception:
            continue
    return behaviors


def ms_to_date(ms) -> str:
    """Convert millisecond Unix timestamp to YYYY-MM-DD (UTC)."""
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def seconds_to_hhmm(seconds) -> str:
    """Convert seconds to h:mm string (e.g. 7:32)."""
    if seconds is None:
        return ""
    try:
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        return f"{h}:{m:02d}"
    except (TypeError, ValueError):
        return ""


def meters_to_miles(m) -> float | None:
    try:
        return round(float(m) / 1609.344, 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-day extraction
# ---------------------------------------------------------------------------

def extract_day(path: Path, lifestyle_behaviors: dict = None) -> dict:
    """Read one JSON file and return a flat dict for the daily CSV row."""
    with open(path) as f:
        raw = json.load(f)

    date  = raw.get("_meta", {}).get("date", path.stem)
    src   = raw.get("_meta", {}).get("source", "unknown")

    # ---- stats -------------------------------------------------------
    st = raw.get("stats") or {}

    # Browser-pull stats has these directly at top level.
    # Export stats also has them at top level — same field names.
    steps            = s(st.get("totalSteps"))
    step_goal        = s(st.get("dailyStepGoal"))
    calories_total   = s(st.get("totalKilocalories"))
    calories_active  = s(st.get("activeKilocalories"))
    calories_bmr     = s(st.get("bmrKilocalories"))
    distance_miles   = meters_to_miles(st.get("totalDistanceMeters"))
    active_seconds   = s(st.get("activeSeconds"))
    highly_active_s  = s(st.get("highlyActiveSeconds"))
    mod_intensity_m  = s(st.get("moderateIntensityMinutes"))
    vig_intensity_m  = s(st.get("vigorousIntensityMinutes"))
    floors_up        = round(float(st["floorsAscendedInMeters"]), 1) if st.get("floorsAscendedInMeters") is not None else None
    floors_down      = round(float(st["floorsDescendedInMeters"]), 1) if st.get("floorsDescendedInMeters") is not None else None
    resting_hr       = s(st.get("restingHeartRate"))
    min_hr           = s(st.get("minHeartRate"))
    max_hr           = s(st.get("maxHeartRate"))
    spo2_avg         = s(st.get("averageSpo2Value"))
    spo2_low         = s(st.get("lowestSpo2Value"))

    # ---- stress (browser-pull: top-level key; export: nested in stats) --
    stress_src = raw.get("stress") or {}
    if not stress_src:
        # Export embeds allDayStress inside stats
        agg = st.get("allDayStress") or {}
        for entry in (agg.get("aggregatorList") or []):
            if entry.get("type") == "TOTAL":
                stress_src = entry
                break

    avg_stress    = s(stress_src.get("averageStressLevel") or stress_src.get("avgStressLevel"))
    max_stress    = s(stress_src.get("maxStressLevel"))
    stress_rest_s = s(stress_src.get("restDuration"))
    stress_low_s  = s(stress_src.get("lowDuration"))
    stress_med_s  = s(stress_src.get("mediumDuration"))
    stress_high_s = s(stress_src.get("highDuration"))

    # ---- body battery (browser: top-level list; export: nested in stats) --
    bb_src = raw.get("body_battery") or []
    if not bb_src:
        bb_obj = st.get("bodyBattery") or {}
        bb_src = [bb_obj] if bb_obj else []

    bb_start = bb_high = bb_low = bb_end = None
    for entry in bb_src if isinstance(bb_src, list) else []:
        stat_list = entry.get("bodyBatteryStatList") or []
        for stat in stat_list:
            t = stat.get("bodyBatteryStatType")
            v = stat.get("statsValue")
            if t == "STARTOFDAY":    bb_start = v
            elif t == "HIGHEST":     bb_high  = v
            elif t == "LOWEST":      bb_low   = v
            elif t == "ENDOFDAY":    bb_end   = v

    # ---- respiration (browser: top-level; export: nested in stats) -----
    resp_src = raw.get("respiration") or {}
    if not resp_src:
        resp_src = st.get("respiration") or {}
    resp_waking = s(resp_src.get("avgWakingRespirationValue"))
    resp_high   = s(resp_src.get("highestRespirationValue"))
    resp_low    = s(resp_src.get("lowestRespirationValue"))

    # ---- sleep -------------------------------------------------------
    sl = raw.get("sleep") or {}
    # Browser-pull wraps sleep in dailySleepDTO for some sub-fields
    sl_dto = sl.get("dailySleepDTO") or sl  # fall back to sl itself if no wrapper

    sleep_start   = s(sl.get("sleepStartTimestampGMT") or sl_dto.get("sleepStartTimestampGMT"))
    sleep_end     = s(sl.get("sleepEndTimestampGMT")   or sl_dto.get("sleepEndTimestampGMT"))
    deep_s        = s(sl.get("deepSleepSeconds")   or sl_dto.get("deepSleepSeconds"))
    light_s       = s(sl.get("lightSleepSeconds")  or sl_dto.get("lightSleepSeconds"))
    rem_s         = s(sl.get("remSleepSeconds")     or sl_dto.get("remSleepSeconds"))
    awake_s       = s(sl.get("awakeSleepSeconds")   or sl_dto.get("awakeSleepSeconds"))
    awake_count   = s(sl.get("awakeCount")          or sl_dto.get("awakeCount"))
    restless      = s(sl.get("restlessMomentCount") or sl_dto.get("restlessMomentCount"))
    avg_sleep_stress = s(sl.get("avgSleepStress")   or sl_dto.get("avgSleepStress"))
    sleep_resp    = s(sl.get("averageRespiration")  or sl_dto.get("averageRespiration"))

    total_sleep_s = None
    if deep_s is not None and light_s is not None and rem_s is not None:
        total_sleep_s = int(deep_s) + int(light_s) + int(rem_s)

    # Sleep scores (export: directly in sl; browser: in dailySleepDTO.sleepScores or sl.sleepScores)
    scores_src = sl.get("sleepScores") or sl_dto.get("sleepScores") or {}
    _overall          = scores_src.get("overall")
    sleep_score       = s(scores_src.get("overallScore") or
                          (_overall.get("value") if isinstance(_overall, dict) else _overall))
    sleep_score_deep  = s(scores_src.get("deepScore"))
    sleep_score_rem   = s(scores_src.get("remScore"))
    sleep_score_recov = s(scores_src.get("recoveryScore"))
    sleep_score_dur   = s(scores_src.get("durationScore"))

    # Sleep SpO2
    spo2_sl = sl.get("spo2SleepSummary") or sl_dto.get("spo2SleepSummary") or {}
    sleep_spo2_avg = s(spo2_sl.get("averageSPO2"))
    sleep_spo2_low = s(spo2_sl.get("lowestSPO2"))
    sleep_hr_avg   = s(spo2_sl.get("averageHR"))

    # ---- HRV (browser only) ------------------------------------------
    hrv_src = raw.get("hrv")
    hrv_weekly_avg = hrv_last_night = hrv_status = None
    if isinstance(hrv_src, dict):
        hrv_weekly_avg  = s(hrv_src.get("weeklyAvg"))
        hrv_last_night  = s(hrv_src.get("lastNight"))
        hrv_status      = s(hrv_src.get("hrvStatus") or hrv_src.get("status"))
        if not hrv_weekly_avg:
            # Try nested summary
            summ = hrv_src.get("hrvSummary") or hrv_src.get("summary") or {}
            hrv_weekly_avg = s(summ.get("weeklyAvg") or summ.get("lastNightAvg"))
            hrv_last_night = s(summ.get("lastNight") or summ.get("lastNightAvg"))
            hrv_status     = s(summ.get("status") or summ.get("hrvStatus"))

    # ---- hydration (browser: top-level; export: nested in stats) -------
    hy_src = raw.get("hydration") or st.get("hydration") or {}
    hydration_ml      = s(hy_src.get("valueInML"))
    hydration_goal_ml = s(hy_src.get("goalInML"))
    hydration_sweat_ml= s(hy_src.get("sweatLossInML"))

    # ---- training / fitness (browser only) ----------------------------
    ts = raw.get("training_status") or {}
    vo2max    = s((ts.get("mostRecentVO2Max") or {}).get("generic"))
    tr_load   = s((ts.get("mostRecentTrainingLoadBalance") or {}).get("monotonicLoad") or
                  (ts.get("mostRecentTrainingLoadBalance") or {}).get("acuteLoad"))
    tr_status = s((ts.get("mostRecentTrainingStatus") or {}).get("trainingStatusPhrase"))

    fa = raw.get("fitness_age") or {}
    fitness_age = s(fa.get("fitnessAge"))
    chrono_age  = s(fa.get("chronologicalAge"))

    tr = raw.get("training_readiness") or []
    tr_score = None
    if isinstance(tr, list) and tr:
        tr_score = s(tr[0].get("score"))
    elif isinstance(tr, dict):
        tr_score = s(tr.get("score"))

    spo2_full = raw.get("spo2") or {}
    spo2_sleep_avg   = s(spo2_full.get("avgSleepSpO2")     or spo2_full.get("averageSpO2"))
    spo2_ondemand    = s(spo2_full.get("onDemandReadingList"))

    # ---- lifestyle logging -------------------------------------------------
    # Columns are discovered dynamically from the dataset — not hardcoded.
    # lifestyle_behaviors is a {name: has_amounts} dict built by discover_lifestyle_behaviors().
    ls = raw.get("lifestyle") or {}
    lifestyle_cols = {}
    for behavior, has_amount in (lifestyle_behaviors or {}).items():
        key   = _behavior_key(behavior)
        entry = ls.get(behavior) or {}
        lifestyle_cols[key] = entry.get("status") if entry else None
        if has_amount:
            lifestyle_cols[f"{key}_amount"] = s(entry.get("amount")) if entry else None

    return {
        "date":                    date,
        "source":                  src,
        # Activity
        "steps":                   steps,
        "step_goal":               step_goal,
        "distance_miles":          distance_miles,
        "calories_total":          calories_total,
        "calories_active":         calories_active,
        "calories_bmr":            calories_bmr,
        "active_seconds":          active_seconds,
        "highly_active_seconds":   highly_active_s,
        "intensity_moderate_min":  mod_intensity_m,
        "intensity_vigorous_min":  vig_intensity_m,
        "floors_up_m":             floors_up,
        "floors_down_m":           floors_down,
        # Heart rate
        "hr_resting":              resting_hr,
        "hr_min":                  min_hr,
        "hr_max":                  max_hr,
        # Stress
        "stress_avg":              avg_stress,
        "stress_max":              max_stress,
        "stress_rest_seconds":     stress_rest_s,
        "stress_low_seconds":      stress_low_s,
        "stress_med_seconds":      stress_med_s,
        "stress_high_seconds":     stress_high_s,
        # Body battery
        "battery_start":           bb_start,
        "battery_end":             bb_end,
        "battery_high":            bb_high,
        "battery_low":             bb_low,
        # SpO2
        "spo2_avg":                spo2_avg,
        "spo2_low":                spo2_low,
        "spo2_sleep_avg":          spo2_sleep_avg,
        # Respiration
        "resp_waking_avg":         resp_waking,
        "resp_high":               resp_high,
        "resp_low":                resp_low,
        # Sleep
        "sleep_start_utc":         sleep_start,
        "sleep_end_utc":           sleep_end,
        "sleep_total_hhmm":        seconds_to_hhmm(total_sleep_s),
        "sleep_total_seconds":     total_sleep_s,
        "sleep_deep_seconds":      deep_s,
        "sleep_light_seconds":     light_s,
        "sleep_rem_seconds":       rem_s,
        "sleep_awake_seconds":     awake_s,
        "sleep_awake_count":       awake_count,
        "sleep_restless_moments":  restless,
        "sleep_stress_avg":        avg_sleep_stress,
        "sleep_respiration_avg":   sleep_resp,
        "sleep_spo2_avg":          sleep_spo2_avg,
        "sleep_spo2_low":          sleep_spo2_low,
        "sleep_hr_avg":            sleep_hr_avg,
        "sleep_score":             sleep_score,
        "sleep_score_deep":        sleep_score_deep,
        "sleep_score_rem":         sleep_score_rem,
        "sleep_score_recovery":    sleep_score_recov,
        "sleep_score_duration":    sleep_score_dur,
        # HRV
        "hrv_weekly_avg":          hrv_weekly_avg,
        "hrv_last_night":          hrv_last_night,
        "hrv_status":              hrv_status,
        # Hydration
        "hydration_ml":            hydration_ml,
        "hydration_goal_ml":       hydration_goal_ml,
        "hydration_sweat_ml":      hydration_sweat_ml,
        # Training / fitness (browser-pull only)
        "vo2max":                  vo2max,
        "training_load":           tr_load,
        "training_status":         tr_status,
        "training_readiness":      tr_score,
        "fitness_age":             fitness_age,
        "chronological_age":       chrono_age,
        # Lifestyle logging (2026+)
        **lifestyle_cols,
    }


def extract_activities(path: Path, date: str) -> list[dict]:
    """Return a list of activity rows from one day's JSON file."""
    with open(path) as f:
        raw = json.load(f)

    acts = raw.get("activities") or []
    rows = []

    for a in acts:
        if not isinstance(a, dict):
            continue

        # Timestamps may be ms epoch or ISO strings depending on source
        start_local = a.get("startTimeLocal") or a.get("beginTimestamp")
        if isinstance(start_local, (int, float)) and start_local > 1e10:
            start_local = datetime.utcfromtimestamp(int(start_local) / 1000).isoformat()

        duration_s = a.get("duration")
        if duration_s and duration_s > 86400:
            # Export stores duration in milliseconds; anything over 1 day in seconds is ms
            duration_s = duration_s / 1000

        rows.append({
            "date":              date,
            "activity_id":       a.get("activityId"),
            "name":              a.get("name") or a.get("activityName"),
            "type":              a.get("activityType") or a.get("activityTypeDTO", {}).get("typeKey") if isinstance(a.get("activityTypeDTO"), dict) else a.get("activityType"),
            "sport":             a.get("sportType"),
            "start_local":       start_local,
            "duration_seconds":  round(float(duration_s), 0) if duration_s else None,
            "distance_miles":    meters_to_miles((a.get("distance") or 0) / 100
                                               if (a.get("distance") or 0) > 10000
                                               else a.get("distance")),
            "calories":          a.get("calories"),
            "avg_hr":            a.get("avgHr"),
            "max_hr":            a.get("maxHr"),
            "avg_speed":         round(float(a["avgSpeed"]), 3) if a.get("avgSpeed") else None,
            "steps":             a.get("steps"),
            "avg_cadence":       a.get("avgRunCadence"),
            "avg_power":         a.get("avgPower"),
            "elevation_gain_m":  a.get("elevationGain"),
            "source":            raw.get("_meta", {}).get("source", "unknown"),
        })

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Only include dates on or after this date")
    args = parser.parse_args()

    since = args.since or "2000-01-01"

    files = sorted(
        p for p in DATA_DIR.glob("*.json")
        if p.stem >= since
    )

    if not files:
        print(f"No files found in {DATA_DIR}")
        return

    OUT_DIR.mkdir(exist_ok=True)

    lifestyle_behaviors = discover_lifestyle_behaviors(files)
    if lifestyle_behaviors:
        print(f"Lifestyle behaviors found: {', '.join(lifestyle_behaviors)}")

    daily_rows      = []
    activity_rows   = []
    errors          = []

    for path in files:
        try:
            row = extract_day(path, lifestyle_behaviors)
            daily_rows.append(row)
            activity_rows.extend(extract_activities(path, path.stem))
        except Exception as e:
            errors.append(f"{path.name}: {e}")

    # Write daily CSV
    daily_path = OUT_DIR / "garmin_daily.csv"
    if daily_rows:
        cols = list(daily_rows[0].keys())
        with open(daily_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(daily_rows)
        print(f"Wrote {len(daily_rows)} rows → {daily_path}")

    # Write activities CSV
    acts_path = OUT_DIR / "garmin_activities.csv"
    if activity_rows:
        cols = list(activity_rows[0].keys())
        with open(acts_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(activity_rows)
        print(f"Wrote {len(activity_rows)} activity rows → {acts_path}")
    else:
        print("No activities found.")

    if errors:
        print(f"\n{len(errors)} files had errors:")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
