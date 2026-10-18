#!/usr/bin/env bash
# Keeps the backup container running: the withdrawal log every hour at half past, and the
# database once a day in the hour BACKUP_DATABASE_HOUR_UTC (default 21: 21:30 UTC is 03:00 in
# India, when nobody is recording).
# A failed run is recorded by backup.sh and does not stop the schedule.
set -uo pipefail
hour=${BACKUP_DATABASE_HOUR_UTC:-21}

while true; do
  # Wake at the half hour, away from the worker's cleanup jobs on the hour.
  now=$(date -u +%s)
  next=$(((now / 3600) * 3600 + 1800))
  ((next > now)) || next=$((next + 3600))
  sleep $((next - now))

  /usr/local/bin/backup.sh withdrawal-log
  if [[ "$(date -u +%-H)" == "$hour" ]]; then
    /usr/local/bin/backup.sh database
  fi
done
