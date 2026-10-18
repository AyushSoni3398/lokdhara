#!/usr/bin/env bash
# Backs up Lokdhara (docs/OBSERVABILITY_AND_BACKUPS.md §3). Runs in the backup container.
#
#   backup.sh database         # pg_dump of everything, encrypted, nightly and before deploys
#   backup.sh withdrawal-log   # the withdrawal requests as CSV, encrypted, every hour
#
# Files are encrypted with age to the admins' public keys before they touch the disk; the
# private keys are never on the server. Each run, failed or not, leaves a backup_runs row
# that the admin status page reads.
#
# Environment:
#   BACKUP_DATABASE_URL         libpq URL of a login role in app_backup (migration 0015)
#   BACKUP_AGE_RECIPIENTS_FILE  public keys, one per line (default /run/secrets/backup_recipients)
#   BACKUP_DIR                  where files are kept on the server (default /backups)
#   BACKUP_REMOTE               rclone destination for the off-site copy, e.g. offsite:lokdhara-backups;
#                               empty keeps files on this server only, which the status row says
#   BACKUP_KEEP_LOCAL           database files kept on the server (default 7)
set -Eeuo pipefail
umask 077

kind=${1:-}
case "$kind" in
  database | withdrawal-log) ;;
  *) echo "usage: backup.sh database|withdrawal-log" >&2; exit 2 ;;
esac

: "${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL is not set}"
recipients=${BACKUP_AGE_RECIPIENTS_FILE:-/run/secrets/backup_recipients}
dir=${BACKUP_DIR:-/backups}
remote=${BACKUP_REMOTE:-}
keep_local=${BACKUP_KEEP_LOCAL:-7}

started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
step=start

# One row per run. psql variables are quoted by psql itself (:'name'), never pasted into SQL.
record() {
  local succeeded=$1 size=$2 file=$3 detail=$4
  psql "$BACKUP_DATABASE_URL" --quiet --no-psqlrc -v ON_ERROR_STOP=1 \
    -v kind="${kind/-/_}" -v started="$started" -v succeeded="$succeeded" \
    -v size="$size" -v file="$file" -v detail="$detail" <<'SQL'
INSERT INTO backup_runs (kind, started_at, succeeded, size_bytes, file_name, detail)
VALUES (:'kind', :'started', :'succeeded', NULLIF(:'size', '')::bigint,
        NULLIF(:'file', ''), NULLIF(:'detail', ''));
SQL
}

# Deletes copies older than $2 in folder $1; a folder that does not exist yet is skipped.
prune_remote() {
  if rclone lsf --max-depth 1 "$1" >/dev/null 2>&1; then
    rclone delete --quiet --min-age "$2" "$1"
  fi
}

fail() {
  trap - ERR
  echo "backup $kind failed during: $step" >&2
  rm -f "${partial:-}"
  record false "" "" "failed during: $step" || echo "could not record the failure" >&2
  exit 1
}
trap fail ERR

step="checking the public keys"
grep -q '^age1' "$recipients"
mkdir -p "$dir"

if [[ "$kind" == database ]]; then
  name="lokdhara-db-$stamp.dump.age"
  folder=daily
  step="dumping and encrypting the database"
  partial="$dir/.$name.partial"
  pg_dump --format=custom --dbname="$BACKUP_DATABASE_URL" | age --encrypt -R "$recipients" >"$partial"
else
  name="lokdhara-withdrawals-$stamp.csv.age"
  folder=withdrawal-log
  step="exporting and encrypting the withdrawal log"
  partial="$dir/.$name.partial"
  # Ids and states only: no names, notes or contacts (docs/PRIVACY_AND_SECURITY.md).
  psql "$BACKUP_DATABASE_URL" --quiet --no-psqlrc -v ON_ERROR_STOP=1 -c "\copy (
    SELECT id, speaker_id, submission_id, requested_scope, status, completed_at
    FROM withdrawal_requests ORDER BY received_at, id) TO STDOUT WITH (FORMAT csv, HEADER)" |
    age --encrypt -R "$recipients" >"$partial"
fi

step="checking the encrypted file"
[[ "$(head -c 21 "$partial")" == "age-encryption.org/v1" ]]
mv "$partial" "$dir/$name"
size=$(stat -c %s "$dir/$name")

detail=""
if [[ -n "$remote" ]]; then
  step="copying off-site"
  rclone copyto --quiet "$dir/$name" "$remote/$folder/$name"
  if [[ "$kind" == database && "$(date -u +%d)" == 01 ]]; then
    rclone copyto --quiet "$dir/$name" "$remote/monthly/$name"
  fi
  step="removing old off-site copies"
  if [[ "$kind" == database ]]; then
    prune_remote "$remote/daily" 31d     # 30 daily copies
    prune_remote "$remote/monthly" 366d  # 12 monthly copies
  else
    prune_remote "$remote/withdrawal-log" 8d
  fi
else
  detail="kept on this server only: no off-site copy is configured"
fi

step="removing old copies on this server"
if [[ "$kind" == database ]]; then
  pattern='lokdhara-db-*.dump.age' keep=$keep_local
else
  pattern='lokdhara-withdrawals-*.csv.age' keep=48
fi
find "$dir" -maxdepth 1 -name "$pattern" -printf '%f\n' | sort -r | tail -n +"$((keep + 1))" |
  while read -r old; do rm -f "$dir/$old"; done

step="recording the run"
record true "$size" "$name" "$detail"
echo "backup $kind ok: $name ($size bytes)${detail:+; $detail}"
