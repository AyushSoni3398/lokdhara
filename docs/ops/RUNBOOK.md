# Server runbook

How to set up, update, back up and restore Lokdhara on one server with Docker Compose
(docs/DEPLOYMENT.md §5). The files are in `infra/prod/`. Nothing here has been run on a real
server yet: the hosting choice (Q-L7, Q-P5) is open, and the restore steps were rehearsed on a
development machine ([restore-drills.md](restore-drills.md)).

Commands run on the server as a maintainer with `sudo`, from the repository checkout in
`/opt/lokdhara`, with this alias:

```bash
alias dc='docker compose -f /opt/lokdhara/infra/prod/docker-compose.yml'
```

## 1. What you need first

- A virtual machine with Ubuntu 24.04 LTS, 2 vCPU, 4 GB RAM, a system disk and a second disk
  for the database (docs/INFRASTRUCTURE_AND_COSTS.md).
- A domain name with an A record pointing at the server.
- Private S3-compatible buckets for the app (five buckets, `infra/prod/env/app.env.example`),
  with versioning on for originals and consent evidence.
- A backup bucket at a **different** provider or account, with versioning on.
- Two admins, each with their own age key pair, made on their own computer:
  `age-keygen -o lokdhara-backup.key`. The private key never goes on the server; keep it
  offline (for example, on a USB stick in a safe place) and in the password manager. The
  public key (the `age1…` line) goes into `/etc/lokdhara/backup_recipients`.
- The password manager entry that holds every secret below, shared by at least two maintainers.

## 2. First-time setup

```bash
# Updates and firewall: SSH only from known addresses, web open to all.
sudo apt-get update && sudo apt-get install -y unattended-upgrades ufw git docker.io docker-compose-v2
sudo ufw default deny incoming && sudo ufw allow from <your office/home IP> to any port 22
sudo ufw allow 80,443/tcp && sudo ufw allow 443/udp && sudo ufw enable

# Database disk mounted at /srv/lokdhara (see the provider's guide), then:
sudo mkdir -p /srv/lokdhara/pgdata /srv/lokdhara/backups /etc/lokdhara
sudo chown 999:999 /srv/lokdhara/backups     # the backup container's user
sudo git clone https://github.com/AyushSoni3398/lokdhara.git /opt/lokdhara

# Settings: copy each example, fill it in, keep it private.
for f in app db web backup; do sudo cp /opt/lokdhara/infra/prod/env/$f.env.example /etc/lokdhara/$f.env; done
sudo nano /etc/lokdhara/app.env   # and db.env, web.env, backup.env
sudo nano /etc/lokdhara/backup_recipients   # both admins' age1… public keys, one per line
sudo chmod 600 /etc/lokdhara/*.env && sudo chmod 644 /etc/lokdhara/backup_recipients
```

Start the database, create the login roles, bring the schema up to date, and create the first
admin. The group roles `app_rw`, `app_erasure` and `app_backup` come from the migrations; the
logins below are members of them and are **not** the schema owner.

```bash
export LKD_GIT_COMMIT=$(git -C /opt/lokdhara rev-parse --short HEAD)
dc build
dc up -d db
dc run --rm migrate
dc exec db psql -U lokdhara -d lokdhara \
  -c "CREATE ROLE lokdhara_app LOGIN PASSWORD '<from app.env>' IN ROLE app_rw" \
  -c "CREATE ROLE lokdhara_eraser LOGIN PASSWORD '<from app.env>' IN ROLE app_erasure" \
  -c "CREATE ROLE lokdhara_backup LOGIN PASSWORD '<from backup.env>' IN ROLE app_backup"
dc up -d
dc run --rm api python -m app.cli create-admin --username <name> --display-name "<Name>"
```

Then check, from a computer outside the server:

- `https://<domain>/healthz` answers `{"status":"ok"}` and the app loads.
- The buckets are **not** public: opening `https://<storage endpoint>/<bucket>/` without
  credentials gives "Access Denied" for all five, and a signed playback link stops working after
  10 minutes (docs/ROADMAP.md M8 tests).
- `dc run --rm backup backup.sh database` prints `backup database ok` and the file appears in
  the backup bucket.
- Sign in as the admin, set up two-step sign-in when the app asks (an authenticator app on
  your phone; write the recovery codes on paper), then invite the second admin, who does the
  same at their first sign-in. Until then admin pages stay hidden (ADR-025).

## 3. Updating to a new version

Only from `main` with CI green.

```bash
cd /opt/lokdhara && sudo git pull origin main
export LKD_GIT_COMMIT=$(git rev-parse --short HEAD)
dc build
dc run --rm backup backup.sh database   # always a fresh backup before migrations
dc run --rm migrate
dc up -d
curl -fsS https://<domain>/healthz
```

Smoke test: sign in, open "my submissions", play one recording. To go back, check out the
previous commit and repeat; if a migration has to be undone, restore the backup taken just
before it (§5) rather than downgrading on live data.

## 4. Backups

The `backup` container (ADR-023) writes, encrypted to the admins' public keys:

| What | When | Kept on the server | Kept off-site |
|------|------|--------------------|---------------|
| Database (`lokdhara-db-*.dump.age`) | Daily at 21:30 UTC (03:00 IST) and before each update | Last 7 | 30 daily + 12 monthly |
| Withdrawal log (`lokdhara-withdrawals-*.csv.age`) | Every hour at half past | Last 48 | 7 days |

Every run adds a row to `backup_runs`; a failed run says which step failed. To look:

```bash
dc logs --tail 20 backup
dc exec db psql -U lokdhara -d lokdhara -c \
  "SELECT kind, finished_at, succeeded, size_bytes, detail FROM backup_runs ORDER BY finished_at DESC LIMIT 5"
```

Originals and consent evidence are not in these dumps; they are protected by bucket versioning.
Derived files are not backed up; they can be made again from the originals.

## 5. Restore a backup

For a drill, restore into a scratch database on the server (or a spare server) while the
service keeps running. For a real recovery, stop the app first: `dc stop api worker web`.

```bash
# 1. Bring one admin's private key for the restore only.
sudo install -m 600 -o 999 /media/usb/lokdhara-backup.key /srv/lokdhara/backups/restore.key

# 2. An empty target database (drill: lokdhara_drill; recovery: drop and recreate lokdhara).
dc exec db psql -U lokdhara -d postgres -c "CREATE DATABASE lokdhara_drill TEMPLATE template0"

# 3. Restore the chosen file (from the server, or fetched from off-site).
dc run --rm -e RESTORE_DATABASE_URL=postgresql://lokdhara:<owner password>@db:5432/lokdhara_drill \
  -e RESTORE_AGE_IDENTITY_FILE=/backups/restore.key backup restore.sh lokdhara-db-<time>.dump.age

# 4. Decrypt the newest withdrawal log and check the restored database.
dc run --rm backup sh -c 'age -d -i /backups/restore.key "$(ls /backups/lokdhara-withdrawals-*.csv.age | tail -1)" > /backups/withdrawals.csv'
dc run --rm -v /srv/lokdhara/backups/withdrawals.csv:/tmp/withdrawals.csv:ro \
  -e LKD_MIGRATION_DATABASE_URL=postgresql+psycopg://lokdhara:<owner password>@db:5432/lokdhara_drill \
  api python -m app.cli verify-restore --withdrawal-log /tmp/withdrawals.csv

# 5. Remove the key and the decrypted log.
sudo shred -u /srv/lokdhara/backups/restore.key /srv/lokdhara/backups/withdrawals.csv
```

If `verify-restore` prints `REDO withdrawal …`, log each one again in the admin withdrawal
screens and accept it, so the deletion runs again, **before** the service reopens; then run the
check again until it passes. A `PROBLEM` line means an original is missing or changed in
storage: stop and investigate before reopening. Record every drill in
[restore-drills.md](restore-drills.md), and drop the drill database afterwards
(`DROP DATABASE lokdhara_drill`).

## 6. Monitoring

- **Service status page:** admins open *Service status* from the home page. Anything that
  needs attention is listed first (ADR-024).
- **Daily digest:** set `LKD_SMTP_HOST`, `LKD_SMTP_USERNAME`, `LKD_SMTP_PASSWORD`,
  `LKD_SMTP_FROM` and `LKD_DIGEST_RECIPIENTS` in `/etc/lokdhara/app.env` (the institution's
  mail server, or any provider's SMTP), then `dc up -d worker`. The first digest goes out
  within a minute of the worker starting and then once a day. Without these settings the
  digest is only logged.
- **Uptime:** add `https://<domain>/healthz` to a free external uptime checker that emails
  the maintainers after three failed checks. It sees only that the site answers.
- **Logs:** `dc logs --since 1h api worker`. Logs never hold content, names or client
  addresses; Docker keeps 7 files of 50 MB per container.

## 7. A lost phone

If an admin has lost both their phone and their recovery codes, someone with server access runs:

```bash
dc run --rm api python -m app.cli reset-mfa --username <name>
```

It turns two-step sign-in off for that user and signs them out everywhere; they set it up again
at their next sign-in. Confirm who is asking (in person or by phone) before running it: anyone
who can make you run it can take over the account.
