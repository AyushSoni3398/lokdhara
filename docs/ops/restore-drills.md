# Restore drills

Each drill restores the latest database backup into a scratch database, runs
`python -m app.cli verify-restore`, and is recorded here (docs/OBSERVABILITY_AND_BACKUPS.md §4).
The procedure is in [RUNBOOK.md §5](RUNBOOK.md#5-restore-a-backup). Quarterly once the pilot
runs, and after any change to the backup scripts.

| # | Date | Where | Backup restored | Time to restore | Result | Problems found |
|---|------|-------|-----------------|-----------------|--------|----------------|
| 0 | 2026-10-18 | Development machine, synthetic data only (rehearsal, not a server) | Nightly dump of 5 synthetic contributors, 10 tone recordings | under 1 s for a 140 KB dump | Passed after redoing one withdrawal | See below |

## Drill 0: rehearsal before the server exists (2026-10-18)

Run with the scripts in `infra/prod/backup/` against a local PostgreSQL, local file storage,
and a local folder standing in for the off-site bucket. Everything was synthetic: accounts made
for the drill, the test consent form, and generated tones.

1. Five contributors gave consent and sent two recordings each; the worker checked and
   promoted all ten.
2. `backup.sh database` wrote an encrypted dump (to two age keys) and copied it off-site.
3. After the backup, one contributor withdrew everything; the deletion routine removed their
   two originals and derived files, and the request was completed. `backup.sh withdrawal-log`
   then wrote the hourly log.
4. The local copy of the dump was deleted, and `restore.sh` fetched it from the off-site
   folder and restored it into an empty database with the second admin's key.
5. `verify-restore` passed the schema check (0015) and the checksums of 8 originals, did not
   check the 2 originals deleted by the withdrawal, and failed on purpose with
   `REDO withdrawal …` for the lost withdrawal.
6. The withdrawal was logged and carried out again on the restored database;
   `verify-restore` then passed.

Problems found and fixed before the scripts were committed:

- Removing old off-site copies failed when the `monthly/` folder did not exist yet (the first
  month); folders that do not exist are now skipped.
- `verify-restore` could not read `alembic_version` as the app's login role; it now connects
  as the schema owner (`LKD_MIGRATION_DATABASE_URL`).
- Originals deleted by a withdrawal after the backup were reported as missing; they are now
  counted separately, and a completed new request for the same speaker clears the redo line.
- A target database made from a customised `template1` already held a function the dump
  creates; the runbook creates the target `TEMPLATE template0`.

Also checked: after the restore the app's login role could read data and was still refused
`DELETE` on `audit_events` (grants and append-only triggers came back with the dump).

Still to do on the real server: the same drill with the production images (PostgreSQL 18), the
real off-site bucket, and each admin's own key.
