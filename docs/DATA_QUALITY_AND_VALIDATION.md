# Data Quality and Validation

Status: **Proposed.** Distinguishes *hard validation* (input is rejected), *quality signals* (advisory, shown to contributors, admins and researchers), and *dataset checks* (run before a release can be frozen).

## 1. Hard validation (reject)

| Area | Check | Where | Error code |
|------|-------|-------|-----------|
| Audio | Size ≤ limit | Proxy + API | `too_large` |
| Audio | Magic-byte signature in allow-list | API | `bad_signature` |
| Audio | Probe succeeds; exactly one audio stream; values in range | Worker | `unsupported_format`, `out_of_range` |
| Audio | Full decode without errors | Worker | `corrupt_audio` |
| Audio | Duration ≥ 1 s and ≤ 30 min | Worker | `too_short`, `too_long` |
| Text | UTF-8, length limits, disallowed characters | API | see [TEXT_PROCESSING_PIPELINE.md §2](TEXT_PROCESSING_PIPELINE.md#2-safety-validation-reject-do-not-alter) |
| Metadata | Enumerations, required fields, JSONB allow-list for `collection_context` | API (Pydantic) | `validation_error` with field path |
| Consent | Active consent with `allow_store_and_review` before leaving draft | API service | `consent_required` |
| Consent | Speaker flagged `minor` without guardian consent | API service | `guardian_consent_required` |
| Links | Transcription has a recording; translation has a source layer | DB CHECK + API | `invalid_link` |
| Concurrency | Revision `base_revision_id` must be current | API | `409 revision_conflict` |

## 2. Quality signals (advisory)

| Signal | Computed by | Shown to |
|--------|-------------|----------|
| `silent`, `very_quiet`, `clipping`, `too_short` | Audio analysis | Contributor (where detectable before upload), admin, researcher, export |
| `possible_duplicate` | Hash / text match | Admin, researcher |
| Declared vs. detected script mismatch | Text pipeline | Contributor (warning), admin, export |
| Uncertainty markup present | Text pipeline | Researcher, export |
| Translation stale (source revised after translation) | Revision links | Researcher, export |
| Lossy source | Audio probe | Researcher, export |
| VAD speech ratio (optional) | Silero VAD | Admin only, labelled "estimate" |

Since nobody reviews submissions ([ADR-021](ARCHITECTURE_DECISIONS.md#adr-021--no-human-reviewer-accept-after-automatic-checks-keep-text-unverified)), these signals are the main quality information a researcher gets, so exports carry them per item and researchers filter on them.

Signals never change status automatically in MVP. Thresholds are initial guesses and must be tuned against pilot data, with changes recorded here.

## 3. Quality without human review

There is no reviewer in the MVP (ADR-021). Quality rests on:

- **Automatic checks** (§1 rejects, §2 warnings) on every submission. A submission moves to `accepted` only when every check has succeeded.
- **Honest labels.** All contributor text, including the read-mode prompt sentence, stays `verification_status = unverified`. Exports and data cards say "contributor-provided, unverified"; nothing is called "verified".
- **Reports.** Any signed-in user can report an item (personal information, a third party's voice, culturally restricted content, wrong or unrelated content). An admin looks at each report and either hides the item (restriction flag) or dismisses the report, with a reason; both are audited.
- **Spot checks (optional).** When a Mundari speaker is available, an admin may listen to a small random sample before a release and note what they found in the data card. This informs, it does not gate.
- **Later:** peer checking ("does this clip match its text?") as in Mozilla Common Voice, once enough contributors are active. The review tables kept in the schema are reserved for it.

## 4. Dataset pre-freeze checks (automated, must all pass)

| # | Check |
|---|-------|
| D1 | Every item `accepted`, not `withdrawn`, and not hidden by an admin. |
| D2 | Every item's effective consent allows the release purpose (re-computed at freeze time, not cached). |
| D3 | No item has an excluding restriction flag for this purpose. |
| D4 | Every referenced file exists and its stored checksum matches a fresh hash. |
| D5 | Every transcription and translation carries its `verification_status` and origin in the export; none is labelled "verified" unless its revision really has `verification_status = verified`. The data card states how many are unverified. |
| D6 | No export field outside the allow-list (schema test on a generated sample). |
| D7 | Licence and data card present for external/public/AI-training purposes. |
| D8 | Summary statistics (counts by dialect label, script, content type, duration) generated and included in the data card. |
| D9 | No speaker contributes more than a configurable share of total duration without a note in the data card (bias awareness, not a block). |

Built in M7 (`app.modules.releases.freeze`). D3 leaves out an item with any restriction flag until Q-G3 is answered. D7 also fails for every purpose but internal research until `LKD_EXTERNAL_RELEASES_ENABLED=true`. D9's share is `LKD_RELEASE_SPEAKER_SHARE_WARNING` (default 0.3); the data card names the speaker codes above it. `POST /datasets/{id}/checks` shows the results before freezing.

## 5. Data integrity monitoring (scheduled jobs)

| Job | Frequency | Action on failure |
|-----|-----------|-------------------|
| Checksum audit of a random sample of originals | Weekly | Alert admin; restore from backup/versioned object. |
| Orphan check: objects with no DB row / rows with missing objects | Weekly | Report; never auto-delete originals. |
| Quarantine cleanup | Hourly | Delete quarantine objects older than 24 h with no promotion. |
| Consent consistency: submissions linked to withdrawn speakers still visible | Daily | Alert admin; hide immediately. |
