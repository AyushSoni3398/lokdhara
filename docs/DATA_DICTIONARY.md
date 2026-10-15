# Data Dictionary

Status: **Proposed.** Defines what each metadata field *means*, who sets it, and whether it is required. Physical columns are in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

Principle: **collect the minimum.** Every optional personal or demographic field exists only because a research use was identified, and it is collected only with consent (`demographics_consented = true`).

## 1. Core metadata (required by the brief)

| Concept | Field(s) | Set by | Required | Sensitivity | Exported? |
|---------|----------|--------|----------|-------------|-----------|
| Submission ID | `submissions.id` (UUIDv7) | System | Yes | Low | Yes |
| Language and identifier | `submissions.language_tag`, `text_layers.language_tag` (BCP 47, default `unr`) | Contributor (default) / reviewer | Yes | Low | Yes |
| Script | `text_layers.script_code` (ISO 15924) | Contributor, auto-suggested | Yes for text | Low | Yes |
| Dialect / regional variety | `submissions.dialect_label`, `speakers.dialect_label` | Contributor/facilitator as **reported**; never inferred | No | Low–medium | Yes (if research consent) |
| Original audio location | `recordings.original_object_key` | System | Yes for audio | **Restricted** | No (export uses package-relative paths) |
| Transcript and translation versions | `text_layers` + `text_revisions.revision_number`, `current_revision_id` | System | — | Low | Yes (selected revision IDs) |
| Duration and technical metadata | `recordings.duration_ms`, `sample_rate_hz`, `channels`, `bit_depth`, `detected_codec`, `detected_container`, `size_bytes`, `is_lossy_source` | System (ffprobe) | Yes for audio | Low | Yes |
| Contributor reference | `submissions.submitted_by` → users | System | Yes | Medium | **No** (replaced by a per-release pseudonymous contributor code if needed) |
| Speaker reference | `speakers.speaker_code` | System | Yes | Medium | Yes as code only (if research consent) |
| Collection context | `submissions.collection_context` (JSONB, schema below) | Contributor/facilitator | Partly | Low–medium | Yes, allow-listed keys only |
| Demographics (optional) | `speakers.age_band`, `gender_self_described`, `first_language`, `other_languages`, `region_coarse` | Speaker via facilitator | No | **Medium–high** | Only if consented and release purpose allows |
| Consent status and permitted uses | `consent_records.status`, `allow_*`, `attribution_preference` | Facilitator/speaker | Yes | Medium | Yes as a **snapshot of permissions only** |
| Source and collection method | `submissions.collection_method`, `recording_mode`, `prompt_id`, `recordings.recorded_device_hint` | Contributor/system | Yes | Low | Yes |
| Processing history | `processing_runs` (job type, tool versions, timestamps, outcome) | System | Yes | Low | Summary in manifest |
| Review status and timestamps | `submissions.status`, `review_events.*` | Reviewers/system | Yes | Low (notes are internal) | Status + dates only |
| Dataset version | `dataset_releases.slug`, `version` | Admin | — | Low | Yes |
| Publication permissions | Effective access (computed) + `dataset_releases.purpose` + `licence` | System + admin | — | — | Yes |

## 2. Controlled vocabularies

### Language tags (BCP 47)
| Tag | Meaning |
|-----|---------|
| `unr` | Mundari (ISO 639-3) |
| `unr-Deva`, `unr-Latn`, `unr-Nagm` | Mundari with script subtag (used for consent forms/UI; text layers store language and script separately) |
| `hi` | Hindi |
| `en` | English |
| `und` | Undetermined (e.g., code-switched segments to be resolved by reviewer) |

Glottolog code for Mundari is `mund1320`; it may be recorded in data cards for interoperability.

### Script codes (ISO 15924)
`Deva` (Devanagari), `Latn` (Latin), `Nagm` (Nag Mundari / Mundari Bani, Unicode block U+1E4D0–U+1E4FF, added in Unicode 15.0), `Beng` (Bengali–Assamese), `Orya` (Odia), `Zyyy` (mixed/undetermined).

### Dialect labels
A controlled list is **pending linguist input (Q-X1)**. Until then: free text, plus a reviewer-maintained mapping table later. Never auto-assign dialect from location.

### `content_type`
`story`, `conversation`, `vocabulary`, `song`, `sentence_list`, `other`.

### `recording_mode`
`free` (spontaneous speech), `prompted` (image or situation prompt), `read` (reading a displayed sentence). See [RECORDING_MODES.md](RECORDING_MODES.md).

### `collection_method`
`self_recorded`, `facilitator_field`, `facilitator_remote`, `imported_archive`.

### `restriction_flags`
| Flag | Meaning | Effect |
|------|---------|--------|
| `sensitive` | Reviewer judges content sensitive for other reasons | Admin + designated reviewers only; excluded from releases unless admin overrides with a recorded reason. |
| `third_party_voice` | Non-consenting person audible | Excluded from all releases. |
| `contains_pii` | Personal details spoken/written | Excluded from public and AI-training releases. |
| `culturally_restricted` | Content the community restricts | Excluded from all releases without explicit community approval (Q-G3). |
| `minor` | Speaker under 18 | Excluded until guardian process confirmed (Q-L4). |

As built (M7): until these rules are confirmed (Q-G3), an item with **any** flag is left out of every dataset release. The narrower per-purpose exclusions above would only ever let more items in, so they wait for that decision.

### `origin` (text revisions)
`human_contributor`, `human_reviewer`, `machine`, `imported`, `prompt_text` (reference sentence of a read-speech prompt).

### `verification_status`
`unverified` (default), `verified` (a reviewer confirmed it matches the audio/source), `disputed` (reviewers disagree or uncertainty unresolved).

## 3. `collection_context` JSONB (allow-listed keys)

| Key | Type | Example | Exported |
|-----|------|---------|----------|
| `setting` | enum: `indoor_quiet`, `indoor_noisy`, `outdoor`, `unknown` | `indoor_quiet` | Yes |
| `speaker_count` | integer | `1` | Yes |
| `equipment` | enum: `phone_builtin_mic`, `phone_external_mic`, `field_recorder`, `unknown` | | Yes |
| `notes` | string (≤ 500 chars) | | **No** (may contain personal details) |

Unknown keys are rejected by API validation. Adding a key requires updating this table and the schema validator.

## 4. What we deliberately do **not** collect

- Exact date of birth (age band is enough).
- Caste, religion, income, or tribe membership beyond what is inherent in language data.
- Precise GPS coordinates or village name linked to a speaker in exportable fields.
- Photographs of speakers.
- Device identifiers or advertising IDs.

If a research need for any of these appears, it requires a governance decision and an update to [CONSENT_AND_DATA_GOVERNANCE.md](CONSENT_AND_DATA_GOVERNANCE.md) first.
