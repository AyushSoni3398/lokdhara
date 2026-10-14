# Assumptions and Open Questions

Status: **Living document.** Update it whenever an assumption is confirmed, disproved, or a question is answered. Record the answer, who decided, and the date; do not delete answered rows.

Legend for *Impact*: **Blocks pilot** (must be answered before collecting real data), **Blocks M#** (blocks a milestone), **Later**.

## 1. Working assumptions

These are assumptions the plan currently relies on. Each one can change the design if it turns out wrong.

| ID | Assumption | If wrong, what changes |
|----|------------|------------------------|
| A1 | Most early contributions come through facilitators, not unaided self-service. | If self-service dominates, invest more in simplified onboarding and in-app audio guidance. |
| A2 | Contributors mainly use Android phones with Chrome; admins and researchers use laptops. | iOS/Safari audio recording formats need extra testing (Safari's MediaRecorder output differs). |
| A3 | Pilot volume is small: tens of speakers, tens to low hundreds of hours of audio in year one. | Storage and processing estimates in [INFRASTRUCTURE_AND_COSTS.md](INFRASTRUCTURE_AND_COSTS.md) scale linearly; architecture holds to at least 10× this. |
| A4 | The team is 2–5 students with Python and JavaScript experience, part-time. | Larger/smaller team changes milestone pacing, not architecture. |
| A5 | Mundari is written in Devanagari, Latin, and Nag Mundari (Mundari Bani) scripts, and possibly Bengali or Odia script in some areas; no single orthography is universally accepted. | If the community/supervisor mandates one orthography, add a validation profile; never drop the original text. |
| A6 | Hindi and English are the translation targets for MVP. | Adding languages is a data change (language codes), not a schema change. |
| A7 | No usable, validated ASR or MT for Mundari exists for production use today. | If one is validated on our data, add it as a *suggestion* source (ADR-014). |
| A8 | Hosting can be either institutional infrastructure or a small paid VPS + object storage. | Deployment doc has both paths. |
| A9 | The repository will contain code and documentation only, never collected data. | — (this is a hard rule, not just an assumption). |
| A10 | Voice recordings are personal data, and some content may be culturally sensitive. | — (treated as true for design purposes). |
| A11 | One recording per submission is enough for the MVP: a retake replaces the recording on the device before upload, and a second part is a separate submission linked as `continuation`. | Allow several recordings per submission; the schema already permits it, only the upload check changes. |

## 2. Open questions

### Legal, ownership, and institution

| ID | Question | Who decides | Impact | Answer |
|----|----------|-------------|--------|--------|
| Q-L1 | Who owns the platform code, and who is the data controller/steward for collected data: the student team, the professor, the institution, or a community body? | Professor + institution (+ community) | **Blocks pilot** | — |
| Q-L2 | Does the institution's IP policy apply to code and data produced in this project? Is any sponsor/funder imposing terms? | Institution, funder | **Blocks pilot** | — |
| Q-L3 | Is ethics committee (IEC/IRB) approval required before collecting recordings? Which committee, which forms? | Professor + institution | **Blocks pilot** | — |
| Q-L4 | What is the approved procedure for minors (age threshold, guardian verification, whether minors participate at all in the pilot)? The DPDP Rules 2025 require verifiable parental consent for processing children's data; applicability to this research must be confirmed by legal advice. | Institution legal / ethics | **Blocks pilot** (until answered, the plan is: **no minors in pilot**) | — |
| Q-L5 | Which licence(s) will apply to released datasets (e.g., a Creative Commons variant, a custom research licence, or community-specific terms)? | Professor, community, institution | Blocks M7 | — |
| Q-L6 | Which licence applies to the source code? | Repository owners | Later (before any public release) | — |
| Q-L7 | Is there a data-residency requirement (data must stay in India)? | Institution / legal | Blocks M8 (hosting choice) | — |
| Q-L8 | Does the DPDP Act research exemption (Section 17(2)(b)) apply to this project, and what obligations remain? | Legal adviser | **Blocks pilot** | — |

### Governance and community

| ID | Question | Who decides | Impact | Answer |
|----|----------|-------------|--------|--------|
| Q-G1 | Which community body or representatives should approve public release and AI-training uses? | Professor + community | Blocks any public/AI release | — |
| Q-G2 | Should speakers be credited by name by default, pseudonymously, or by their choice? (Plan: by their choice, default pseudonymous.) | Community + professor | Blocks M3 | *Provisional for development (2026-10-12):* the speaker chooses; default pseudonymous. |
| Q-G3 | Which content categories are culturally restricted (e.g., ritual songs, sacred stories), and who can see them? | Community representatives | Blocks M6 | — |
| Q-G4 | In field practice, is consent captured before or after recording? | Facilitators + ethics | Blocks M3 | *Provisional for development (2026-10-12):* the app asks for consent first, but a draft may be recorded before consent; it cannot be submitted until consent is attached (enforced by the database). |
| Q-G5 | How are export holders bound to withdrawal requests (data use agreement)? | Professor + institution | Blocks M7 | — |
| Q-G7 | Who approves images and situation prompts as culturally appropriate? | Community representatives | Blocks M3 | *Provisional for development (2026-10-12):* reviewers and admins draft prompts and only an admin approves them; a community reviewer still has to be named before real collection. |
| Q-G6 | How is benefit returned to the community (access to materials, educational outputs)? | Professor + community | Later | — |

### Linguistic

| ID | Question | Who decides | Impact | Answer |
|----|----------|-------------|--------|--------|
| Q-X1 | Which dialect/variety labels should be offered as a controlled list (with free text always allowed)? | Linguist / professor | Blocks M3 | — |
| Q-X2 | Is there a preferred orthography or normalisation policy for derived (not original) text? | Linguist + community | Blocks M5 (normalised field stays empty until decided) | — |
| Q-X3 | Which uncertainty and annotation conventions should transcribers use (e.g., unclear word, overlapping speech, code-switching to Hindi)? | Linguist | Blocks M5 | *Provisional for development (2026-10-12):* the markup in [TEXT_PROCESSING_PIPELINE.md](TEXT_PROCESSING_PIPELINE.md) §8; only `[?…]` and `[inaudible]` set the uncertainty flag. |
| Q-X4 | Which scripts must be supported for input at launch (Devanagari and Latin certain; Nag Mundari likely)? | Linguist + community | Blocks M3 | — |
| Q-X5 | Which topics and initial prompts (images, situations) should be offered? | Linguist + community | Blocks M3 | *Provisional for development (2026-10-12):* `seed-dev` adds three team-written Hindi situation prompts with free-form topic tags; no images yet. |
| Q-X6 | Where does the read-sentence bank come from (written by reviewers, existing texts), and under what licence? | Linguist + owner | Blocks M3 | *Provisional for development (2026-10-12):* one Hindi placeholder sentence, clearly marked, so read mode can be tested; no Mundari sentences until this is answered. |

### Product and project

| ID | Question | Who decides | Impact | Answer |
|----|----------|-------------|--------|--------|
| Q-P1 | Can we run 3–5 short sessions with real contributors/facilitators to validate personas and flows before M3 UI work? | Ayush + professor | Blocks M3 | — |
| Q-P2 | What pilot success targets (speakers, hours, reviewed items) does the supervisor want? | Professor | Blocks M8 | — |
| Q-P3 | Who are the initial reviewers and administrators? | Ayush + professor | Blocks M6 | Answered 2026-10-14 by the professor: **no human reviewers**. Nobody on the team can review recordings manually, so submissions are accepted after the automatic checks and their text stays unverified ([ADR-021](ARCHITECTURE_DECISIONS.md#adr-021--no-human-reviewer-accept-after-automatic-checks-keep-text-unverified)). The team's admins (Ayush and the professor) handle reports and withdrawals. |
| Q-P4 | The GitHub repository `AyushSoni3398/lokdhara` is currently **public** and owned by AyushSoni3398. The brief requires a private repository unless the owner approves otherwise. Should it be made private, and who is the owner of record? | Ayush Soni (AyushSoni3398, owner) | **Blocks pushing planning docs** | Answered 2026-10-11: keep the repository **public** (code and docs only; data never committed). |
| Q-P5 | Budget available for hosting (₹/month), and whether institutional servers are available. | Professor / institution | Blocks M8 | — |

### Technical (to be validated by spikes, not decided by debate)

| ID | Question | How it gets answered | Impact |
|----|----------|----------------------|--------|
| Q-T1 | Which recording formats do target phones' browsers actually produce, and do they decode reliably with ffmpeg? | Spike in M1 on real devices | **Answered for Android Chrome** (see §2.1); iOS Safari still untested |
| Q-T2 | Is Opus playback reliable on all target browsers (notably iOS Safari), or is an AAC fallback needed? | Spike in M4 | Unblocked 2026-10-13: an AAC copy (`playback_aac`) is made for every recording, so playback works without Opus. Still to check on an iPhone whether Opus alone would do. |
| Q-T3 | Are proposed upload limits (100 MB / 30 min) right for field recordings? | Pilot feedback | Later |
| Q-T4 | Which object-storage provider meets cost and residency needs? | Compare after Q-L7 | Blocks M8 |
| Q-T5 | Does near-duplicate audio detection (e.g., Chromaprint) work usefully on speech? | Experiment in M4 | Later |
| Q-T6 | Which fonts render Nag Mundari acceptably on target phones? | Device test in M3 | Blocks M3 if Nag Mundari is required |
| Q-T7 | How long may an uploaded file wait in quarantine for its draft to be submitted? The SPA submits right after uploading, but `cleanup.quarantine` must not delete files of drafts still being submitted. | Decide in M4 | Answered 2026-10-14 by the project owner: **30 days** (`LKD_DRAFT_UPLOAD_RETENTION_DAYS`). After that an hourly `cleanup.expire_drafts` job deletes the draft's quarantine copy and marks the recording `expired`. The draft stays, and when it is sent the app uploads the recording again from the phone, which restores the same recording. |

### 2.1 Q-T1 findings: device recording spike (2026-10-11)

Method: a standalone test page reported `MediaRecorder.isTypeSupported` results, recorded a 4-second synthetic tone through `MediaRecorder` with no microphone, decoded it in the browser, and analysed a ~10 s file from the phone's own recorder app. Formats were then checked with FFmpeg 6.1 on equivalent files produced by Chromium's `MediaRecorder`. No audio was uploaded or kept.

| Device | Browser | Default `MediaRecorder` output | Also supported | Phone recorder app |
|--------|---------|-------------------------------|----------------|--------------------|
| Android 10 phone (owner's) | Chrome 149 | `audio/webm;codecs=opus`, WebM container, 48 kHz | `audio/mp4` with AAC (`mp4a.40.2`) or Opus | `.aac`, AAC in ADTS, 48 kHz stereo, ~99 kbit/s |
| Android 10 phone (second tester) | Chrome 154 | same type support (recording step not run) | same | not tested |
| iPhone / iOS Safari | — | **not tested** | — | — |

Conclusions:

1. Android Chrome records **WebM/Opus at 48 kHz** by default; the browser recorder should request `audio/webm;codecs=opus` first, then `audio/mp4`, and send whatever `MediaRecorder.mimeType` reports.
2. Uploaded files from phone recorder apps arrive as **AAC (ADTS) `.aac`**, so the allow-list must include `aac` (ADTS) as well as WebM, Ogg, MP4/M4A, WAV, FLAC, and MP3.
3. FFmpeg decodes all three formats fully (WebM/Opus, MP4/Opus, ADTS/AAC).
4. **WebM files from `MediaRecorder` carry no duration** in the header (`ffprobe` reports `duration=N/A`). `duration_ms` must come from the full decode, not from ffprobe's format header (AUDIO_PROCESSING_PIPELINE §3.5). ADTS durations from ffprobe are estimates for the same reason.
5. A real microphone recording through the browser was not possible from the test page (sandbox blocked the mic); it uses the same encoder, so the format is expected to match. M3 must confirm on a real phone.
6. Still open: iOS Safari (expected `audio/mp4`), and a low-end Android phone. Q-T2 (Opus playback on iOS) remains an M4 task.

## 3. Decision log for answered questions

| Date | ID | Decision | Decided by |
|------|----|----------|-----------|
| 2026-10-11 | Plan | Planning phase (M0) approved; ADR-001–018 accepted | Ayush Soni (owner) |
| 2026-10-11 | Q-P4 | Repository stays public | Ayush Soni (owner) |
| 2026-10-11 | Q-T1 (partial) | Android Chrome records WebM/Opus 48 kHz; phone recorder apps give AAC/ADTS; duration taken from full decode; iOS still to test | Device spike (owner + one tester) |
