#!/usr/bin/env bash
# Registers (or prints) a crontab entry that runs `edutube daily` once a day
# (LLR-SCH-02).
#
# Usage:
#   scripts/schedule_cron.sh            # print the crontab line
#   scripts/schedule_cron.sh --install  # append it to the current user's crontab
#
# The entry cd's into the project directory, activates the venv, runs
# `edutube daily`, and appends output to logs/cron.log.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_TIME="06:00"

if [ -f "$PROJECT_ROOT/config.yaml" ]; then
    extracted=$(grep -E "run_time:" "$PROJECT_ROOT/config.yaml" | head -1 | sed -E "s/.*run_time:\s*['\"]?([0-9]{2}:[0-9]{2}).*/\1/") || true
    if [ -n "${extracted:-}" ]; then
        RUN_TIME="$extracted"
    fi
fi

HOUR="${RUN_TIME%%:*}"
MINUTE="${RUN_TIME##*:}"
HOUR=$((10#$HOUR))
MINUTE=$((10#$MINUTE))

CRON_LINE="$MINUTE $HOUR * * * cd \"$PROJECT_ROOT\" && . .venv/bin/activate && edutube daily >> logs/cron.log 2>&1"

echo "$CRON_LINE"

if [ "${1:-}" = "--install" ]; then
    ( crontab -l 2>/dev/null | grep -v "edutube daily" || true; echo "$CRON_LINE" ) | crontab -
    echo "Installed into crontab. View with: crontab -l"
fi
