#!/usr/bin/env bash
# Daily Garmin Connect data pull
# Runs via cron — logs to /tmp/garmin-pull.log
#
# Cron example (6 AM daily):
#   0 6 * * * /path/to/garmin-extract/scripts/pull-garmin.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
LOG="/tmp/garmin-pull.log"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
cd "$PROJECT_DIR"
"$PYTHON" pullers/garmin.py >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"
