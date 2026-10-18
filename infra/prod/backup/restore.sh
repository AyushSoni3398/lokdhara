#!/usr/bin/env bash
# Restores a database backup into an EMPTY database (docs/OBSERVABILITY_AND_BACKUPS.md §4).
#
#   restore.sh lokdhara-db-20261018T210000Z.dump.age
#
# The file is taken from BACKUP_DIR, or fetched from BACKUP_REMOTE/daily (or /monthly) when it
# is not on this server. Restore into a scratch database for a drill; restore into production
# only after the service is stopped. Afterwards run, against the restored database:
#   python -m app.cli verify-restore --withdrawal-log <decrypted latest withdrawal log>
#
# Environment:
#   RESTORE_DATABASE_URL       libpq URL of the empty target database, as the schema owner
#                              (the same role name as in production, `lokdhara` by default,
#                              because the saved default privileges name it)
#   RESTORE_AGE_IDENTITY_FILE  an admin's age private key; bring it for the restore and remove
#                              it afterwards, it is never kept on the server
#   BACKUP_DIR, BACKUP_REMOTE  as for backup.sh
set -Eeuo pipefail
umask 077

name=${1:?usage: restore.sh <backup file name>}
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is not set}"
: "${RESTORE_AGE_IDENTITY_FILE:?RESTORE_AGE_IDENTITY_FILE is not set}"
dir=${BACKUP_DIR:-/backups}
remote=${BACKUP_REMOTE:-}
name=$(basename "$name")

file="$dir/$name"
if [[ ! -f "$file" ]]; then
  [[ -n "$remote" ]] || { echo "$file not found and no BACKUP_REMOTE is set" >&2; exit 1; }
  file=$(mktemp)
  trap 'rm -f "$file"' EXIT
  rclone copyto --quiet "$remote/daily/$name" "$file" 2>/dev/null ||
    rclone copyto --quiet "$remote/monthly/$name" "$file"
fi

sql() { psql "$RESTORE_DATABASE_URL" --quiet --no-psqlrc -v ON_ERROR_STOP=1 "$@"; }

tables=$(sql -tAc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
if [[ "$tables" != 0 ]]; then
  echo "The target database already has $tables tables; restore only into an empty one." >&2
  exit 1
fi

# The group roles are cluster-wide, so a dump does not carry them; the grants in it need them.
for role in app_rw app_erasure app_readonly app_backup; do
  sql -c "DO \$\$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$role') THEN
      CREATE ROLE $role NOLOGIN;
    END IF;
  END \$\$"
done

age --decrypt -i "$RESTORE_AGE_IDENTITY_FILE" "$file" |
  pg_restore --no-owner --exit-on-error --single-transaction --dbname="$RESTORE_DATABASE_URL"

echo "Restored $name. Now run: python -m app.cli verify-restore --withdrawal-log <log.csv>"
