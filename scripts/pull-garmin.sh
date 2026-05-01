#!/usr/bin/env bash
# Daily Garmin Connect data pull
# Logs to <project_dir>/logs/garmin-YYYY-MM-DD.log by default.
# Override: GARMIN_PULL_LOG=/your/path pull-garmin.sh --push-both
#
# Cron example (6 AM daily):
#   0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh
#
# Optional flags (can be combined):
#   --push-drive    Upload CSVs to Google Drive after a successful pull
#   --push-sheets   Sync CSVs to Google Sheets after a successful pull
#   --push-both     Shorthand for --push-drive --push-sheets
#
# Example with Drive + Sheets:
#   0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh --push-both

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
LOG="${GARMIN_PULL_LOG:-${PROJECT_DIR}/logs/garmin-$(date '+%Y-%m-%d').log}"

PUSH_DRIVE=0
PUSH_SHEETS=0

for arg in "$@"; do
    case "$arg" in
        --push-drive)  PUSH_DRIVE=1 ;;
        --push-sheets) PUSH_SHEETS=1 ;;
        --push-both)   PUSH_DRIVE=1; PUSH_SHEETS=1 ;;
    esac
done

mkdir -p "$(dirname "$LOG")"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
cd "$PROJECT_DIR"
"$PYTHON" pullers/garmin.py >> "$LOG" 2>&1
PULL_EXIT=$?
echo "Pull exit: $PULL_EXIT" >> "$LOG"

if [ "$PULL_EXIT" -eq 0 ]; then
    "$PYTHON" reports/build_garmin_csvs.py >> "$LOG" 2>&1
    echo "CSV build exit: $?" >> "$LOG"

    if [ "$PUSH_DRIVE" -eq 1 ]; then
        "$PYTHON" -m garmin_extract --push-drive >> "$LOG" 2>&1
        echo "Drive push exit: $?" >> "$LOG"
    fi

    if [ "$PUSH_SHEETS" -eq 1 ]; then
        "$PYTHON" -m garmin_extract --push-sheets >> "$LOG" 2>&1
        echo "Sheets push exit: $?" >> "$LOG"
    fi
fi
