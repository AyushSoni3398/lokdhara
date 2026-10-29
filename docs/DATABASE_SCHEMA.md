# Database Schema

Status: **Implemented** by migrations `0001`–`0014` in `backend/migrations/`. Where the migrations refine this document, ADR-020 records why. Field meanings are in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

Conventions:

- PostgreSQL 18. Primary keys `id uuid DEFAULT uuidv7()`.
- All timestamps `timestamptz`, UTC.
- Enumerations are `text` columns with `CHECK` constraints (easier to migrate than PostgreSQL `ENUM` types).
- **Append-only** tables have a trigger that rejects `UPDATE` and `DELETE` except by the dedicated withdrawal/deletion routine (which runs under a separate database role). Three trigger functions (ADR-020):
  - `lkd_reject_change()`: the whole row is immutable.
  - `lkd_guard_columns(mutable…)`: immutable except the listed columns (e.g. consent `status`).
  - `lkd_freeze_columns(frozen…)`: the listed identity columns never change; the rest may.
- Column markers below: 🔒 restricted (admin-only or encrypted), 🧊 immutable after insert, 🔎 indexed for search/filter, 🗂 JSONB extensible.

## 1. Identity

### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| username | text UNIQUE NOT NULL | Login name; not necessarily real name. Lowercase `^[a-z0-9][a-z0-9._-]{2,39}$` (input is lowercased). |
| display_name | text NOT NULL | Shown in UI. |
| email 🔒 | text NULL UNIQUE | Optional (many contributors may have none). |
| phone 🔒 | text NULL | Optional; only if needed for contact. |
| password_hash 🔒 | text NOT NULL | Argon2id. |
| status | text CHECK IN ('invited','active','suspended','deactivated') | |
| preferred_locale | text DEFAULT 'hi' | `hi`, `en`, later `unr`. |
| created_at, updated_at | timestamptz | |
| last_login_at | timestamptz NULL | |

### `user_roles`
| Column | Type | Notes |
|--------|------|-------|
| user_id | uuid FK users | |
| role | text CHECK IN ('contributor','facilitator','reviewer','researcher','admin') | |
| scope | text NULL | Optional narrowing/extension, e.g. `culturally_restricted` for designated community reviewers. |
| granted_by | uuid FK users | |
| granted_at | timestamptz | |
| revoked_at | timestamptz NULL | Row kept for history. |
| revoked_by | uuid FK users NULL | |
| PK | (user_id, role, granted_at) | Active grants: `revoked_at IS NULL`. |

Partial unique index: one active grant per (user, role, scope).

### `invitations`, `password_resets`, `sessions`, `login_throttle`
`invitations(id, token_hash 🔒, role, created_by, created_at, expires_at, accepted_by NULL, accepted_at NULL, revoked_at NULL)`
`password_resets(id, user_id, token_hash 🔒, created_by, created_at, expires_at, used_at NULL)`
`sessions(id, user_id, token_hash 🔒, created_at, last_seen_at, expires_at, revoked_at NULL, user_agent_hash, ip_hash)` — raw tokens are never stored, only SHA-256 hashes.
`login_throttle(key_hash PK, failures, window_started_at, locked_until NULL)` — keys are HMACs of the username or client IP hash, never the raw values.

`user_mfa(user_id PK/FK, secret_enc 🔒 bytea, key_version, created_at, confirmed_at NULL, last_used_step bigint)` and `mfa_recovery_codes(id, user_id FK, code_hash 🔒 UNIQUE, used_at NULL)` — migration `0017`. The TOTP secret is encrypted by the app (AES-256-GCM, key derived from the identity key, bound to the user); two-step sign-in counts once `confirmed_at` is set; `last_used_step` stops a code being used twice. Recovery codes are stored as keyed hashes and marked when used. `app_readonly` cannot read either table.

## 2. Speakers and consent

Implemented by migration `0004`.

### `speakers`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| speaker_code 🔎 | text UNIQUE NOT NULL | Pseudonymous, random (e.g., `SPK-7Q3M9`). |
| linked_user_id | uuid FK users NULL | Set when the speaker is also an account holder. |
| created_by | uuid FK users | Facilitator or self. |
| age_band 🔎 | text NULL CHECK IN ('18-29','30-44','45-59','60+','under_18','undisclosed') | Only if consented. |
| gender_self_described | text NULL | Free text, optional, only if consented. |
| first_language | text NULL | BCP 47 tag, e.g., `unr`. |
| other_languages | text[] NULL | |
| dialect_label 🔎 | text NULL | From controlled list or free text (Q-X1). |
| region_coarse 🔎 | text NULL | District/block level at most; never village + name together. |
| demographics_consented | boolean NOT NULL DEFAULT false | If false, demographic columns must be NULL (CHECK). |
| status | text CHECK IN ('active','withdrawn') | |
| created_at | timestamptz | |

Frozen: `id`, `speaker_code` (format `SPK-` + 5–12 of `0-9A-Z`), `created_by`.

### `speaker_identities` 🔒 (separate table; admin + creating facilitator only)
`speaker_id PK/FK, full_name_enc, contact_enc, village_enc, notes_enc, key_version, created_at, updated_at` — application-level encrypted `bytea` columns (key from environment/secret store; `key_version` allows rotation). Deleted on withdrawal. The `app_readonly` role cannot read this table; the backup role `app_backup` can, so that backups are complete.

### `consent_forms` 🧊
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| form_code | text | e.g., `LKD-CONSENT` |
| version | text | e.g., `1.0` |
| language | text | `hi`, `en`, `unr-Deva` … |
| text_sha256 | text | Hash of the exact form text shown. |
| body_markdown | text | The form text. |
| ethics_reference | text NULL | IEC approval reference once available (Q-L3). |
| is_test_form | boolean NOT NULL DEFAULT true | Test forms are for development only; real forms need Q-L3. |
| effective_from, retired_at | timestamptz | |
| UNIQUE | (form_code, version, language) | |

CHECK: `text_sha256` equals the SHA-256 of `body_markdown`. Only `retired_at` may change.

### `consent_records` 🧊 (append-only; changes create a new row)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| speaker_id 🔎 | uuid FK speakers | |
| consent_form_id | uuid FK consent_forms | |
| supersedes_id | uuid FK consent_records NULL | Previous record for this speaker. |
| status 🔎 | text CHECK IN ('active','superseded','withdrawn') | Status changes are the only allowed update (via routine). |
| method | text CHECK IN ('in_app','oral_recorded','paper_reference') | |
| obtained_by | uuid FK users | |
| obtained_at | timestamptz | |
| guardian_involved | boolean NOT NULL | |
| guardian_relationship | text NULL | |
| evidence_object_key 🔒 | text NULL | Key in `consent-evidence` bucket. |
| paper_reference 🔒 | text NULL | ID of paper form held offline. |
| allow_store_and_review | boolean NOT NULL | Must be true to participate. |
| allow_research | boolean NOT NULL DEFAULT false | |
| allow_public_access | boolean NOT NULL DEFAULT false | |
| allow_ai_training | boolean NOT NULL DEFAULT false | |
| allow_commercial_use | boolean NOT NULL DEFAULT false | |
| attribution_preference | text CHECK IN ('pseudonymous','name','none') DEFAULT 'pseudonymous' | |
| demographics_consented | boolean NOT NULL DEFAULT false | Answer to the demographics question (migration `0008`); `speakers.demographics_consented` mirrors the active record, and a No erases stored demographics. |
| applies_to_past_contributions | boolean NOT NULL DEFAULT false | If true, a *wider* new record also widens earlier submissions; narrowing always applies to past submissions. |
| notes | text NULL | |

Partial unique index: one `active` record per speaker. CHECKs: `allow_store_and_review` is true; `oral_recorded` needs `evidence_object_key`; `paper_reference` needs `paper_reference`; `guardian_relationship` only with `guardian_involved`. Only `status` may change.

### `withdrawal_requests`
`id, speaker_id, submission_id NULL, received_via ('in_app','facilitator','phone','in_person','email'), received_at, recorded_by, requested_scope ('full','narrow','specific_items'), note NULL (at most 1,000 characters, admins only), verified_by NULL, verified_at NULL, status ('received','verified','in_progress','completed','rejected'), actions_taken jsonb 🗂, erased_at NULL, completed_at NULL`

Migration `0014` makes `speaker_id` required and adds `note` and `erased_at`. A request for one item (`specific_items`) names its submission; the other scopes do not. A verified request has `verified_by` and `verified_at`; a closed one (completed or rejected) has `completed_at`; `erased_at` is set by the deletion routine. One waiting (`received`) request per speaker, item and scope (`uq_withdrawal_requests_waiting`). What was asked, by whom and when (`id, speaker_id, submission_id, received_via, received_at, recorded_by, requested_scope, note`) cannot change (`lkd_freeze_columns`). `in_progress` is allowed but not used yet.

## 3. Submissions, audio, text

Implemented by migrations `0005` (prompts, submissions, related items) and `0006` (recordings, renditions, text).

### `submissions`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| client_submission_id | uuid UNIQUE | Generated on device; idempotency for retries. |
| submitted_by 🔎 | uuid FK users | |
| speaker_id 🔎 | uuid FK speakers | |
| consent_record_id | uuid FK consent_records NULL | Required before leaving `draft` (CHECK on status). |
| kind 🔎 | text CHECK IN ('audio','text','audio_text') | |
| content_type 🔎 | text CHECK IN ('story','conversation','vocabulary','song','sentence_list','other') | |
| title | text NULL | Optional, any script. |
| language_tag 🔎 | text NOT NULL DEFAULT 'unr' | BCP 47. |
| dialect_label 🔎 | text NULL | As reported for this submission. |
| region_coarse 🔎 | text NULL | |
| recorded_on | date NULL | |
| recording_mode 🔎 | text CHECK IN ('free','prompted','read') NULL | NULL only for text-only submissions. |
| prompt_id | uuid FK prompts NULL | Required when `recording_mode` is `prompted` or `read`. |
| collection_method 🔎 | text CHECK IN ('self_recorded','facilitator_field','facilitator_remote','imported_archive') | |
| collection_context 🗂 | jsonb DEFAULT '{}' | Setting, number of speakers, equipment. |
| status 🔎 | text (see state machine) | Migration `0010` adds `accepted`, set when every automatic check succeeds (ADR-021). The review statuses stay allowed but unused. |
| topics 🔎 | text[] NOT NULL DEFAULT '{}' | Keys from `topics` (checked by the app, at most 10; GIN index). Migration `0018`. Prompted and read items start with their prompt's matching tags. |
| restriction_flags 🔎 | text[] DEFAULT '{}' | `sensitive`, `third_party_voice`, `contains_pii`, `culturally_restricted`, `minor`. An admin sets one to hide a reported item. |
| created_at, submitted_at, updated_at | timestamptz | |

CHECKs: consent before leaving `draft`; `recording_mode` is NULL exactly for `text` submissions; `prompt_id` is set exactly for `prompted`/`read`. Frozen: `id`, `client_submission_id`, `submitted_by`, `created_at`.

### `recordings`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK submissions | |
| original_object_key 🧊 | text NOT NULL | `{yyyy}/{mm}/{recording_id}/original.{ext}`; the same key in the quarantine bucket until promotion, then in originals. |
| original_filename_ext | text | Extension only; full client filename not stored (may contain names). |
| sha256_original 🧊🔎 | char(64) NOT NULL | |
| sha256_pcm 🔎 | char(64) NULL | Hash of decoded mono PCM; catches re-encoded duplicates. |
| size_bytes 🧊 | bigint | |
| detected_container, detected_codec | text | From ffprobe. |
| sample_rate_hz, channels, bit_depth | int | bit_depth NULL for lossy codecs. |
| duration_ms 🔎 | int | |
| is_lossy_source | boolean | |
| upload_status | text CHECK IN ('quarantined','validated','rejected_invalid','promoted','expired','erased') | `expired` (migration `0011`): a draft's quarantine copy deleted after 30 days unsent (Q-T7). `erased` (migration `0014`): the speaker withdrew it and the deletion routine removed its files; the row stays so release manifests stay readable. |
| quarantined_at | timestamptz | When the bytes were last stored in quarantine; the 30 days count from here. |
| validation_errors 🗂 | jsonb NULL | |
| quality_metrics 🗂 | jsonb NULL | peak_dbfs, rms_dbfs, integrated_lufs, clipping_ratio, silence_ratio, speech_ratio_vad. |
| quality_flags 🔎 | text[] DEFAULT '{}' | `silent`, `too_short`, `clipping`, `very_quiet`, `possible_duplicate`. |
| recorded_device_hint | text NULL | Browser-recorded vs. file upload. |
| upload_key 🧊 | uuid NULL | The upload's `Idempotency-Key` (migration `0009`); `UNIQUE (submission_id, upload_key)`, so a retried upload returns the stored recording. |
| created_at | timestamptz | |

Index: `UNIQUE (sha256_original)` is **not** enforced (duplicates must be stored and flagged, not rejected silently); use a normal index. Frozen: `id`, `submission_id`, `original_object_key`, `sha256_original`, `size_bytes`, `upload_key`, `created_at`; validation results fill in later. `recorded_device_hint` is `browser_recorder` or `file_upload`.

### `renditions` 🧊
`id, recording_id FK, kind ('playback_opus','playback_aac','analysis_flac_16k_mono','waveform_peaks'), object_key, sha256, size_bytes, params jsonb 🗂, params_sha256, tool_versions jsonb 🗂, processing_run_id FK, created_at` — UNIQUE (recording_id, kind, params_sha256). `playback_aac` serves browsers without Opus support (iPhone).

### `text_layers`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK submissions | |
| layer_type 🔎 | text CHECK IN ('standalone','transcription','translation') | |
| recording_id | uuid FK recordings NULL | Required when `transcription`. |
| source_layer_id | uuid FK text_layers NULL | Required when `translation`. |
| entry_type 🔎 | text CHECK IN ('word','phrase','sentence','paragraph','long_text') NULL | For standalone text. |
| language_tag 🔎 | text NOT NULL | `unr`, `hi`, `en`. |
| script_code 🔎 | text NOT NULL | ISO 15924: `Deva`, `Latn`, `Nagm`, `Beng`, `Orya`, `Zyyy` (mixed/unknown). |
| current_revision_id | uuid FK text_revisions NULL | Pointer, updated in the same transaction as a new revision. |
| created_at | timestamptz | |

CHECK constraints enforce the `recording_id`/`source_layer_id` rules per `layer_type`. Only `current_revision_id` changes after insert.

### `text_revisions` 🧊 (append-only)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| layer_id 🔎 | uuid FK text_layers | |
| revision_number | int | UNIQUE (layer_id, revision_number). |
| based_on_revision_id | uuid FK text_revisions NULL | |
| source_revision_id | uuid FK text_revisions NULL | Translations only: the source-layer revision that was translated (detects stale translations). |
| content_original | text NOT NULL | Verbatim (ADR-010). |
| content_nfc 🔎 | text NOT NULL | NFC form; used for search and dedupe. |
| content_normalized | text NULL | Per policy version; NULL until Q-X2. |
| normalization_policy_version | text NULL | |
| detected_scripts | text[] | Scripts actually present. |
| uncertainty_markup | boolean | True if transcriber conventions for uncertainty are used. |
| origin 🔎 | text CHECK IN ('human_contributor','human_reviewer','machine','imported','prompt_text') | `prompt_text` = reference text from a read-speech prompt; unverified until a reviewer confirms the reading matches. | |
| author_user_id | uuid FK users NULL | NULL only for `machine`. |
| tool_name, tool_version, model_id | text NULL | Required when `machine`. |
| confidence | numeric NULL | Only when `machine` and meaningful. |
| verification_status 🔎 | text CHECK IN ('unverified','verified','disputed') | Changed only via review events (routine). |
| change_note | text NULL | |
| created_at | timestamptz | |

Search indexes: GIN `to_tsvector('simple', content_nfc)`, GIN `content_nfc gin_trgm_ops` (`pg_trgm`). Provenance CHECKs: human origins need `author_user_id`; `machine` needs `tool_name` and `tool_version`; `confidence` only for `machine`; `content_normalized` and its policy version are set together. Only `verification_status` may change.

### `text_segments` (reserved, post-MVP)
`id, revision_id FK, start_ms, end_ms, speaker_label, text_original, text_nfc` — for time alignment.

### `prompts` 🧊 (one row per prompt version)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| prompt_key 🔎 | text | Stable key across versions, e.g. `img-farming-012`. |
| version | int | UNIQUE (prompt_key, version). |
| prompt_type 🔎 | text CHECK IN ('image','situation','read_sentence') | |
| text | text NULL | Instruction/situation text, or the sentence to read. |
| text_language_tag | text NULL | `hi`, `unr`, … |
| script_code | text NULL | Required for `read_sentence`. |
| image_object_key | text NULL | Required for `image`; stored in `derived/prompts/`. |
| prompt_audio_object_key | text NULL | Optional spoken version for non-literate speakers. |
| source_and_licence | text NOT NULL | Who made it and under what licence. |
| topic_tags 🔎 | text[] | Controlled list (Q-X5). |
| status 🔎 | text CHECK IN ('draft','approved','retired') | Only `status` and `approved_by` change after insert; approved or retired prompts need `approved_by` (for a draft retired without approval, the admin who retired it). At most one approved version per `prompt_key`: approving a new version retires the old one. |
| approved_by | uuid FK users NULL | |
| created_by, created_at | | |

### `topics` (migration `0018`, ADR-030)
| Column | Type | Notes |
|--------|------|-------|
| key | text PK CHECK `^[a-z][a-z0-9_]{1,39}$` | Never changes, so exported topic keys keep their meaning. |
| label_en, label_hi | text NOT NULL | Shown in the topic dropdown; 1 to 80 characters. |
| sort_order | int DEFAULT 1000 | Display order. |
| retired_at | timestamptz NULL | Retired topics are not offered any more but stay on items that have them. |
| created_by | uuid FK users NULL | NULL for the 23 topics the migration adds (provisional list, Q-X5). |
| created_at | timestamptz | |

Admins add, rename, reorder and retire topics; nobody deletes one.

### `related_items`
`id, submission_a, submission_b, relation ('same_story_retake','possible_duplicate','continuation'), created_by, created_at`.

## 4. Review

Implemented by migration `0007`.

### `review_events` 🧊
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK | |
| text_revision_id | uuid FK NULL | When the decision concerns one revision. |
| reviewer_id 🔎 | uuid FK users | Reviewer ≠ submitted_by, checked in the service and by a trigger (comments excepted). |
| action | text CHECK IN ('open','approve','reject','request_changes','verify_revision','dispute_revision','add_restriction','remove_restriction','reopen','comment') | |
| reason_code | text NULL | Controlled list (e.g., `wrong_language`, `inaudible`, `off_topic`, `abuse`, `duplicate`, `no_consent`). |
| restriction | text NULL | For add/remove restriction. |
| note | text NULL | Internal; never exported. |
| created_at | timestamptz | |

There is no reviewer (ADR-021): admins write `add_restriction` and `remove_restriction` events when they hide or show an item after a report, and `restriction_flags` is updated in the same transaction.

### `reports`
Implemented by migration `0012`. Never deleted; only the decision columns are written, once.

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK | |
| reported_by | uuid FK users | One open report per person and item (partial unique index). |
| reason | text CHECK IN ('personal_information','third_party_voice','culturally_restricted','wrong_content') | |
| note | text NULL ≤ 1000 | Seen by admins only; not in the audit log. |
| created_at | timestamptz | |
| decision | text NULL CHECK IN ('hidden','dismissed') | Set together with `decided_by` and `decided_at`. |
| decided_by | uuid FK users NULL | |
| decided_at | timestamptz NULL | |
| decision_note | text NULL ≤ 2000 | The admin's reason. |

## 5. Processing

Implemented by migration `0003` (ADR-019).

### `jobs` (mutable work queue)
`id, job_type, payload jsonb (IDs only), target_type, target_id, status ('queued','running','succeeded','failed'), attempts, max_attempts, run_after, dedupe_key NULL, locked_by NULL, lock_expires_at NULL, last_error_code NULL, created_at, finished_at NULL` — partial unique index on `dedupe_key` while queued or running. Finished rows may be purged; history lives in `processing_runs`.

### `processing_runs` 🧊 (one row per finished attempt)
`id, job_id (no FK, so jobs can be purged), job_type ('system.ping','audio.validate','audio.analyze','audio.renditions','audio.dedupe','text.derive','dataset.export','cleanup.quarantine','cleanup.expire_drafts','cleanup.expire_exports','withdrawal.erase','ops.digest' (migration `0016`)), target_type, target_id, attempt, status ('succeeded','failed'), started_at, finished_at, worker_id, tool_versions jsonb 🗂, input_sha256, output_summary jsonb 🗂, error_code, error_detail (sanitised: for unexpected errors only the exception type is stored)`. A running attempt is visible in `jobs`, so this table never needs updating.

### `backup_runs` 🧊 (one row per finished backup)
`id, kind ('database','withdrawal_log'), started_at, finished_at, succeeded, size_bytes NULL, file_name NULL (≤ 200), detail NULL (≤ 500, an error summary with no content)` — migration `0015`. A successful run names its file and size. Written once by the backup job, which logs in as a member of the NOLOGIN role `app_backup`: it may read every table (speaker identities included, encrypted, so a restore is complete) and insert only here. The admin status page reads the latest row of each kind ([OBSERVABILITY_AND_BACKUPS.md](OBSERVABILITY_AND_BACKUPS.md)).

## 6. Datasets

### `dataset_releases`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| slug | text | e.g., `mundari-speech-pilot` |
| version | text NULL | SemVer, e.g., `0.1.0`, set on freeze (NULL while a draft). UNIQUE (slug, version). |
| purpose 🔎 | text CHECK IN ('internal_research','external_research','public','ai_training') | Determines which consent flag is required. |
| selection_criteria 🗂 | jsonb | The filter used. |
| status | text CHECK IN ('draft','frozen','retracted') | |
| licence | text NULL | Required before `frozen` for external/public purposes (Q-L5). At most 200 characters. |
| data_card_markdown | text | At most 50 000 characters; included in the package README. |
| manifest_object_key, manifest_sha256 | text NULL | Set on freeze. The package's text files are kept next to the manifest in the `exports` bucket for as long as the release. |
| code_version | text NULL | Git commit of the code that froze it (`LKD_GIT_COMMIT`). |
| created_by, approved_by | uuid FK users | approved_by is the admin who froze it. |
| created_at, updated_at, frozen_at, retracted_at | timestamptz | |
| retraction_note | text NULL | |
| replaces_id | uuid FK dataset_releases NULL | Migration `0014`: set on a PATCH draft started from a release that had items withdrawn; the draft can only take items of that release. |

Migration `0013`. `ck_dataset_releases_frozen_complete` ties the status to its fields (a draft has no version, manifest or approver; a retracted release has its date and note). The `lkd_release_guard` trigger lets a draft change freely, a frozen release change only to `retracted`, and nothing change after that; only drafts can be deleted.

### `dataset_release_items` 🧊
`release_id FK, submission_id FK, recording_id FK NULL, rendition_id FK NULL (the analysis FLAC), text_revision_ids uuid[], consent_record_id FK, consent_snapshot jsonb (the four uses as computed at freezing), item_sha256s jsonb, withdrawn_after_release_at timestamptz NULL` — PK (release_id, submission_id). `withdrawn_after_release_at` is the only field set after insert (via withdrawal routine).

### `export_requests`
`id, release_id FK, requested_by FK, purpose_statement (1–2000 characters), status ('requested','approved','building','ready','expired','rejected','failed'), decided_by FK NULL, decided_at NULL, decision_note NULL, object_key NULL, sha256 NULL, size_bytes NULL, created_at, ready_at NULL, expires_at NULL, downloaded_at timestamptz[]`. A decided request has `decided_by` and `decided_at`; a ready one has its object, checksum and expiry. `id, release_id, requested_by, purpose_statement, created_at` cannot change (`lkd_freeze_columns`).

## 7. Audit

### `audit_events` 🧊

Append-only via the shared `lkd_reject_change()` trigger: UPDATE/DELETE fail unless the session is a member of `app_erasure` **and** has set `lkd.erasure = 'on'` for its transaction. Migration `0001` creates the NOLOGIN roles `app_rw`, `app_erasure`, `app_readonly` and their default privileges (no role gets TRUNCATE).

`id, occurred_at, actor_user_id NULL, actor_type ('user','system','worker'), action, target_type, target_id, request_id, ip_hash, details jsonb 🗂 (no content, no names)`.

Indexed on (target_type, target_id), (actor_user_id, occurred_at), (action, occurred_at).

## 8. Field classification summary

| Category | Examples | Rule |
|----------|----------|------|
| Immutable | originals, renditions, text_revisions, consent_records (except status), review_events, reports (except the decision), audit_events, release items | Triggers block UPDATE/DELETE; only the withdrawal routine (separate DB role) may delete for erasure. |
| Versioned | text layers (via revisions), consent (via superseding records), datasets (via SemVer releases), consent forms | New row per change. |
| Restricted | speaker_identities, contact fields, password/token hashes, consent evidence keys, IP hashes | Admin-only API paths; never exported; encrypted where noted. |
| Searchable/indexed | status, kind, content_type, dialect_label, region_coarse, language_tag, script_code, quality_flags, restriction_flags, duration, content_nfc (FTS + trigram), speaker_code | B-tree / GIN as appropriate. |
| Never exported | speaker identities, user emails/phones, review notes, IP hashes, consent evidence | Enforced by export builder allow-list. |

## 9. How the schema supports the documented workflows

| Workflow ([USER_FLOWS.md](USER_FLOWS.md)) | Tables |
|------|--------|
| F1 contribution | submissions, prompts, recordings, text_layers, text_revisions, processing_runs |
| F2 consent | consent_forms, consent_records, speaker_identities |
| F3 withdrawal | withdrawal_requests, consent_records, submissions, dataset_release_items, audit_events |
| F4 reports and hiding | reports, review_events, submissions.restriction_flags |
| F5 researcher search | submissions + text_revisions indexes, effective-access view |
| F6 release/export | dataset_releases, dataset_release_items, export_requests |
| F7 failed processing | processing_runs, queue tables |

Effective access is one service module, `app.modules.consents.access`, with the same rule as Python (`in_catalogue`) and as a SQL condition (`catalogue_filter`); a shared table of cases checks that they agree (ADR-012).
