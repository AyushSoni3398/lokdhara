# System Architecture

Status: **Proposed** · Diagrams: [ARCHITECTURE_DIAGRAM.md](ARCHITECTURE_DIAGRAM.md) · Decisions: [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md)

## 1. Shape of the system

Lokdhara is a **modular monolith**: one backend codebase deployed as two processes (an HTTP API and a background worker) sharing one PostgreSQL database and one object store. The frontend is a static single-page app served by the same reverse proxy.

```
Browser (React SPA) ──HTTPS──► Caddy ──► FastAPI app (api process)
                                   │          │
                                   │          ├── PostgreSQL (metadata, consent, revisions, jobs, audit)
                                   │          └── Object store (originals, derived, consent evidence, exports)
                                   │
                                   └── static SPA files
                         Worker process (same codebase) ── polls job queue in PostgreSQL,
                                                           runs ffprobe/ffmpeg, writes derived files
```

Why this shape: a small student team can run, debug, and back up one database and one codebase. Separating the worker keeps slow audio processing out of web requests without introducing a message broker.

## 2. Components

| Component | Responsibility | Not responsible for |
|-----------|----------------|---------------------|
| **SPA (frontend/)** | UI in Hindi/English; browser recording; on-device drafts (IndexedDB); upload with retry; review editor; researcher search | Any authorisation decision (server decides everything) |
| **Reverse proxy (Caddy)** | TLS, HTTP/2, compression, static files, request size cap, basic rate limiting at the edge | Business logic |
| **API (backend/app)** | Authentication, authorisation, validation of input, writes to DB, streaming uploads into quarantine, issuing signed playback URLs, enqueuing jobs, audit logging | Heavy audio processing |
| **Worker (backend/app, `worker` entrypoint)** | Audio validation/probing, renditions, quality metrics, duplicate hashing, text derivation, dataset export packaging, scheduled cleanups | Serving HTTP |
| **PostgreSQL** | System of record for everything except binary files; job queue; audit log | Storing audio blobs |
| **Object store** | Binary files, separated by sensitivity into buckets/prefixes | Access control decisions (API issues short-lived signed URLs) |

## 3. Backend module boundaries

Inside the monolith, code is organised by **domain module**, each with its own models, service functions, and API router. Modules call each other through service functions, not by reaching into each other's tables.

| Module | Owns tables | Key services |
|--------|-------------|-------------|
| `identity` | users, user_roles, sessions, invitations | sign-in, role checks |
| `speakers` | speakers, speaker_identities | create speaker, restricted identity access |
| `consents` | consent_forms, consent_records | capture consent, compute effective permissions |
| `withdrawals` | withdrawal_requests | log, accept, refuse and close requests; deletion job as `app_erasure` (ADR-022) |
| `submissions` | submissions, recordings, renditions, text_layers, text_revisions | create draft, accept upload, add revisions |
| `prompts` | prompts | prompt library for prompted and read speech (ADR-018): pick next prompt, versioned editing, approval |
| `processing` | processing_runs (+ queue tables) | enqueue, run, retry, record tool versions |
| `review` | review_events, restrictions | queue, decisions, restriction flags |
| `datasets` | dataset_releases, dataset_release_items, export_requests | preview, freeze, build export |
| `audit` | audit_events | append-only logging |
| `storage` (infrastructure) | — | `ObjectStore` interface: local and S3 adapters |

Proposed layout (created in Milestone 1, not now):

```
backend/
  pyproject.toml
  app/
    main.py              # FastAPI app factory
    worker.py            # worker entrypoint
    config.py            # pydantic-settings
    db.py
    modules/
      identity/  speakers/  consents/  prompts/  submissions/
      processing/  review/  datasets/  audit/
        (each: models.py, schemas.py, service.py, router.py)
        (names must pass scripts/check-forbidden-files.sh, hence "consents")
    object_store/        # ObjectStore + adapters (not "storage/": CI blocks that name for data)
    audio/               # ffprobe/ffmpeg wrappers, pure functions
    text/                # normalisation, script detection, pure functions
  migrations/            # Alembic
  tests/
frontend/
  package.json  vite.config.ts  src/
infra/
  docker-compose.yml  Caddyfile
```

## 4. Key runtime flows

### 4.1 Upload

The SPA keeps each draft, recording included, in IndexedDB from its first step. On "Save and upload" it runs the steps below in order and saves its progress on the device after each one, so a retry continues where it stopped: create the submission (repeatable through `client_submission_id`), upload the recording, add the text layers, submit. Lost connections and `429`/`5xx` answers are retried after 10 s, 30 s, 1 min, then every 5 min, and at once when the browser is back online. The draft leaves the device only after the submit succeeds. Drafts belong to the signed-in user, so a shared phone never uploads one person's draft under another person's account.

1. SPA sends `POST /api/v1/submissions/{id}/recordings` (multipart) with an `Idempotency-Key`.
2. API checks session, role, ownership, the speaker's active consent, and the per-user upload rate; checks the leading bytes against allowed signatures; streams bytes to `quarantine/` while counting them and computing SHA-256. The key (`{yyyy}/{mm}/{recording_id}/original.{ext}`) is chosen here and reused in `originals/`, so `original_object_key` never changes.
3. API creates a `recordings` row (`upload_status = quarantined`); if the row cannot be written, the quarantine object is deleted again.
4. The SPA then calls `POST /submissions/{id}/submit`, which attaches the consent record, sets `processing`, and enqueues `audio.validate` in the same transaction. Drafts are never processed.
5. Worker runs ffprobe + full decode; on success copies to `originals/` (write-once), computes metrics, creates renditions, sets `accepted` (no human review, ADR-021); on failure marks `rejected_invalid` with a reason and deletes the quarantine object after the retention window.

### 4.2 Playback

The API never streams audio through Python for normal playback. It checks permission, writes an audit event for restricted items, and returns a short-lived signed URL for the **playback rendition**: an S3 presigned URL in staging and production, or, with the local development adapter, an HMAC-signed `/api/v1/local-storage/…` URL served by the API (that route is only mounted when `LKD_STORAGE_BACKEND=local` in development or test). Only `derived` and `exports` objects can ever be signed; originals, quarantine, and consent evidence cannot.

### 4.3 Text revision

`POST /text-layers/{id}/revisions` with `base_revision_id`. If the base is not the current revision, the API returns `409 Conflict` (optimistic concurrency) so two reviewers cannot silently overwrite each other.

### 4.4 Dataset release

Freezing a release writes `dataset_release_items` rows pointing at exact revision IDs and a manifest checksum. Export packaging is a worker job that reads only those rows.

## 5. Cross-cutting concerns

| Concern | Approach |
|---------|---------|
| Configuration | Environment variables via pydantic-settings; `.env.example` documents them; no secrets in code. |
| Errors | RFC 9457 `application/problem+json` responses; no stack traces to clients. |
| Logging | JSON logs with request ID; never log audio content, text content, names, or tokens. |
| i18n | Frontend message catalogues (`hi`, `en`); API returns error *codes* the SPA translates. |
| Time | All timestamps `timestamptz` in UTC; display in IST. |
| IDs | UUIDv7 primary keys; human-friendly codes only where needed (speaker codes, release versions). |
| Idempotency | `Idempotency-Key` header on create/upload endpoints; stored for 24 h. |
| Rate limiting | Per-IP at proxy; per-user in API for login and upload. |

## 6. Scaling path (only when measured)

| Trigger | Step |
|---------|------|
| Uploads saturate API bandwidth | Presigned direct-to-bucket uploads into quarantine. |
| Processing backlog > 1 day | Run more worker processes (same image). |
| Search slow at scale | Tune indexes; consider a search engine only after measuring. |
| Need for ASR suggestions | Separate GPU worker consuming the same job queue, writing `origin = machine` revisions. |

Splitting into services is not on this path unless the team and load grow substantially.
