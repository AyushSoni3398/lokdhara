# Observability and Backups

Status: **Proposed.**

## 1. Logging

- Structured JSON logs to stdout from API and worker; Docker log rotation on the host (e.g., 7 × 50 MB).
- Every request has a `request_id` (propagated to jobs as `correlation_id`).
- **Never logged:** audio, text content, speaker names/contacts, emails/phones, passwords, tokens, cookies, raw IP addresses, object keys of consent evidence.
- A logging filter redacts known sensitive keys; a unit test feeds sample payloads through the logger and asserts redaction.

## 2. Metrics and health (lightweight)

| Signal | Source | Alert when |
|--------|--------|-----------|
| `/healthz`, `/readyz` | API | External uptime monitor fails 3 checks |
| Queue depth and oldest queued job age | DB query exposed on admin dashboard | Oldest job > 1 hour |
| Dead jobs count | DB | > 0 new in 24 h (daily digest) |
| Disk usage on VM | Host | > 80% |
| Backup success | Backup job writes status row | Missing for > 26 h |
| Error rate (5xx) | Logs / error tracker | Spike |
| Login failures | Audit events | Unusual spike |

MVP uses an admin dashboard page and a daily digest to maintainers (delivery channel to be chosen in M8, e.g. email); no Prometheus/Grafana stack until there is a need.

*As built (M8 part 2, ADR-024):* the **Service status** page (`/admin/status`, API `GET /admin/status`) shows every signal above except the 5xx rate, with alerts first: no successful database backup for 26 hours or withdrawal log for 2 hours, a failed last backup run, backups not copied off-site, a job due for more than an hour, jobs failed in the last day, the disk more than 80% full, or more than 50 failed sign-ins in a day. The worker sends the same facts as a plain-text email once a day (`ops.digest`) through any SMTP server set in `LKD_SMTP_*` to `LKD_DIGEST_RECIPIENTS`; without those settings it only logs that a digest was made. Counts and times only, never names or content. An external uptime monitor on `/healthz` is still to be set up with the server ([ops/RUNBOOK.md §6](ops/RUNBOOK.md#6-monitoring)). The 5xx rate waits for an error tracker, which is optional.

Optional error tracking (e.g., Sentry free tier): only with `send_default_pii` disabled, request bodies not captured, and a scrubbing hook; otherwise rely on logs.

## 3. Backups

*As built (M8, ADR-023):* the `backup` container in `infra/prod/backup/` logs in as a member of `app_backup` (migration `0015`), pipes `pg_dump -Fc` into `age` encrypted to both admins' public keys, copies the file off-site with `rclone`, and keeps 30 daily and 12 monthly copies there (7 on the server). Every hour it also writes the withdrawal requests (ids and states only) as an encrypted CSV, kept 7 days, for step 2 of §4. Each run, failed or not, adds a row to `backup_runs`. How to run and check it: [ops/RUNBOOK.md §4](ops/RUNBOOK.md#4-backups).

| What | How | Frequency | Retention | Where |
|------|-----|-----------|-----------|-------|
| PostgreSQL | `pg_dump -Fc` → encrypt (`age`, public key on server, private key offline with two admins) → upload | Nightly + before each deploy | 30 daily, 12 monthly | Backup bucket, separate credentials (write-only key on server) |
| `originals/` | Bucket versioning + (if supported) object lock; optional cross-provider replica later | Continuous | Versions retained ≥ 30 days after deletion except erasure | Primary storage |
| `consent-evidence/` | Versioning; included in replica | Continuous | Per retention policy | Primary storage |
| `derived/` | Not backed up (re-creatable from originals) | — | — | — |
| Configuration | Infra files in Git; secrets in password manager | On change | — | — |

## 4. Restore drills

*As built:* `infra/prod/backup/restore.sh` restores into an empty database, then `python -m app.cli verify-restore --withdrawal-log <decrypted log>` checks the schema version, checksums a sample of originals, and prints a `REDO withdrawal` line for each withdrawal completed after the backup. Steps: [ops/RUNBOOK.md §5](ops/RUNBOOK.md#5-restore-a-backup). Drill 0 (a rehearsal with synthetic data on a development machine) passed on 2026-10-18; the first drill on the real server is still to do.

- Quarterly: restore latest DB dump into a scratch environment, run integrity checks (row counts, foreign keys, checksum sample of originals).
- After any restore to production: **re-apply all completed withdrawal requests** made after the backup timestamp before reopening the service (the `withdrawal_requests` export is also kept outside the DB backup for this purpose).
- Record each drill (date, duration, problems) in [ops/restore-drills.md](ops/restore-drills.md).

## 5. Targets (pilot)

- RPO (max data loss): 24 hours for metadata; near-zero for originals (versioned storage).
- RTO (time to restore): 48 hours.
