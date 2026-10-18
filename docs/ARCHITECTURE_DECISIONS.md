# Architecture Decision Records

Each ADR records a decision, the alternatives, and **the conditions under which we would revisit it**. Status values: *Proposed* (awaiting the project owner's approval), *Accepted*, *Superseded by ADR-NNN*. Never edit an accepted ADR's decision in place; add a new ADR that supersedes it.

ADRs 001–019 were **Accepted** by the project owner on 2026-10-11 (ADR-019 after the Milestone 2 spike), ADR-020 on 2026-10-12, and ADR-021 (a decision by the professor) on 2026-10-14.

| # | Title | Status |
|---|-------|--------|
| 001 | Record decisions as ADRs in this file | Accepted |
| 002 | Modular monolith: one API process + one worker process | Accepted |
| 003 | React + TypeScript + Vite single-page app | Accepted |
| 004 | Python 3.13 + FastAPI backend | Accepted |
| 005 | PostgreSQL 18 as the single system of record | Accepted |
| 006 | S3-compatible object storage behind an interface | Accepted |
| 007 | PostgreSQL-backed job queue, no message broker | Accepted |
| 008 | Invite-only accounts with server-side sessions | Accepted |
| 009 | Originals are immutable; all processing creates derived artefacts | Accepted |
| 010 | Text stored verbatim; normalisation only in derived fields | Accepted |
| 011 | Text layers are append-only revisions with provenance | Accepted |
| 012 | Consent as versioned records with per-use permissions; effective access is the most restrictive rule | Accepted |
| 013 | Dataset releases are immutable manifests; export packages are generated, never committed | Accepted |
| 014 | No ASR/MT in the MVP; future model output is always a suggestion | Accepted |
| 015 | Single-VM Docker Compose deployment | Accepted |
| 016 | UUIDv7 internal IDs and pseudonymous public codes | Accepted |
| 017 | Repository holds code and documentation only | Accepted |
| 018 | Three recording modes (free, prompted, read) with a versioned prompt library | Accepted |
| 019 | In-house PostgreSQL job table instead of Procrastinate (refines ADR-007) | Accepted |
| 020 | Database triggers enforce column immutability and self-review; schema refinements from Milestone 2 | Accepted |
| 021 | No human reviewer: submissions are accepted after automatic checks and their text stays unverified | Accepted |
| 022 | Withdrawals: a separate module, deletion right after an admin accepts, PATCH releases only from the replaced release | Proposed |

---

## ADR-001 — Record decisions as ADRs in this file

- **Context:** Student teams rotate; decisions get lost.
- **Decision:** Keep ADRs in this single file until it exceeds ~1,000 lines, then split into `docs/adr/NNN-title.md`.
- **Alternatives:** One file per ADR from the start (more files to navigate for a small project); wiki (separate from code review).
- **Revisit when:** the file becomes hard to navigate.

## ADR-002 — Modular monolith

- **Context:** 2–5 part-time students; pilot-scale traffic; audio processing is slow and must not block requests.
- **Decision:** One Python codebase, two processes (`api`, `worker`), domain modules with explicit service boundaries.
- **Alternatives:** Microservices (operational cost, distributed transactions across consent/review data — rejected); single process with in-request processing (slow uploads, timeouts — rejected); serverless functions (cold starts with FFmpeg, vendor lock-in, harder local dev).
- **Cost:** Lowest.
- **Revisit when:** a component needs independent scaling that adding worker processes cannot provide (e.g., GPU ASR).

## ADR-003 — React + TypeScript + Vite SPA

- **Context:** All pages are behind sign-in; heavy client features (recording, drafts, editing).
- **Decision:** Static SPA, route-level code splitting, react-i18next.
- **Alternatives:** Next.js (adds a Node server runtime; SSR benefits unused), SvelteKit (smaller bundles, less team familiarity), HTMX (minimal JS but recording/draft features need JS anyway).
- **Revisit when:** a public, SEO-relevant site is required, or the contributor bundle cannot meet NFR-1 on real devices.

## ADR-004 — Python 3.13 + FastAPI

- **Context:** Audio processing and future NLP are Python ecosystems.
- **Decision:** FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2; uv for dependencies; ruff + mypy.
- **Alternatives:** Node + Fastify (two backend languages once Python processing is added); Django (strong admin, but heavier coupling; closest alternative).
- **Revisit when:** generic admin CRUD dominates effort (consider Django), or team skills shift strongly to TypeScript.

## ADR-005 — PostgreSQL 18

- **Context:** Highly relational data with integrity requirements (consent propagation), plus some flexible metadata.
- **Decision:** PostgreSQL 18; JSONB only for genuinely open-ended attributes; full-text (`simple`) + `pg_trgm` search; triggers to block UPDATE/DELETE on append-only tables.
- **Alternatives:** MongoDB (weaker enforced relationships); SQLite (insufficient concurrency, no row-level locking for job queue).
- **Revisit when:** search needs exceed Postgres at measured scale (add a search index, keep Postgres as record).

## ADR-006 — S3-compatible object storage behind an interface

- **Decision:** `ObjectStore` interface; `LocalObjectStore` for dev/tests, `S3ObjectStore` for staging/prod. Separate buckets (or prefixes with separate credentials) for `quarantine`, `originals`, `derived`, `consent-evidence`, `exports`. Versioning enabled on `originals`; object lock if the provider supports it.
- **Alternatives:** Local disk only (single point of failure); storing audio in Postgres (bloats DB and backups).
- **Revisit when:** the institution mandates a specific storage system.

## ADR-007 — PostgreSQL-backed job queue

- **Decision:** Jobs live in PostgreSQL and are claimed with `FOR UPDATE SKIP LOCKED`. Preferred library: Procrastinate; fallback: a minimal in-house `jobs` table if the spike in M2 shows Procrastinate is a poor fit. Each job run is also recorded in our own `processing_runs` table for provenance.
- **Alternatives:** Celery/RQ + Redis (another service to run and back up); cloud queues (vendor lock-in).
- **Revisit when:** sustained throughput exceeds what one Postgres comfortably handles (far beyond pilot scale).

## ADR-008 — Invite-only accounts with server-side sessions

- **Decision:** Admin invitations; Argon2id password hashes; opaque session token in `HttpOnly; Secure; SameSite=Lax` cookie; session rows in Postgres; CSRF token for unsafe methods; login rate limiting.
- **Alternatives:** JWT (hard revocation); managed auth vendor (third-party processor of personal data, residency questions); phone OTP (cost, SIM-swap risk).
- **Revisit when:** public self-registration is approved, or institutional SSO becomes available for staff.

## ADR-009 — Originals are immutable

- **Decision:** After validation, an original is written once to `originals/` and never modified. Every derived file records its source, parameters, tool versions, and checksum. Only the withdrawal/deletion process may delete originals, and it is audit-logged.
- **Alternatives:** Normalising in place (irreversible loss — rejected).
- **Revisit:** never for the principle.

## ADR-010 — Text stored verbatim

- **Decision:** `content_original` stores exactly what was submitted (after rejecting disallowed control characters). `content_nfc` is Unicode NFC. `content_normalized` follows a versioned normalisation policy and stays empty until the policy is agreed (Q-X2).
- **Alternatives:** Normalise on input (destroys orthographic evidence — rejected).
- **Revisit when:** never for originals; the policy itself is versioned.

## ADR-011 — Append-only text revisions with provenance

- **Decision:** Transcriptions, translations, and standalone texts are `text_layers`; each change creates a `text_revisions` row with `origin` (`human_contributor`, `human_reviewer`, `machine`, `imported`), author or tool+version, confidence (machine only), and `based_on_revision_id`. Optimistic concurrency on edits.
- **Alternatives:** Mutable rows + history table (easier to get wrong); generic JSON documents (weak integrity).
- **Revisit when:** time-aligned segments are introduced (they attach to revisions; no change to this rule).

## ADR-012 — Consent records and effective access

- **Decision:** Consent is captured against a versioned form; each permitted use is a separate boolean; changes create a new record that supersedes the old. Effective access = most restrictive of (current consent, restriction flags, review status). Computed in one service function and covered by tests.
- **Alternatives:** A single "public/private" flag (cannot express research-only vs. AI-training); per-submission ad-hoc flags (inconsistent).
- **Revisit when:** governance bodies define additional uses (add columns via migration; default `false`).

## ADR-013 — Immutable dataset releases

- **Decision:** A frozen release is a list of exact revision IDs and file checksums plus a data card. Export packages are built on demand into short-lived storage. Datasets are **never** committed to Git.
- **Alternatives:** Ad-hoc exports (not reproducible); Git LFS / DVC for data (puts data near the public code repo, and DVC remotes still need governance — reconsider only for derived, fully public datasets).
- **Revisit when:** datasets are approved for public publication (consider a research data repository with DOIs).

## ADR-014 — No ASR/MT in the MVP

- **Decision:** No automatic transcription or translation. The schema supports `origin = machine` revisions with tool, model ID, and confidence so suggestions can be added later, but they never count as verified until a human revision supersedes them, and they are excluded from "verified transcript" datasets.
- **Alternatives:** Use a multilingual ASR now (unvalidated for Mundari; licence constraints on some models; risk of contaminating ground truth).
- **Revisit when:** a reviewed test set exists to measure candidate models, and licences permit the intended use.

## ADR-015 — Single-VM Docker Compose deployment

- **Decision:** Production and staging each run Caddy, API, worker, and PostgreSQL via Docker Compose on one VM (or institutional server); object storage external; nightly encrypted backups to a separate bucket.
- **Alternatives:** PaaS (good fallback); Kubernetes (rejected).
- **Revisit when:** uptime needs exceed what one VM with backups can meet, or the institution provides managed hosting.

## ADR-016 — Identifiers

- **Decision:** UUIDv7 primary keys (PostgreSQL 18 `uuidv7()`); speakers have a separate pseudonymous code (e.g., `SPK-7Q3M9`) that contains no personal information; object keys contain only UUIDs, never names.
- **Revisit:** unlikely.

## ADR-017 — Repository holds code and documentation only

- **Decision:** No audio, no collected text, no consent documents, no personal data, no exports, no secrets in Git — enforced by `.gitignore`, a CI forbidden-file check, and secret scanning. Test fixtures are synthetic and generated at test time where possible.
- **Revisit:** never.

## ADR-018 — Three recording modes with a prompt library

- **Context:** The owner wants audio collected in the three standard modes used by speech corpora: free/spontaneous speech, prompted (image or situation) speech, and read speech. Each yields different data and suits different speakers.
- **Decision:** `submissions.recording_mode` records the mode; a versioned `prompts` table holds images, situations, and read sentences; submissions reference the exact prompt version. Read mode stores the prompt sentence as a `prompt_text` transcription revision that stays unverified until a reviewer confirms the reading. Details in `docs/RECORDING_MODES.md`.
- **Alternatives:** Free speech only (simplest, but unbalanced topics and slow transcription); storing prompt info in `collection_context` JSONB (weak integrity, hard to filter and export).
- **Revisit when:** a mode proves unusable in the field, or new modes (e.g., conversation between two speakers) are needed.

## ADR-019 — In-house PostgreSQL job table instead of Procrastinate

- **Status:** Accepted (project owner, 2026-10-11, after the Milestone 2 spike); refines ADR-007, which allowed this fallback.
- **Context:** The M2 spike checked Procrastinate 3.10 against our needs. (1) Jobs must be enqueued in the **same transaction** as the domain change (e.g. a recording row and its validation job), but Procrastinate's SQLAlchemy connector supports only psycopg2 and opens its own connections, while we use psycopg 3 sessions. (2) It ships its own 600-line schema and 39 versioned SQL migrations that must be applied in step with library upgrades, a second migration system next to Alembic. (3) Its worker is async-first, while our handlers are synchronous (FFmpeg subprocesses, SQLAlchemy sessions).
- **Decision:** A `jobs` table owned by our migrations. `enqueue()` inserts into the caller's session, so it commits or rolls back with the domain change. Workers claim one due job with `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`, holding a lease (`LKD_WORKER_LEASE_SECONDS`); a job whose lease expires is taken by another worker. Failures retry with exponential backoff (30 s doubling, capped at 1 h) up to `max_attempts`; `JobError(retryable=False)` fails at once. Handler writes commit atomically with the success record and roll back on failure. Every attempt appends a `processing_runs` row. A partial unique index on `dedupe_key` allows at most one pending job per key. Admins list failed jobs and retry them (audited).
- **Alternatives:** Procrastinate (above); Celery/RQ + Redis (rejected in ADR-007).
- **Consequences:** About 250 lines of code we own and test (`backend/app/modules/processing/queue.py`, `tests/test_jobs.py`). No scheduling or cron features: periodic jobs (quarantine cleanup) will be enqueued by a small scheduler loop when needed.
- **Revisit when:** we need scheduled/periodic jobs, job priorities, or throughput beyond a few workers.

## ADR-020 — Database triggers enforce column immutability and self-review

- **Status:** Accepted (project owner, 2026-10-12; implemented by migrations `0004`–`0007`); refines ADR-009, ADR-011, ADR-012.
- **Context:** DATABASE_SCHEMA.md marks several tables 🧊 but also says some of their columns change later (consent status, prompt status, revision verification, recording validation results). A whole-row append-only trigger cannot express that, and leaving it to the services means one bug could rewrite consent or provenance. Writing the migrations also showed gaps in the proposed schema.
- **Decision:** Two reusable trigger functions, with the same erasure-routine exception as `lkd_reject_change()`:
  - `lkd_guard_columns(mutable…)`: the row is append-only except the listed columns. Used for `consent_forms` (`retired_at`), `consent_records` (`status`), `prompts` (`status`, `approved_by`), `text_revisions` (`verification_status`).
  - `lkd_freeze_columns(frozen…)`: the listed columns never change; others may. Used for `speakers`, `submissions`, `recordings`, `text_layers` identity columns.
  - A `BEFORE INSERT` trigger on `review_events` rejects any action other than `comment` by the submission's own submitter (the service checks this too).
  - Refinements to the proposed schema: `consent_forms.is_test_form` (default true; real forms need Q-L3) and a CHECK that `text_sha256` matches `body_markdown`; `consent_records` CHECKs for oral evidence, paper reference, and guardian fields; `withdrawal_requests.recorded_by`; a `playback_aac` rendition kind (iPhone playback); `renditions.params_sha256` replaces the undefined `params_hash`; `speaker_identities.key_version` for key rotation; `app_readonly` cannot read `speaker_identities`.
- **Alternatives:** Service-only enforcement (one code path away from silent rewrites); separate history tables for every mutable column (more tables and joins for little gain at MVP scale).
- **Consequences:** Rule violations surface as database errors with stable prefixes (`append_only:`, `immutable_columns:`, `self_review:`) that services map to problem details. Schema changes to guarded tables must update the trigger's column list in the same migration.
- **Revisit when:** a guarded column needs a legitimate correction workflow (add a dedicated routine, like erasure), or trigger overhead shows up in profiling.

## ADR-021 — No human reviewer: accept after automatic checks, keep text unverified

- **Status:** Accepted (professor's decision, confirmed by the project owner on 2026-10-14; answers Q-P3). Narrows the review parts of ADR-011, ADR-018 and ADR-020, and the review workflow in PRODUCT_REQUIREMENTS §5.5, USER_FLOWS F4 and ROADMAP M6.
- **Context:** The plan assumed Mundari-literate reviewers who listen to every submission and approve it before it can enter a dataset. The team has nobody who can do that, and none is expected for the pilot.
- **Decision:**
  - A submission whose automatic checks all succeed moves straight to a new status, `accepted`. Nobody approves it first. The checks that reject input (file type, decoding, duration, consent) and the advisory warnings (silence, clipping, script mismatch, possible duplicates) stay as they are.
  - Contributor text is kept as **contributor-provided and unverified** (`verification_status = unverified`). In read mode the prompt sentence stays the reference transcription, also unverified. No screen, export, manifest or data card calls such text "verified".
  - Clean-up still needs a person now and then, but not a review of everything: any signed-in user can **report** an item (personal information, a third party's voice, culturally restricted content, wrong content), and an admin can **hide** it by setting a restriction flag or record a withdrawal. Hidden and withdrawn items never reach a release.
  - The review tables and statuses from M2 (`review_events`, `in_review`, `changes_requested`, `approved`, `rejected`, the self-review trigger) stay in the schema, unused for now, so that peer checking can be added later without a migration that drops data.
- **Alternatives:** Keep the reviewer queue and let the admin approve everything (one person becomes the bottleneck and would approve without understanding the language); peer voting among contributors as in Mozilla Common Voice (a good later step, but needs enough active contributors first); marking text "verified" when it came from read mode (false, since speakers do not always read exactly what is shown).
- **Consequences:** Datasets are honest but noisier: data cards must say that transcriptions are unverified. Pre-freeze checks D1 and D5 change (DATA_QUALITY_AND_VALIDATION §4). M6 shrinks to reporting, admin hiding and the researcher catalogue. Existing `awaiting_review` rows move to `accepted` in migration `0010`.
- **Revisit when:** Mundari-literate volunteers or paid reviewers become available, or enough contributors are active for peer checking.

## ADR-022 — Withdrawals: deletion right after acceptance, PATCH releases from the replaced release

- **Status:** Proposed (built in M7 part 2, 2026-10-16; awaiting the project owner's approval). Implements DATA_RETENTION_AND_DELETION §2–3 and DATASET_VERSIONING §2.
- **Context:** A speaker can take back one item, everything, or some uses. The plan left open when deletion runs, what happens to frozen releases (which never change), what a PATCH release may contain, and whether proof of consent survives a withdrawal.
- **Decision:**
  - A `withdrawals` module owns the request workflow (`received` → `verified` or `rejected` → `completed`). The `withdrawal_requests` table stays in the consents area of the schema; who logged a request and what was asked never change (trigger, migration `0014`).
  - Accepting a request (`verify`) hides the items at once and queues the deletion job in the same transaction; there is no waiting period. Accepting is the admin's point of no return, so the screen asks once more.
  - The deletion job runs as `app_erasure`. It deletes every stored version of the originals (quarantine and originals buckets), renditions and the `items.jsonl` of releases that held the items; empties the text revisions, the title and context, report notes, and, for a whole withdrawal, the identity and demographics. Rows stay as tombstones so manifests remain readable. Audio jobs that were running re-check and delete what they made.
  - Frozen releases are not changed. Their items get `withdrawn_after_release_at`, their ready packages are deleted and new export requests are refused. The release shows how many items were withdrawn.
  - A PATCH release is a draft that names the release it replaces. It can only take items of that release (so withdrawn, hidden and no longer allowed items stay out), keeps its purpose, and freezes as the same MAJOR.MINOR with a higher PATCH. Its data card starts with a notice.
  - A narrower consent (fewer uses) is a new consent record; it marks frozen releases for the purposes it no longer allows. Widening consent later does not unmark them.
  - The consent records, the request and the oral consent recording are kept by default (`LKD_WITHDRAWAL_KEEP_CONSENT_EVIDENCE=true`) until Q-G8 is answered.
- **Alternatives:** A 30-day delay before deletion (a speaker could change their mind, but data stays longer and a second admin step is needed); rewriting frozen releases (breaks reproducibility of published results); a PATCH draft with fresh selection criteria (could add new items, which is a MINOR change); deleting consent evidence at once (cannot be undone if the institution needs proof).
- **Consequences:** A mistaken acceptance cannot be undone except from backups, so admins must check the requester first. Export holders are not notified by the system yet; that waits for the data-use agreement (Q-G5). Backups keep deleted data until they age out (DATA_RETENTION_AND_DELETION §2).
- **Revisit when:** the ethics committee answers Q-G8 or asks for a cooling-off period, or legal holds (§5) need to pause deletions.

## ADR-023 — Backups: pg_dump encrypted with age, copied off-site with rclone, checked by a restore command

- **Status:** Proposed (built in M8 part 1, 2026-10-18; awaiting the project owner's approval). Implements OBSERVABILITY_AND_BACKUPS §3–4.
- **Context:** The plan asked for nightly encrypted database dumps kept 30 days and 12 months, a private key the server never holds, a status row the admin page can check, and a restore that re-applies withdrawals made after the backup. The hosting provider is not chosen yet (Q-L7, Q-P5), so the off-site copy cannot depend on one provider's tools.
- **Decision:**
  - A `backup` container built from `postgres:18` (so `pg_dump` matches the server) runs `pg_dump -Fc`, piped straight into `age` with the admins' public keys; nothing unencrypted is written to disk. `rclone` copies each file to a bucket at a different provider or account, which works with any S3-compatible service.
  - The container logs in as a member of a new group role `app_backup` (migration `0015`): it reads every table, speaker identities included, and inserts only into `backup_runs`, one unchangeable row per run.
  - Every hour it also writes the withdrawal requests (ids and states only) as an encrypted CSV. After a restore, `python -m app.cli verify-restore --withdrawal-log …` lists the withdrawals completed after the backup, which must be carried out again before the service reopens. The same command checks the schema version and checksums a sample of originals.
  - `restore.sh` restores only into an empty database and creates the cluster-wide group roles first, because a dump does not carry them.
- **Alternatives:** WAL archiving with pgBackRest or WAL-G (a smaller loss window, but more to run and learn than the 24-hour RPO needs); the provider's own volume snapshots (not encrypted with our keys, and tied to a provider not yet chosen); GPG instead of age (more options to get wrong).
- **Consequences:** Up to 24 hours of metadata can be lost (the RPO in §5); originals are protected by bucket versioning, not by these dumps. Losing both admins' private keys makes every backup unreadable, so each admin keeps theirs offline and the keys are checked at every drill. The identity encryption key must be kept in the password manager too, or restored identities cannot be read. Backups keep withdrawn data until they age out (DATA_RETENTION_AND_DELETION §2).
- **Revisit when:** the pilot needs a loss window shorter than a day, or the chosen provider offers encrypted, off-account backups that meet §3.
