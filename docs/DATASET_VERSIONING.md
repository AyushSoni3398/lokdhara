# Dataset Versioning and Export Format

Status: **Built in M7** (releases, checks, freezing, retraction, export packages); the withdrawal workflow (§2) follows in M7 part 2. Datasets are **never** stored in Git (ADR-013, ADR-017).

## 1. Concepts

| Term | Meaning |
|------|---------|
| **Release** | A named, versioned selection of approved items for a declared purpose, e.g., `mundari-speech-pilot@0.1.0`. |
| **Draft release** | Selection criteria + preview; can change. |
| **Frozen release** | Immutable list of exact item revisions and file checksums, plus a data card and manifest. |
| **Export package** | A generated ZIP (or directory) for one frozen release, built on request, time-limited. Can be rebuilt byte-identically from the manifest while files still exist. |
| **Retraction** | Marking a frozen release as no longer to be used (e.g., after a serious consent issue). The record stays for audit. |

## 2. Version numbers (SemVer adapted to data)

- **MAJOR**: schema of the export changes incompatibly (renamed fields, new file layout).
- **MINOR**: items added (new approved contributions).
- **PATCH**: corrections — revised transcripts, removed withdrawn items, metadata fixes.

A withdrawal therefore produces a new **PATCH** release that excludes the item; the old release is annotated (`withdrawn_after_release_at`) and its data card updated with a notice. Old frozen manifests are kept for reproducibility of published results, but **export of old releases with withdrawn items is blocked**.

## 3. Purpose gates

| Release `purpose` | Consent flag required for every item | Additional requirements |
|-------------------|---------------------------------------|-------------------------|
| `internal_research` | `allow_research` | Project members only. |
| `external_research` | `allow_research` | Data-use agreement signed (Q-G5); licence set. |
| `public` | `allow_public_access` | Community + institutional approval recorded (Q-G1); licence set. |
| `ai_training` | `allow_ai_training` (and `allow_commercial_use` if the use is commercial) | Separate governance approval. |

Items with restriction flags are excluded according to [DATA_DICTIONARY.md §2](DATA_DICTIONARY.md#2-controlled-vocabularies). Until the community decides on Q-G3, an item with **any** restriction flag is left out of every release, `culturally_restricted` included. The rule lives in `app.modules.consents.access` (`in_release` and `release_filter`), with one table of test cases for both.

Releases other than `internal_research` also need `LKD_EXTERNAL_RELEASES_ENABLED=true`, which is set only once those governance answers are recorded; until then check D7 fails for them.

**How a release is made.** A researcher or admin starts a draft (`slug`, `purpose`, selection criteria: kinds, content types, recording modes, dialect labels, only items with audio, only items with text) and previews it. `POST /datasets/{id}/checks` runs D1–D9 ([DATA_QUALITY_AND_VALIDATION.md §4](DATA_QUALITY_AND_VALIDATION.md)). An admin freezes it with a version: the checks run again, consent is re-computed, one `dataset_release_items` row records each item's revisions, audio copy and consent, and the package's text files (items.jsonl, README.md, datacard.json, LICENSE.txt, manifest.json) are stored. Exports are asked for with a purpose statement, approved by another admin, and built by the `dataset.export` job from those stored files plus the audio copies, each checked against the manifest. Packages expire after `LKD_EXPORT_RETENTION_DAYS` (`cleanup.expire_exports`, hourly).

## 4. Export package layout (v1)

```
mundari-speech-pilot-0.1.0/
├── README.md                 # human-readable data card
├── datacard.json             # machine-readable data card
├── manifest.json             # release metadata + per-file sha256
├── LICENSE.txt               # licence text for this release
├── items.jsonl               # one JSON object per item (see below)
├── audio/
│   └── {item_id}.flac        # analysis rendition (16 kHz mono FLAC)
└── checksums.sha256          # sha256sum-compatible list
```

Originals are **not** included by default (privacy, size); a release may include them only if its purpose and governance approval explicitly allow it.

### `items.jsonl` record (v1)

```json
{
  "item_id": "0192f1c4-…",
  "language": "unr",
  "speaker_code": "SPK-7Q3M9",
  "dialect_label": "reported label or null",
  "content_type": "story",
  "collection_method": "facilitator_field",
  "recording_mode": "prompted",
  "prompt": {"id": "…", "key": "img-farming-012", "version": 2, "type": "image"},
  "recorded_on": "2027-01-15",
  "audio": {"path": "audio/0192f1c4-….flac", "duration_ms": 61234, "sample_rate_hz": 16000, "is_lossy_source": true, "sha256": "…", "bytes": 1960000},
  "transcription": {"revision_id": "…", "language": "unr", "script": "Deva", "text": "…", "origin": "prompt_text", "verification_status": "unverified", "uncertainty_markup": false},
  "text": null,
  "translations": [{"language": "hi", "script": "Deva", "revision_id": "…", "source_revision_id": "…", "text": "…", "origin": "human_contributor", "verification_status": "unverified", "uncertainty_markup": false}],
  "quality_flags": [],
  "consent_permissions": {"research": true, "public": false, "ai_training": false, "commercial": false},
  "speaker": {"age_band": "45-59"}
}
```

`transcription` is what is said in a recording; `text` is a text-only item (a standalone text layer); either may be `null`. `speaker` is `{}` unless the speaker agreed to share demographics. Items are sorted by `item_id`.

Fields are produced from an **explicit allow-list** in code (`app.modules.releases.package`); anything not in the allow-list is never exported (contacts, names, review notes, `collection_context.notes`, object keys, user IDs).

### `manifest.json` (v1)

`release_slug, version, purpose, licence, frozen_at, frozen_by_role, item_count, total_duration_ms, export_format_version: "1", lokdhara_git_commit, files: [{path, sha256, bytes}]` (every file except `manifest.json` and `checksums.sha256`; `checksums.sha256` also lists the manifest). Without a licence, LICENSE.txt says the data is for internal research within the project only.

### Data card contents

Following the spirit of "Datasheets for Datasets" (Gebru et al.) and Data Statements for NLP (Bender & Friedman): motivation, composition (counts by dialect label, content type, script, duration), collection process, consent and permitted uses, preprocessing applied, known limitations (e.g., lossy sources, unverified translations), distribution terms, maintenance contact, withdrawal notice section.

## 5. Reproducibility

- Each frozen release stores the Git commit of the Lokdhara code that produced it.
- The export builder is deterministic: sorted items, fixed ZIP timestamps, so rebuilding yields identical checksums.
- Release manifests are retained even after the export package expires.

## 6. Why not Git LFS / DVC for data?

They are good tools for public, derived datasets, but they place data next to a code repository and assume distribution rights that we do not yet have. Revisit for **public** releases only, once licences and governance are settled; a research data repository that issues DOIs (e.g., Zenodo or an institutional repository) may be the better publication channel.
