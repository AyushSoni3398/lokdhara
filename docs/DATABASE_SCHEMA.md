# Database Schema (proposed)

Status: **Partly implemented.** Identity (§1) and the audit log (§7) are implemented by migrations `0001`–`0002` in `backend/migrations/`; the rest is the logical schema that later Milestone 2 migrations implement. Field meanings are in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

Conventions:

- PostgreSQL 18. Primary keys `id uuid DEFAULT uuidv7()`.
- All timestamps `timestamptz`, UTC.
- Enumerations are `text` columns with `CHECK` constraints (easier to migrate than PostgreSQL `ENUM` types).
- **Append-only** tables have a trigger that rejects `UPDATE` and `DELETE` except by the dedicated withdrawal/deletion routine (which runs under a separate database role).
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

## 2. Speakers and consent

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

### `speaker_identities` 🔒 (separate table; admin + creating facilitator only)
`speaker_id PK/FK, full_name_enc, contact_enc, village_enc, notes_enc, created_at` — application-level encrypted columns (key from environment/secret store). Deleted on withdrawal.

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
| effective_from, retired_at | timestamptz | |
| UNIQUE | (form_code, version, language) | |

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
| applies_to_past_contributions | boolean NOT NULL DEFAULT false | If true, a *wider* new record also widens earlier submissions; narrowing always applies to past submissions. |
| notes | text NULL | |

Partial unique index: one `active` record per speaker.

### `withdrawal_requests`
`id, speaker_id NULL, submission_id NULL, received_via ('in_app','facilitator','phone','in_person','email'), received_at, requested_scope ('full','narrow','specific_items'), verified_by NULL, verified_at NULL, status ('received','verified','in_progress','completed','rejected'), actions_taken jsonb 🗂, completed_at NULL`

## 3. Submissions, audio, text

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
| status 🔎 | text (see state machine) | |
| restriction_flags 🔎 | text[] DEFAULT '{}' | `sensitive`, `third_party_voice`, `contains_pii`, `culturally_restricted`, `minor`. |
| created_at, submitted_at, updated_at | timestamptz | |

### `recordings`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK submissions | |
| original_object_key 🧊 | text NOT NULL | `originals/…` |
| original_filename_ext | text | Extension only; full client filename not stored (may contain names). |
| sha256_original 🧊🔎 | char(64) NOT NULL | |
| sha256_pcm 🔎 | char(64) NULL | Hash of decoded mono PCM; catches re-encoded duplicates. |
| size_bytes 🧊 | bigint | |
| detected_container, detected_codec | text | From ffprobe. |
| sample_rate_hz, channels, bit_depth | int | bit_depth NULL for lossy codecs. |
| duration_ms 🔎 | int | |
| is_lossy_source | boolean | |
| upload_status | text CHECK IN ('quarantined','validated','rejected_invalid','promoted') | |
| validation_errors 🗂 | jsonb NULL | |
| quality_metrics 🗂 | jsonb NULL | peak_dbfs, rms_dbfs, integrated_lufs, clipping_ratio, silence_ratio, speech_ratio_vad. |
| quality_flags 🔎 | text[] DEFAULT '{}' | `silent`, `too_short`, `clipping`, `very_quiet`, `possible_duplicate`. |
| recorded_device_hint | text NULL | Browser-recorded vs. file upload. |
| created_at | timestamptz | |

Index: `UNIQUE (sha256_original)` is **not** enforced (duplicates must be stored and flagged, not rejected silently); use a normal index.

### `renditions` 🧊
`id, recording_id FK, kind ('playback_opus','analysis_flac_16k_mono','waveform_peaks'), object_key, sha256, size_bytes, params jsonb 🗂, tool_versions jsonb 🗂, processing_run_id FK, created_at` — UNIQUE (recording_id, kind, params_hash).

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

CHECK constraints enforce the `recording_id`/`source_layer_id` rules per `layer_type`.

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

Search indexes: GIN `to_tsvector('simple', content_nfc)`, GIN `content_nfc gin_trgm_ops`.

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
| status 🔎 | text CHECK IN ('draft','approved','retired') | Status is the only field changed after insert. |
| approved_by | uuid FK users NULL | |
| created_by, created_at | | |

### `related_items`
`id, submission_a, submission_b, relation ('same_story_retake','possible_duplicate','continuation'), created_by, created_at`.

## 4. Review

### `review_events` 🧊
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| submission_id 🔎 | uuid FK | |
| text_revision_id | uuid FK NULL | When the decision concerns one revision. |
| reviewer_id 🔎 | uuid FK users | CHECK in service: reviewer ≠ submitted_by. |
| action | text CHECK IN ('open','approve','reject','request_changes','verify_revision','dispute_revision','add_restriction','remove_restriction','reopen','comment') | |
| reason_code | text NULL | Controlled list (e.g., `wrong_language`, `inaudible`, `off_topic`, `abuse`, `duplicate`, `no_consent`). |
| restriction | text NULL | For add/remove restriction. |
| note | text NULL | Internal; never exported. |
| created_at | timestamptz | |

`submissions.status` and `restriction_flags` are derived from review events and updated in the same transaction.

## 5. Processing

### `processing_runs` 🧊
`id, job_type ('audio.validate','audio.analyze','audio.renditions','audio.dedupe','text.derive','dataset.export','cleanup.quarantine'), target_type, target_id, attempt, status ('running','succeeded','failed'), started_at, finished_at, worker_id, tool_versions jsonb 🗂, input_sha256, output_summary jsonb 🗂, error_code, error_detail (sanitised)`

Queue tables are owned by the job library (Procrastinate) or a minimal `jobs` table (ADR-007).

## 6. Datasets

### `dataset_releases`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| slug | text | e.g., `mundari-speech-pilot` |
| version | text | SemVer, e.g., `0.1.0`. UNIQUE (slug, version). |
| purpose 🔎 | text CHECK IN ('internal_research','external_research','public','ai_training') | Determines which consent flag is required. |
| selection_criteria 🗂 | jsonb | The filter used. |
| status | text CHECK IN ('draft','frozen','retracted') | |
| licence | text NULL | Required before `frozen` for external/public purposes (Q-L5). |
| data_card_markdown | text | |
| manifest_object_key, manifest_sha256 | text NULL | Set on freeze. |
| created_by, approved_by | uuid FK users | approved_by must be admin. |
| frozen_at, retracted_at | timestamptz NULL | |
| retraction_note | text NULL | |

### `dataset_release_items` 🧊
`release_id FK, submission_id FK, recording_id FK NULL, rendition_id FK NULL, text_revision_ids uuid[], consent_record_id FK, consent_snapshot jsonb, item_sha256s jsonb, withdrawn_after_release_at timestamptz NULL` — PK (release_id, submission_id). `withdrawn_after_release_at` is the only field set after insert (via withdrawal routine).

### `export_requests`
`id, release_id FK, requested_by, purpose_statement, approved_by NULL, status ('requested','approved','building','ready','expired','rejected','failed'), object_key NULL, sha256 NULL, expires_at NULL, downloaded_at[]`.

## 7. Audit

### `audit_events` 🧊

Append-only via the shared `lkd_reject_change()` trigger: UPDATE/DELETE fail unless the session is a member of `app_erasure` **and** has set `lkd.erasure = 'on'` for its transaction. Migration `0001` creates the NOLOGIN roles `app_rw`, `app_erasure`, `app_readonly` and their default privileges (no role gets TRUNCATE).

`id, occurred_at, actor_user_id NULL, actor_type ('user','system','worker'), action, target_type, target_id, request_id, ip_hash, details jsonb 🗂 (no content, no names)`.

Indexed on (target_type, target_id), (actor_user_id, occurred_at), (action, occurred_at).

## 8. Field classification summary

| Category | Examples | Rule |
|----------|----------|------|
| Immutable | originals, renditions, text_revisions, consent_records (except status), review_events, audit_events, release items | Triggers block UPDATE/DELETE; only the withdrawal routine (separate DB role) may delete for erasure. |
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
| F4 review | review_events, text_revisions, submissions.status/restriction_flags |
| F5 researcher search | submissions + text_revisions indexes, effective-access view |
| F6 release/export | dataset_releases, dataset_release_items, export_requests |
| F7 failed processing | processing_runs, queue tables |

An `effective_access` SQL view (or service function) joins submissions → active consent → restriction flags → status and is the single source of truth for visibility (ADR-012).
