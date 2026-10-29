# Product Requirements — Lokdhara MVP

Status: **Draft for approval** · Planning phase · Last updated 2026-10-11

## 1. Purpose of this document

This document says *what* the first version of Lokdhara must do and *why*. It does not choose technologies (see [TECH_STACK_EVALUATION.md](TECH_STACK_EVALUATION.md)) or define the exact scope boundary (see [MVP_SCOPE.md](MVP_SCOPE.md)). Requirements are numbered so that tests, milestones, and reviews can refer to them.

## 2. Problem statement

Mundari (ISO 639-3 `unr`), an Austroasiatic (Munda) language spoken mainly in Jharkhand and neighbouring states of India, has comparatively little structured, consented, and well-documented digital language data. Recordings that do exist are often scattered across personal phones, individual research projects, and messaging apps, with no record of who spoke, under what consent, or how the content was transcribed.

Lokdhara aims to give the Mundari-speaking community and researchers one place to:

1. Collect recordings and texts from native speakers with explicit, recorded consent.
2. Link audio to transcriptions and to Hindi and English translations.
3. Check that material automatically, keep its history visible, and label contributor text honestly as unverified.
4. Produce versioned, documented datasets that are released only within the permissions the speakers granted.

## 3. Goals and non-goals

### Goals (MVP)

| ID | Goal |
|----|------|
| G1 | Let a contributor, or a facilitator working with a speaker, submit audio, text, or both, from a low-end Android phone on a slow connection. |
| G2 | Record consent and permitted uses *before* any submission can leave the draft state. |
| G3 | Preserve every original recording and original text byte-for-byte; all processing produces separate derived artefacts. |
| G4 | Accept submissions that pass automatic checks without a human reviewer, label their text as contributor-provided and unverified, and let administrators hide reported items, with every change attributed and versioned ([ADR-021](ARCHITECTURE_DECISIONS.md#adr-021--no-human-reviewer-accept-after-automatic-checks-keep-text-unverified)). |
| G5 | Let authorised researchers build an immutable, versioned dataset release from accepted items and export it in a documented format, filtered by consent. |
| G6 | Honour withdrawal requests across live data, future releases, and (as far as technically possible) existing releases. |

### Non-goals (MVP)

- General cultural-heritage collections (recipes, artefacts, traditions) — see [MVP_SCOPE.md](MVP_SCOPE.md).
- Automatic speech recognition (ASR) or machine translation (MT) in production.
- Public, anonymous browsing of recordings.
- Native mobile apps.
- Payments, rewards, or gamification.

## 4. Users and roles (summary)

Detailed personas are in [USER_PERSONAS.md](USER_PERSONAS.md); permissions are in [ACCESS_CONTROL.md](ACCESS_CONTROL.md).

| Role | One-line description |
|------|----------------------|
| Contributor | A native speaker (or community member) submitting their own speech or text. |
| Facilitator | A trusted community member or field researcher who records *other* speakers and captures their consent. A contributor with extra permissions. |
| Reviewer | A Mundari-literate person who checks transcription, translation, quality, and sensitivity. **Not used in the MVP:** the team has no reviewers (ADR-021). The role stays in the code for later peer checking. |
| Researcher | An authorised linguist or student who reads accepted data and requests exports. |
| Administrator | Manages accounts, roles, consent-form versions, withdrawals, and operations. |

## 5. Functional requirements

Priority: **M** = must have for MVP, **S** = should have if time allows, **F** = future.

### 5.1 Accounts and access

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-A1 | Anyone may sign up as a contributor with a username and password; staff roles are given by invitation or by an administrator (ADR-028, changed 2026-10-23). | M |
| FR-A2 | A user can sign in, sign out, and see their own role(s). | M |
| FR-A3 | Roles are assigned and revoked by administrators only; every change is audit-logged. | M |
| FR-A4 | Sessions expire after inactivity; administrators can revoke a user's sessions. | M |
| FR-A5 | Password reset is administrator-assisted in the pilot (no email/SMS dependency). | M |
| FR-A6 | Self-service password reset via email or SMS. | F |
| FR-A7 | The interface is available in Hindi and English, with the structure ready for a Mundari interface translation. | M (Hindi, English) / S (Mundari UI strings) |

### 5.2 Speakers and consent

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-C1 | Each recording and text is linked to a *speaker* record identified by a pseudonymous speaker code, not by name. | M |
| FR-C2 | Identifying details (name, contact) are optional, stored separately, and visible only to administrators and the facilitator who created them. | M |
| FR-C3 | Consent is captured against a specific, versioned consent form in a language the speaker understands, with separate yes/no answers for each permitted use (see [CONSENT_AND_DATA_GOVERNANCE.md](CONSENT_AND_DATA_GOVERNANCE.md)). | M |
| FR-C4 | Consent can be captured as an in-app confirmation, an audio-recorded oral consent, or a reference to a paper form held offline. Evidence files are stored in restricted storage, never in the repository. | M |
| FR-C5 | A submission without an active consent record cannot be submitted for review. | M |
| FR-C6 | Speakers under 18 may contribute without a parent or guardian (owner's decision 2026-10-29, Q-L4, ADR-032). The record can still note a guardian if one takes part. | M |
| FR-C7 | A speaker or their representative can withdraw or narrow consent; the system records the request and propagates it (see [DATA_RETENTION_AND_DELETION.md](DATA_RETENTION_AND_DELETION.md)). | M |

### 5.3 Submissions

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-S1 | A user chooses audio, text, or audio + text when starting a submission. | M |
| FR-S2 | Audio can be recorded in the browser or uploaded from a file. | M |
| FR-S2a | Every audio submission uses one of three recording modes: **free speech**, **prompted speech** (describe an image or respond to a situation), or **read speech** (read a displayed Mundari sentence). See [RECORDING_MODES.md](RECORDING_MODES.md). | M |
| FR-S2b | Administrators and reviewers manage a versioned prompt library (images, situations, read sentences); only approved prompts are shown to contributors. | M |
| FR-S3 | Text entries can be a word, phrase, sentence, paragraph, or longer story/conversation, with the script (Devanagari, Latin, Nag Mundari/Mundari Bani, other) recorded. | M |
| FR-S4 | A transcription can be attached to a recording, and Hindi and/or English translations to a transcription or text entry. Each is optional at submission time. | M |
| FR-S5 | Metadata: content type (story, conversation, vocabulary, song, other), dialect/region as reported, recording context, recording date, and optional consented speaker attributes. | M |
| FR-S6 | A submission can be saved as a draft on the device and resumed; an interrupted upload does not lose the recording. | M |
| FR-S7 | The contributor sees the status of their own submissions (draft, processing, accepted, could not be processed, rejected as invalid, hidden, withdrawn). | M |
| FR-S8 | Resumable chunked upload for long recordings on unstable connections. | S |
| FR-S9 | Time-aligned segments (start/end times within a recording) for transcriptions. | F (schema reserved) |

### 5.4 Validation and processing

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-P1 | Uploaded files are validated by file signature and by decoding, not by extension or browser-reported type. | M |
| FR-P2 | Size and duration limits are enforced (initial values in [AUDIO_PROCESSING_PIPELINE.md](AUDIO_PROCESSING_PIPELINE.md)). | M |
| FR-P3 | Technical metadata (codec, sample rate, channels, bit depth, duration) is extracted and stored. | M |
| FR-P4 | Derived renditions are produced: a low-bandwidth playback file and a standard analysis file. The original is never modified or deleted by processing. | M |
| FR-P5 | Basic quality metrics (silence ratio, clipping, loudness) are computed and shown to contributors, administrators and researchers as advisory signals. | M |
| FR-P6 | Exact duplicates (same file hash) are detected; near-duplicates are flagged and linked, never auto-deleted. | M (exact) / S (near) |
| FR-P7 | Text is stored verbatim; Unicode-normalised and policy-normalised forms are separate derived fields. | M |
| FR-P8 | Processing failures are logged, retried with limits, and visible to administrators; a failed job can be re-run. | M |

### 5.5 Acceptance and reports (no human review)

The professor decided on 2026-10-14 that there is no human reviewer ([ADR-021](ARCHITECTURE_DECISIONS.md#adr-021--no-human-reviewer-accept-after-automatic-checks-keep-text-unverified)). The review requirements FR-R1 to FR-R6 are replaced by:

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-R1 | A submission whose automatic checks all succeed becomes `accepted` without waiting for a person. | M |
| FR-R2 | Contributor text, including the read-mode prompt sentence, stays `unverified`; no screen or export calls it verified. | M |
| FR-R3 | Any signed-in user can report an item (personal information, a third party's voice, culturally restricted, wrong content). | M |
| FR-R4 | An administrator can hide a reported item with a restriction flag, or dismiss the report, with a reason; both are audit-logged. Hidden items leave the catalogue and future releases. | M |
| FR-R5 | Corrections are new revisions by the contributor or an administrator; the earlier revision remains. | M |
| FR-R6 | Peer checking of clips and text by other contributors, or by reviewers if any become available. | F |

### 5.6 Researcher access and datasets

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-D1 | Researchers can search and filter approved items they are authorised to see. | M |
| FR-D2 | An administrator or authorised researcher can create a dataset release from a filter, review its contents, and freeze it. A frozen release cannot change. | M |
| FR-D3 | A release includes only items whose *current* consent allows the release's declared purpose. | M |
| FR-D4 | An export package contains audio, text layers, a manifest, a data card, and checksums, in the format in [DATASET_VERSIONING.md](DATASET_VERSIONING.md). | M |
| FR-D5 | Export downloads are time-limited, attributed, and audit-logged. | M |

### 5.7 Administration and audit

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-X1 | An append-only audit log records sign-ins, role changes, consent changes, review decisions, restricted-data access, exports, and deletions. | M |
| FR-X2 | Administrators can manage consent-form versions, withdrawal requests, and failed processing jobs. | M |

## 6. Non-functional requirements

| ID | Requirement | Target (initial, to be validated in pilot) |
|----|-------------|--------|
| NFR-1 Low bandwidth | Contribution pages usable on a 2G/3G-class connection. | Initial JS+CSS for the contribution flow ≤ 250 KB compressed; no web fonts required to read Hindi/English UI. |
| NFR-2 Mobile | Works on mid/low-end Android Chrome; responsive down to 360 px width. | Tested on at least one low-end Android device in M8. |
| NFR-3 Accessibility | Large touch targets, icon + text labels, audio prompts possible later. | WCAG 2.2 AA for core flows as a goal, not a claim. |
| NFR-4 Multilingual | All UI strings externalised; no hard-coded language in components. | Hindi + English at launch. |
| NFR-5 Integrity | Originals immutable; every derived file traceable to its source and the tool version that created it. | Checksums verified on every export. |
| NFR-6 Privacy | Data minimisation; restricted data separated; least-privilege access. | See [PRIVACY_AND_SECURITY.md](PRIVACY_AND_SECURITY.md). |
| NFR-7 Maintainability | One backend language, one database, one deployable unit plus a worker. | A new student contributor can run the stack locally in under an hour. |
| NFR-8 Cost | Pilot runs within a small monthly budget or on institutional infrastructure. | See [INFRASTRUCTURE_AND_COSTS.md](INFRASTRUCTURE_AND_COSTS.md). |
| NFR-9 Recoverability | Database and object storage backed up; restore tested. | RPO 24 h, RTO 48 h for the pilot. |

## 7. Edge cases, failure states, and abuse scenarios

| Scenario | Required behaviour |
|----------|--------------------|
| Upload interrupted at 90% | Recording remains in the device draft; retry resumes or restarts without data loss. The server never keeps a partial upload: a cut-off transfer is discarded at once. |
| File renamed to `.mp3` but is an executable or HTML | Rejected by signature/decoder check; logged as a validation failure; nothing promoted to permanent storage. |
| Valid audio, but 100% silence or < 1 s | Accepted into quarantine, flagged `silent`/`too_short`; contributor told before final submission when detectable client-side. |
| Same file uploaded twice | Exact hash match flagged; contributor sees "this looks like a recording you already submitted"; both kept and linked as possible duplicates for researchers to filter. |
| Same story recorded twice by the same speaker | Not a duplicate: both kept; an administrator may link them as related takes. |
| Transcription present, no translation | Valid. Item can be included in audio+transcript datasets; translation status shown as missing. |
| Contributor marks a transcription as uncertain | Uncertainty kept as structured markup; the export carries the uncertainty; nothing is marked "verified transcript" in the MVP. |
| Machine-generated transcript (future) | Stored with `origin = machine`; never counted as verified. |
| Speaker under 18, no guardian consent | Submission cannot leave the draft state; stays private to the facilitator; flagged to an administrator. |
| Recording contains third parties who did not consent | Someone reports it and an administrator marks `restricted: third_party_voice`; excluded from all releases until resolved. |
| Content is sacred, ritual, or culturally restricted | Someone reports it and an administrator marks `restricted: culturally_sensitive`; visible only to administrators and designated community members; never exported without explicit community approval (see open question Q-G3). |
| Personal information spoken in the recording (phone numbers, names of others) | Someone reports it and an administrator flags `contains_pii`; excluded from public/AI-training releases; redaction is future work. |
| Abusive, hateful, or spam submissions | Reported and hidden by an administrator; repeated abuse leads to account suspension. Sign-ups are limited per network (ADR-028). |
| Account compromise | Admin revokes sessions; audit log identifies affected actions. |
| Consent withdrawn after an item was included in a frozen release | Item marked withdrawn; excluded from all *future* releases; release record annotated; holders of prior exports notified per governance policy. |
| Facilitator leaves the project | Their submissions remain; ownership of speaker contact data transfers to an administrator. |
| Processing job crashes repeatedly | After N attempts the job is marked `dead`, the submission shows `processing_failed`, and an admin can re-queue after fixing the cause. Original remains intact. |

## 8. Success criteria for the pilot

These are proposed and need agreement with the supervising professor (open question Q-P2):

- A defined number of consented speakers and hours of accepted audio (target to be set).
- Zero incidents of sensitive data committed to the repository or exposed publicly.
- At least one frozen, documented dataset release that a researcher outside the core team can load using only the data card.
- Contributors can complete a submission without help after one demonstration (observed in pilot).

## 9. Related documents

- [USER_PERSONAS.md](USER_PERSONAS.md), [USER_FLOWS.md](USER_FLOWS.md), [MVP_SCOPE.md](MVP_SCOPE.md)
- [ASSUMPTIONS_AND_OPEN_QUESTIONS.md](ASSUMPTIONS_AND_OPEN_QUESTIONS.md)
- [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md), [CONSENT_AND_DATA_GOVERNANCE.md](CONSENT_AND_DATA_GOVERNANCE.md)
