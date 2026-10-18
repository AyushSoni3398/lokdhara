# Deployment

Status: **Server files built in M8 (2026-10-18): `infra/prod/` and the step-by-step [ops/RUNBOOK.md](ops/RUNBOOK.md). No server exists yet and no paid services are used; the hosting choice waits on Q-L7 and Q-P5.**

## 1. Local development (Milestone 1)

Target experience:

```bash
git clone <repo>
cp .env.example .env            # fill local-only values; never commit .env
docker compose -f infra/docker-compose.yml up -d db   # PostgreSQL 18
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
uv run python -m app.worker     # in another terminal
cd frontend && npm ci && npm run dev
```

- Object storage in development: local filesystem adapter under `./.local-storage/` (git-ignored).
- FFmpeg: installed locally or run the worker in the Compose `worker` service. The pinned version is 6.1 from Ubuntu 24.04 ([AUDIO_PROCESSING_PIPELINE.md](AUDIO_PROCESSING_PIPELINE.md)); on Ubuntu, `sudo apt-get install ffmpeg`.
- Seed command creates synthetic users (one per role) and generated audio fixtures — never real data.

## 2. Environment variables

Documented in [`.env.example`](../.env.example). Categories: app (`LKD_ENV`, `LKD_BASE_URL`, `LKD_SECRET_KEY`), database (`LKD_DATABASE_URL`), storage (`LKD_STORAGE_BACKEND`, bucket names, endpoint, credentials), limits (`LKD_MAX_UPLOAD_BYTES`, `LKD_MAX_AUDIO_SECONDS`), encryption (`LKD_IDENTITY_ENCRYPTION_KEY`), observability (`LKD_SENTRY_DSN` optional).

Production secrets live in the host's secret mechanism (environment file outside the repo with `600` permissions, or the platform's secret store), owned by at least two maintainers.

## 3. Database migrations

- Alembic, one migration per coherent schema change, reviewed like code.
- Never edit a migration that has been applied anywhere shared (staging/prod); write a new one.
- Destructive changes (drop column/table) use expand → migrate → contract across two releases.
- Migrations run as a separate step before the new app version starts (`alembic upgrade head` in a one-off container) under the schema-owner role (`LKD_MIGRATION_DATABASE_URL`).
- The API and worker connect (`LKD_DATABASE_URL`) as a login role that is a member of `app_rw` and is **not** the schema owner or a superuser, e.g. `CREATE ROLE lokdhara_app LOGIN PASSWORD '…' IN ROLE app_rw;`. The withdrawal routine (the worker's `withdrawal.erase` job) connects with `LKD_ERASURE_DATABASE_URL` as a separate login role in `app_erasure`, e.g. `CREATE ROLE lokdhara_eraser LOGIN PASSWORD '…' IN ROLE app_erasure;`; only that role can clear rows the append-only triggers protect. Its storage credentials need `s3:DeleteObjectVersion` so earlier versions of a withdrawn file are deleted too; an object-lock retention on originals would stop that, so use versioning without compliance-mode locks.
- Run uvicorn with `--proxy-headers --forwarded-allow-ips=<Caddy's address>` so the client IP used for per-network sign-in throttling is the real client, not Caddy (otherwise one network limit would apply to everyone).
- Also run uvicorn with `--timeout-keep-alive 75` and give Caddy's `reverse_proxy` a shorter upstream keep-alive (`transport http { keepalive 60s }`), so uvicorn never closes an idle connection that Caddy is about to reuse. With uvicorn's 5 s default, the load test saw requests fail with "connection reset" ([LOAD_TESTING.md](LOAD_TESTING.md)).
- The first administrator is created on the server with `uv run python -m app.cli create-admin`; everyone else joins by invitation.
- CI tests upgrade → downgrade → upgrade on an empty DB.

## 4. CI/CD

| Stage | Trigger | Action |
|-------|---------|--------|
| CI | Every push / PR | Checks in [TESTING_STRATEGY.md §4](TESTING_STRATEGY.md#4-ci-checks-github-actions-proposed) |
| Build | Merge to `main` | Build API/worker image and SPA bundle; tag with commit SHA |
| Staging deploy | Manual approval (initially) | Pull image, run migrations, restart, smoke tests |
| Production deploy | Manual approval by a maintainer, after staging | Same, plus pre-deploy DB backup |

Deployment credentials (SSH key or platform token) are GitHub Actions environment secrets configured by the repository owner — **not configured during planning**.

## 5. Production topology (Scenario A or B in [INFRASTRUCTURE_AND_COSTS.md](INFRASTRUCTURE_AND_COSTS.md))

*As built:* `infra/prod/docker-compose.yml`, `infra/prod/Caddyfile`, the backup container in `infra/prod/backup/`, and one example settings file per container in `infra/prod/env/`. Images are built on the server from the checked-out commit and tagged with it. Caddy sends HSTS, a Content-Security-Policy that allows scripts and styles only from the site itself, and keeps client addresses out of its access log. The API trusts forwarded client addresses only from Caddy's fixed address on the Compose network.

```
VM (Ubuntu LTS, unattended security updates, firewall: 22 restricted, 80/443 open)
└── docker compose
    ├── caddy      (TLS via Let's Encrypt, static SPA, reverse proxy /api)
    ├── api        (uvicorn, N workers)
    ├── worker     (FFmpeg; no inbound ports; egress only to DB + storage)
    ├── db         (PostgreSQL 18, volume on separate disk)
    └── backup     (pg_dump → age → rclone to an off-site bucket; ADR-023)
Object storage (external, private buckets)
```

## 6. Recovery from failed processing jobs

| Situation | Procedure |
|-----------|-----------|
| Single job failed (deterministic) | Submission `rejected_invalid` with reason; contributor informed. |
| Jobs failing after a deploy | Roll back image; re-queue affected jobs from admin dashboard (idempotent). |
| Worker crashed mid-job | Lock expires; job retried automatically. |
| Storage outage | Jobs fail with infrastructure error and retry with backoff; uploads return `503` with `Retry-After`; SPA keeps drafts. |
| Bulk reprocessing needed (e.g., new rendition parameters) | Admin command enqueues jobs in batches; originals untouched; new renditions keyed by params hash. |

## 7. Release checklist

- [ ] CI green on the commit.
- [ ] Migration reviewed; backup taken.
- [ ] Docs updated if behaviour changed (AGENTS.md rule).
- [ ] Staging smoke test passed (login, upload fixture, review, playback).
- [ ] Rollback plan noted in the release notes.

## 8. Resource inventory (to maintain once anything exists)

| Resource | Provider | Owner account | Purpose | Monthly cost |
|----------|----------|---------------|---------|--------------|
| — | — | — | — | — |
