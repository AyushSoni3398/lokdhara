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
| 008 | Invite-only accounts with server-side sessions | Accepted; sign-up part superseded by ADR-028 |
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
| 026 | Contributors download listening copies of their own recordings, one at a time or all as a zip | Proposed |
| 028 | Public sign-up for contributors; profile and consent asked once; minors with a guardian (guardian part replaced by ADR-032) | Proposed |
| 029 | Every download says what each recording is: full item details, spreadsheets, tags in the audio | Proposed |
| 030 | Topics: a list admins extend, chosen per item and carried into every download | Proposed |
| 031 | One "I accept" tick on the consent page | Accepted |
| 032 | Owner's answers of 2026-10-29: no ethics approval, minors without a guardian, nothing restricted, consent proof kept one month, facilitators record others | Accepted |

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
  - The consent records and the request are kept. The oral consent recording is kept for one month and then deleted (`LKD_WITHDRAWAL_CONSENT_EVIDENCE_DAYS=30`, ADR-032, Q-G8).
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

## ADR-024 — Monitoring: an admin status page and a daily email digest, no metrics stack

- **Status:** Proposed (built in M8 part 2, 2026-10-18; awaiting the project owner's approval). Implements OBSERVABILITY_AND_BACKUPS §2.
- **Context:** A student team will look after the pilot server part-time. They need to know when backups stop, the worker stalls, checks fail, or the disk fills, without running Prometheus, Grafana and an alert manager. The plan left the digest's delivery channel open.
- **Decision:**
  - `GET /admin/status` and the *Service status* page gather counts and times from the database (jobs, `backup_runs`, submissions, failed sign-ins from the audit log, open reports, withdrawals and export approvals), the database size and the disk use. A pure `alerts()` function turns them into codes with the thresholds of §2.
  - A periodic `ops.digest` job (migration `0016`) writes the same facts as a plain-text email once a day and sends it through SMTP, with STARTTLS, using Python's standard library. Without a mail server and recipients it only logs.
  - The digest and the page hold counts and times only, never names, contacts, client addresses or contributed content, so an ordinary mail provider may carry it.
  - Uptime is checked from outside by a free external monitor on `/healthz`, which learns only that the site answers.
- **Alternatives:** Prometheus with Grafana (more to run and secure than a part-time team can manage); a hosted error and metrics service (sends request data to a third party and needs its own ADR); a chat webhook such as Slack or Telegram (another account to manage, and not every maintainer uses one).
- **Consequences:** Problems are noticed within a day by email, or at once by an admin who opens the page; there is no paging at night, which the pilot does not need. The 5xx error rate is not tracked until an optional error tracker is added. The SMTP password is one more secret in `app.env`.
- **Revisit when:** the service grows past one server, or the team needs alerts faster than daily.

## ADR-025 — Two-step sign-in for admins: TOTP built in, recovery codes, reset on the server

- **Status:** Proposed (built in M8 part 3, 2026-10-18; awaiting the project owner's approval). Implements the MFA row of ACCESS_CONTROL §4.
- **Context:** An admin account can hide items, accept withdrawals (which delete data), approve exports and grant roles. A stolen or guessed admin password would be the worst single failure, so the plan called for TOTP for admins in M8. ADR-008 rules out managed auth services, so the second step has to be built in.
- **Decision:**
  - Time-based codes (RFC 6238: SHA-1, 6 digits, 30 seconds), which every common authenticator app supports, implemented with Python's standard library and checked against the RFC's test vectors. A code is accepted one step either side of the current one and never twice (`last_used_step`).
  - The secret is encrypted with AES-256-GCM under a key derived (HKDF) from `LKD_IDENTITY_ENCRYPTION_KEY` and bound to the user (migration `0017`). The setup QR code is drawn on the server with `segno`, a small pure-Python library, so the secret never goes to an outside service.
  - Ten one-time recovery codes are shown once at setup and stored as keyed hashes.
  - The login request carries the code in the same request as the password (`401 mfa_required` asks for it), so there is no half-signed-in session state. Wrong codes count towards the existing per-account and per-network lockout.
  - `LKD_REQUIRE_ADMIN_MFA` (on outside development and test): an admin without two-step sign-in has every role except admin until they set it up. The rule is applied where sessions are resolved, so every admin check, including those inside services, sees the same roles. Confirming setup signs out the user's other sessions.
  - Turning it off for a lost phone is a server command (`python -m app.cli reset-mfa`), not a button: it signs the user out everywhere and is audited.
- **Alternatives:** WebAuthn passkeys (stronger, but more code and harder to support on the shared and older phones in the field; a later addition); SMS codes (cost, SIM-swap risk, and phone numbers would have to be stored); an admin button to reset another admin (a single compromised admin could then remove the other's protection).
- **Consequences:** Admins need a smartphone authenticator app and must keep their recovery codes. Losing both needs someone with server access. The identity encryption key now also protects sign-in, one more reason to keep it in the password manager. Other roles can turn two-step sign-in on but are not required to.
- **Revisit when:** passkeys are well supported on the phones the team uses, or facilitators get wider powers.

## ADR-026 — Contributors download listening copies of their own recordings

- **Status:** Proposed (built 2026-10-22 on the project owner's request; awaiting approval). Adds a row to ACCESS_CONTROL §2.
- **Context:** Contributors asked to keep their own recordings on their phone, one at a time and all at once. Originals are admin-only, audited and need a reason (ACCESS_CONTROL §2), because they are the archive's master copies and may hold more than the speaker expects (location sounds, other voices). A facilitator also sees recordings of speakers they registered, who are other people.
- **Decision:**
  - `GET /recordings/{id}/download` redirects to a short-lived signed link that saves the **listening copy** (AAC `.m4a` first, which every phone plays, else Opus `.webm`) as a file. `GET /me/recordings.zip` puts the listening copy of every recording the user sent into one zip, stored without recompressing.
  - Only recordings **the user sent themselves** (`submitted_by`), not withdrawn, and with **no restriction flag**: an item an admin hid after a report (personal information, a third party's voice, a minor, culturally restricted content) is not offered, although its owner can still play it.
  - File names hold only the recording day and the random end of the recording ID (`lokdhara-2026-10-12-3f9a0c21.m4a`), never titles or names. Downloads are not audit-logged, like playback, since the user can already listen to the same file.
- **Alternatives:** Download the original (the contributor's own upload, but it widens an admin-only rule and needs the professor's view on governance first); zip in the browser (a new JavaScript dependency and every file fetched separately on a slow connection); several single downloads at once (browsers block them).
- **Consequences:** Saved copies leave the platform: a later withdrawal deletes the server's copies but not what is on the contributor's phone, which the withdrawal screen and facilitator guide should say. The zip is built in the API process, spilling to a temporary file above 8 MB; at pilot sizes (tens of recordings, about 20 MB per hour of AAC) this is fine.
- **Revisit when:** the professor answers whether contributors may download originals, or a contributor's recordings grow past a few hundred MB.

## ADR-027 — Admins download everything in one zip; one admin approves an export

- **Status:** Proposed (built 2026-10-23 on the project owner's request; awaiting the professor's view on governance). Changes the "Download original audio" and "Approve export" rows of ACCESS_CONTROL §2.
- **Context:** The project owner asked to be able to download all the data as an admin, unfiltered, and found the second-admin approval for exports too heavy for a pilot with one or two admins. Until now originals could not be downloaded at all (the admin endpoint in ACCESS_CONTROL §2 was never built), and a dataset release always leaves out names, withdrawn and restricted items, and items whose consent does not allow its purpose.
- **Decision:**
  - `GET /admin/archive.zip?reason=…` (admins only, reason of 10 to 500 characters) streams one zip holding every row of the data tables as JSON Lines, the speakers' identity details decrypted, and every stored original recording, oral consent recording and prompt file. Nothing is filtered by consent, restriction flags, hiding or pending withdrawals. Password and token hashes, MFA secrets, sessions, jobs and login counters are left out. `files.jsonl` lists each stored file and whether it was found.
  - The tables are read and an `archive.download` audit event with the reason and file count is committed before any byte is sent. The zip is written while it streams, never held in memory or on disk; audio is stored, the JSON is compressed.
  - The admin status page has a "Download everything" section: the link appears once a reason is written.
  - An admin may approve or reject any export request, including their own (`own_request` is gone). A researcher's request still needs one admin.
- **Alternatives:** Build the archive with a job into the exports bucket (survives a dropped connection, but more moving parts and a second copy of everything on the server); keep dataset releases as the only way out (leaves no way to get originals or names); keep two-person export approval (safer against one compromised admin account, but the pilot may have only one admin).
- **Consequences:** One admin account can now take every name, contact and recording, and approve exports alone; two-step sign-in (ADR-025) and the audit log are the remaining guards. A downloaded archive is outside the withdrawal routine: the README in the zip says to delete a withdrawing speaker's data from saved copies, and admins must do so. Data erased by a completed withdrawal is gone and cannot be in an archive. A very large archive (hundreds of GB) can take hours over one connection and does not resume.
- **Revisit when:** the professor answers the governance questions (Q-L1 to Q-L4, Q-G9), there are several admins, or the archive outgrows one download.

## ADR-028 — Public sign-up for contributors; profile and consent asked once; minors with a guardian

- **Status:** Proposed (decided by the project owner on 2026-10-23; awaiting the professor's view on governance). Supersedes the invite-only part of ADR-008 for contributors; sessions, password hashing and throttling stay as ADR-008 says.
- **Context:** The project owner wants Lokdhara to work like a normal app: anyone can make an account, sign in and out, and give their details once instead of on every upload. Invite-only accounts also had no screens yet (the invitation and reset links opened "not found"). Speaker details and consent were already kept per speaker, but a contributor could not fill in their own name, phone or village, and every recording asked for dialect and area again.
- **Decision:**
  - `POST /auth/signup` (public) makes an account with the **contributor** role only and signs it in. It takes a username, display name, password and language, like an invitation; no email or phone is needed, because many contributors use neither, and SMS codes cost money and store phone numbers (owner's choice, 2026-10-23). Staff roles still come by invitation or by an admin's grant.
  - Spam guard: at most `LKD_SIGNUP_MAX_PER_IP` (20) new accounts per client network in `LKD_SIGNUP_WINDOW_MINUTES` (60), counted in the `login_throttle` table under a keyed hash of the network; `429 signup_limited` after that. `LKD_OPEN_SIGNUP=false` closes sign-up (`404 signup_closed`).
  - After sign-up the app makes the person's own speaker profile, asks for consent, then shows **My profile**: name, phone and village (restricted identity, encrypted; ACCESS_CONTROL §2 now lets speakers read and edit their own) and, only if they agreed to share demographics, age group, gender, first language and area. Dialect needs no extra consent. New recordings start with the speaker's dialect and area filled in; they can be changed per recording.
  - **Minors take part** (owner's decision, 2026-10-23; `LKD_ALLOW_MINORS=true`). The consent screen asks whether the speaker is under 18; if so a parent or guardian agrees with them and their relationship is recorded (`guardian_involved`, `guardian_relationship`). The `minor` flag still hides an item from the catalogue when an admin sets it after a report.
  - Forgotten passwords: there is no self-service reset, since accounts have no verified email or phone. The sign-in page says to ask a coordinator; an admin finds the account on **People and accounts** (`GET /admin/users?q=`) and makes a one-time reset link. The same page makes staff invitation links.
- **Alternatives:** Phone number + SMS code (familiar, but costs per message, needs a paid provider and stores phone numbers; SIM-swap risk); email + password (easy resets, but many contributors do not use email); keep invite-only (no spam, but every contributor needs an admin first); a CAPTCHA (an outside service or a puzzle hard for elders on slow phones).
- **Consequences:** Strangers can now send recordings straight into the collection, and there is no human reviewer (ADR-021): reports and admin hiding are the only checks on content, and spam accounts are limited only per network. Accounts made at a shared connection count together, so a big field session may hit the limit; raise it in the settings. The DPDP Rules 2025 call for verifiable parental consent for children's data; the app records that a guardian agreed but cannot verify who they are, so Q-L4 stays open for the professor and institution. Losing a password always needs an admin.
- **Revisit when:** spam or abusive recordings appear, the professor or ethics committee rules on minors (Q-L4) or on open sign-up, or contributors start using email or phone numbers that could verify a reset.

## ADR-029 — Every download says what each recording is: full item details, spreadsheets, tags in the audio

- **Status:** Proposed (asked for by the project owner on 2026-10-29: "store all the recordings properly with relevant tags"; awaiting the professor's view on the demographics part).
- **Context:** Every recording was stored with its details (speaker, consent, prompt, dialect, area, setting, format, quality, texts), but the downloads lost many of them. A release's `items.jsonl` left out the recording setting, speaker count and microphone, although DATA_DICTIONARY §3 lists them as exported, and also the original's format, the quality measurements, the prompt's text, and every demographic except the age band. The FLAC files had no tags at all, the admin archive was 20 table files with no list of recordings, and contributors' own copies were named only by a date and part of an ID.
- **Decision:**
  - **Release packages (export format 1.1).** Each `items.jsonl` record adds `collection_context` (setting, speaker count, microphone; never the notes), `audio.original` (container, codec, sample rate, channels, bit depth, size, browser recording or file upload), `audio.quality` (loudness, peaks, clipping, silence), the prompt's `text`, `language`, `script` and `topic_tags`, and `area`. `speaker` adds gender, first and other languages and region.
  - **Demographics rule.** Age band, as before, whenever the speaker agreed to share demographics. Gender, languages, region and the recording's area only when the speaker agreed **and** the release is for `internal_research`; wider purposes keep only the age band until governance decides (Q-G1, Q-G5). Releases never hold minors' items (restriction flag) or names, contacts, villages, titles or notes.
  - **metadata.csv** in each package: the same items, one row each, UTF-8 with a byte order mark so spreadsheets show Devanagari and Nag Mundari; lists are joined and text starting with `= + - @` gets a leading `'` so a spreadsheet does not run it. `items.jsonl` stays the exact copy. The deletion routine erases it with `items.jsonl`.
  - **Tags inside each FLAC file** (`app.audio.flac_tags`, no FFmpeg): item ID, release, speaker code, date, content type, language, dialect, mode, collection method, prompt, transcription, translations, permitted uses and licence. No demographics or area, which stay where the release's terms travel with them. Only STREAMINFO and SEEKTABLE are kept from the stored copy; the audio frames are unchanged. Freezing reads each audio copy once to check it and to record the tagged file's checksum; the export writes the tags while it streams and checks both. Releases frozen in format 1 are rebuilt untagged, byte for byte.
  - **Admin archive:** `recordings_overview.csv`, one row per recording (and per text-only item) joining speaker code and identity, consent, prompt, collection details, format, quality, current texts and the file's name in the zip.
  - **Contributors' downloads:** names add the recording mode and content type (`lokdhara-2026-10-12-read-story-3f9a0c21.m4a`; still never the title), and the zip of all recordings adds `details.csv` (title, date, prompt, dialect, area, length, status, transcription, translations). Single-file downloads stay a redirect to the stored copy, so the `.m4a` itself is not tagged.
- **Alternatives:** Tag the FLAC copies when they are made (but titles and texts change after upload, and a release must describe the item as frozen); tag with FFmpeg at export (an extra tool run per file, and its output depends on the FFmpeg version); put demographics in the audio tags (a copied file would carry them without the licence and the release's terms); keep demographics at age band only (simplest, but researchers lose gender and dialect-area balance).
- **Consequences:** Freezing now reads every audio file twice (check D4, then tagging), so a large release takes longer to freeze. Internal research packages hold more about each speaker; combined with a small community, gender plus area plus age band can point to a person, which the professor should weigh (Q-G11). Older packages keep format 1.
- **Revisit when:** the professor answers Q-G11, Q-G1 or Q-G5, a release is published outside the project, or freezing becomes too slow.

## ADR-030 — Topics: a list admins extend, chosen per item and carried into every download

- **Status:** Proposed (asked for by the project owner on 2026-10-29: "what domain he is speaking, like agriculture, health, governance … we can give the dropdown and add more topics too"). Gives a working answer to Q-X5 for recordings; the list itself is provisional until a linguist and the community check it.
- **Context:** A recording kept its type (story, song, …) but not its subject. Only prompts had free-form topic tags, so free recordings had no subject at all, and nothing about subjects reached the downloads.
- **Decision:**
  - A `topics` table (migration `0018`) holds the offered topics: a fixed `key`, English and Hindi labels, an order, and `retired_at`. It starts with 23 topics: agriculture, forest and nature, animals and livestock, water and weather, health and medicine, food and cooking, family and relations, daily life, education, governance and village council, law, land and rights, market and money, work and crafts, festivals and rituals, beliefs, history and ancestors, folk tales, music and dance, games, places and travel, numbers and time, phones and technology, something else.
  - `GET /topics` gives the dropdown; admins add, rename, reorder and retire topics (`/admin/topics`), audited. Keys never change and topics are never deleted, so exported keys keep their meaning; a retired topic is not offered but stays on items that have it.
  - Each submission has `topics` (up to 10 keys, checked against the list). A prompted or read item starts with its prompt's tags that are on the list.
  - Topics go into `items.jsonl`, `metadata.csv`, the data card counts, the `TOPICS` tag of each FLAC file, the admin `recordings_overview.csv` and contributors' `details.csv`. A release can take only items with any of chosen topics.
- **Alternatives:** Free-text topics typed by contributors (spellings drift and cannot be counted); a list fixed in code (every new topic needs a release of the app); one topic per item (stories often touch several).
- **Consequences:** The contributor screens still need the dropdown (frontend work, later). Items recorded before this have no topics. Topic counts in a data card count an item once per topic.
- **Revisit when:** a linguist and the community review the list (Q-X5), or topics need sub-topics.


## ADR-031 — One "I accept" tick on the consent page

- **Status:** Accepted (decided by the project owner on 2026-10-29, who also answered Q-G13: one tick is enough). Changes how CONSENT_AND_DATA_GOVERNANCE §3.1 is shown, not what is stored.
- **Context:** The consent page asked six Yes/No questions and a credit question, each starting at No. The project owner found this long and unusual for contributors, who expect one page to read and one box to tick, as on most websites.
- **Decision:**
  - The page shows the consent form, then a plain list of everything the speaker agrees to: keeping and reviewing the recording, research use, public access, building computer tools, use by companies, recording age group, area and languages, and credit by a code instead of the name. Then one **"I have read the above and I accept"** tick, which starts empty. Save stays disabled until it is ticked.
  - Saving sends every permission as `true` and `attribution_preference: pseudonymous`. The server, the database and the consent record are unchanged; old consent records with mixed answers keep working.
  - The facilitator's "how was consent given" choices stay. The under-18 question and the parent or guardian field were removed later the same day (ADR-032).
  - Releases still need their own approval: public and AI-training releases are only made when governance approves them (§4), so a tick alone does not publish anything.
- **Alternatives:** Keep separate questions (most protective, but long); one tick for the required part with the other uses as switches that start off (short and still specific per purpose; this was recommended and the owner chose the single tick instead).
- **Consequences:** Every new speaker agrees to all uses, including public access and use by companies; a speaker who wants only part of them cannot say so in the app and has to withdraw instead. India's DPDP Act asks for consent that is specific to each purpose, and an ethics committee may ask for separate choices, so this is open as Q-G13. Speakers can no longer choose to be credited by name or not at all (Q-G2).
- **Revisit when:** the professor or ethics committee answers Q-G13, or speakers ask to share only part of their data.

## ADR-032 — Owner's answers of 2026-10-29: no ethics approval, minors without a guardian, nothing restricted, consent proof kept one month, facilitators record others

- **Status:** Accepted (decided by the project owner on 2026-10-29). Answers Q-L3, Q-L4, Q-G3, Q-G8, Q-G12 and Q-G13. Replaces the guardian part of ADR-028 and the "only the signed-in user's own voice" choice made earlier the same day.
- **Context:** These questions were waiting for the professor and an ethics committee. The project owner answered them so the app can be finished for the pilot.
- **Decision:**
  - **Ethics approval (Q-L3):** none is needed from anyone.
  - **Minors (Q-L4):** anyone may contribute, minors included, and no parent or guardian is asked for. The consent page no longer asks whether the speaker is under 18. The server still accepts `guardian_involved` and `guardian_relationship`, so old records stay valid and the question can come back. `LKD_ALLOW_MINORS` stays `true`.
  - **Restricted content (Q-G3):** nothing is culturally restricted for now. The `culturally_restricted` flag and scope stay in the code, unused unless an admin sets the flag after a report.
  - **Proof of consent after a withdrawal (Q-G8):** kept for one month. `LKD_WITHDRAWAL_CONSENT_EVIDENCE_DAYS` (default 30) replaces `LKD_WITHDRAWAL_KEEP_CONSENT_EVIDENCE`. A daily job, `withdrawal.expire_consent_evidence` (migration `0019`), deletes every stored version of the oral consent recordings of speakers whose full withdrawal was erased that long ago, and notes it in the request's `actions_taken` and the audit log. The request and the consent records stay, without notes or identity, as the record that the withdrawal was honoured. With 0 days the recording is deleted together with everything else.
  - **Recording other people (Q-G12):** facilitators and admins see "Whose voice or text is this?" again when they start a new recording: their own, someone they registered, or a new person, whose consent they then record (in the app, orally or on paper). Contributors still go straight to their own voice.
  - **One tick (Q-G13):** enough; ADR-031 is accepted.
- **Alternatives:** Wait for the professor and an ethics committee (slower, and the owner says none is needed); keep the guardian field as optional (less friction than before, but the owner wants no guardian step); keep proof of consent for years (stronger proof, but holds a withdrawn person's voice longer).
- **Consequences:** India's DPDP Rules 2025 call for verifiable parental consent for children's data, and research use without ethics approval can limit where results are published; the owner carries both risks. After one month there is no recording left to show that an oral consent was given; the consent record (method, form version, date) remains.
- **Revisit when:** the institution, a journal or a funder asks for ethics approval, a guardian complains, or the community names restricted content.
