# Audio Processing Pipeline

Status: **Proposed.** Commands below were smoke-tested with FFmpeg 6.1 on synthetic audio during planning (2026-10-11); exact flags and thresholds must be re-validated in Milestone 4 against real device recordings (Q-T1).

Implementation status (Milestone 4, parts 1 to 6): §3.2 probe, §3.3 full decode, and §3.4 promotion run in the `audio.validate` job (`backend/app/audio/`, `backend/app/modules/submissions/processing.py`); a `cleanup.quarantine` job then deletes the quarantine copy, and the `audio.analyze` job (§3.5) measures the original and sets the reviewer flags; `audio.renditions` (§3.6) makes the derived copies; `audio.dedupe` (§3.7) flags and links duplicates. Submissions move on as their jobs settle (§3.8).

**FFmpeg version:** 6.1 as packaged by Ubuntu 24.04 (`6.1.1-3ubuntu5` when this was written). CI installs the same package on an `ubuntu-24.04` runner, and the worker image must use it too. The exact `-version` line of `ffmpeg` and `ffprobe` is stored in `processing_runs.tool_versions` for every validation.

## 0. Principles

1. **The original is sacred.** It is stored exactly as received after validation and never modified, overwritten, or deleted by processing (ADR-009).
2. **Deterministic first.** Validation, metadata, conversion, and metrics use FFmpeg/ffprobe with pinned versions. Model-based steps (VAD) are advisory and labelled as such.
3. **Everything is traceable.** Each derived file records source checksum, parameters, tool versions, and the `processing_runs` row that created it.
4. **Fail visibly.** Every failure has an error code the contributor or admin can understand; nothing is silently dropped.

## 1. Accepted inputs (initial)

| Container / codec | Typical source | Accept |
|-------------------|----------------|--------|
| WebM / Opus | Chrome/Android `MediaRecorder` | Yes |
| Ogg / Opus | WhatsApp-style voice notes, Firefox | Yes |
| MP4 (M4A) / AAC | iOS Safari `MediaRecorder`, phone recorder apps | Yes |
| Raw AAC in ADTS (`.aac`) | Android phone recorder apps (seen in the Q-T1 spike) | Yes |
| WAV / PCM (8–32-bit int, 32-bit float) | Field recorders | Yes |
| FLAC | Field recorders, archives | Yes |
| MP3 | Older recordings | Yes |
| 3GP / AMR-NB/WB | Older feature-phone recordings | **Evaluate** in M4 (decoder availability in the pinned FFmpeg build) |
| Anything else | — | Reject with `unsupported_format` |

Browser-reported MIME type and file extension are recorded for diagnostics only and **never trusted**.

## 2. Limits (initial values, configurable via environment)

| Limit | Value | Rationale |
|-------|-------|-----------|
| Max upload size | 100 MB | Covers ~10 min of 44.1 kHz stereo WAV or many hours of Opus; protects bandwidth and disk. |
| Max duration | 30 min | Long stories should be split; segmentation is future work. |
| Min duration | 1 s | Shorter is almost always accidental. |
| Max channels | 2 | Multi-track recordings out of scope. |
| Sample rate | 8 kHz – 96 kHz | Outside this, likely corrupt. |
| Uploads per user per hour | 60 | Abuse control; adjustable. |

Limits are enforced at three layers: Caddy (`request_body max_size`), API (streaming byte counter aborts early), worker (duration after decode).

## 3. Pipeline stages

```mermaid
flowchart TD
    A[API: stream to quarantine<br/>count bytes, sha256, sniff first 64 bytes] -->|size/magic fail| X1[reject: too_large / bad_signature]
    A --> B[job audio.validate]
    B --> B1[ffprobe: container, codec, rate, channels, duration]
    B1 -->|not allowed| X2[reject: unsupported_format / out_of_range]
    B1 --> B2[full decode to null sink<br/>ffmpeg -v error -xerror]
    B2 -->|decode errors| X3[reject: corrupt_audio]
    B2 --> C[promote: copy to originals/, verify sha256, mark promoted]
    C --> D[job audio.analyze]
    C --> E[job audio.renditions]
    C --> F[job audio.dedupe]
    D --> G{all succeeded?}
    E --> G
    F --> G
    G -->|yes| H[submission: accepted]
```

### 3.1 Signature check (API, synchronous)

Read the first 64 bytes and match against an allow-list of magic numbers:

| Format | Signature |
|--------|-----------|
| WAV | `RIFF....WAVE` |
| FLAC | `fLaC` |
| Ogg | `OggS` |
| WebM/Matroska | `1A 45 DF A3` |
| MP4/M4A | `....ftyp` (bytes 4–7) with brand allow-list (`M4A `, `mp42`, `isom`, `iso5`, …) |
| MP3 | `ID3` or MPEG frame sync `FF Ex`/`FF Fx` |
| AAC (ADTS) | ADTS sync `FF F1` / `FF F9` (layer bits `00`); shares the MPEG sync pattern, so tell it apart from MP3 by the layer bits |
| 3GP/AMR | `....ftyp3gp` / `#!AMR` (if accepted) |

A signature match is necessary but not sufficient; the full decode in 3.3 is the real check.

### 3.2 Probe (worker)

```bash
ffprobe -v error -show_entries \
  format=format_name,duration,size,bit_rate:stream=codec_type,codec_name,sample_rate,channels,bits_per_sample,sample_fmt \
  -of json input
```

Reject if: no audio stream, more than one audio stream, any video stream with real frames (cover art in MP3/M4A is ignored), values outside §2.

As built, both ffprobe and FFmpeg are told which demuxer to use (`-f matroska`, `ogg`, `wav`, `flac`, `mov`, `aac`, or `mp3`, from the container the API recognised in §3.1), so FFmpeg never guesses among its other input formats. Accepted codecs: Opus, Vorbis, AAC, MP3 (lossy), FLAC and PCM `u8`/`s16le`/`s24le`/`s32le`/`f32le` (lossless). Rejections are stored in `recordings.validation_errors` as `{"code", "reason"}`, for example `{"code": "out_of_range", "reason": "too_long"}`.

### 3.3 Full decode integrity check

```bash
ffmpeg -v error -xerror -i input -map 0:a:0 -f null -
```

Any stderr output at `error` level → `corrupt_audio`. This also catches truncated uploads that probe correctly.

As built, the same run measures `duration_ms` (from `-progress`) and stops reading just after `LKD_MAX_AUDIO_SECONDS`, so an over-long file costs no more than the limit. Tests showed that a cut-off WebM, WAV, FLAC, M4A, or AAC file is caught, but an MP3 or Ogg file cut between two frames decodes cleanly and is simply shorter; the reviewer hears that. Recordings under `LKD_MIN_AUDIO_SECONDS` are not rejected here: `audio.analyze` flags them `too_short` (§3.5).

### 3.4 Promotion

Copy quarantine object → `originals/{yyyy}/{mm}/{recording_id}/original.{ext}` (the API stores the upload under the same key in quarantine, so `recordings.original_object_key` is set once at upload); re-hash the stored object; on match, set `upload_status = promoted` in the same transaction that inserts the `processing_runs` result. Object keys never contain names or client filenames.

### 3.5 Analysis (`audio.analyze`)

```bash
ffmpeg -hide_banner -nostats -i original -map 0:a:0 \
  -af "silencedetect=noise=-50dB:d=0.5,astats=metadata=0:measure_perchannel=none,ebur128=peak=true" \
  -f null -
```

Parsed into `recordings.quality_metrics`:

| Metric | Source | Flag rule (initial, tune in pilot) |
|--------|--------|-----------------------------------|
| `peak_dbfs` | astats Peak level | — |
| `rms_dbfs` | astats RMS level | `very_quiet` if < −45 dBFS |
| `integrated_lufs`, `true_peak_dbtp` | ebur128 summary | — |
| `clipping_ratio` | astats (samples at full scale / total) or peak ≥ −0.1 dBFS count | `clipping` if > 0.1 % |
| `silence_ratio` | silencedetect total silence / duration | `silent` if > 95 % |
| `speech_ratio_vad` | Silero VAD (optional, advisory) | shown only, no automatic flag in MVP |
| `duration_ms` | full decode (`ffmpeg -f null`), not the ffprobe header: browser WebM files have no duration (Q-T1) | `too_short` if < 1 s |

Flags are **advisory** signals for reviewers; they never auto-reject in the MVP (except `silent` + `too_short` which warn the contributor before upload where detectable client-side).

As built (`backend/app/audio/quality.py`):

- The filters run in one pass over the original, which is downloaded and checked against `sha256_original` first. `astats` runs after `aformat=sample_fmts=s16`, so a lossy recording, which decodes to floating point and can go past full scale, saturates and its clipped samples can be counted.
- `clipping_ratio` is an estimate: `astats` "Peak count" divided by the number of samples, counted only when the peak reaches −0.1 dBFS. Lossy encoders smooth clipped peaks, so the ratio is lower for AAC and Opus than for the same sound in WAV (in tests, a heavily clipped tone gave about 0.7 as WAV and 0.01 as AAC); the 0.1 % threshold still flags both.
- `true_peak_dbtp` is the `ebur128` true peak. Values of minus infinity (digital silence) are stored as `null`, and a `null` RMS also counts as `very_quiet`.
- `too_short` uses `LKD_MIN_AUDIO_SECONDS` (default 1). The other thresholds are constants at the top of `quality.py`, to be tuned on pilot recordings: silence below −50 dB for at least 0.5 s, `silent` above 95 % silence, `very_quiet` below −45 dBFS RMS, `clipping` above 0.1 %.
- Re-running `audio.analyze` replaces its own four flags and keeps flags set by other jobs (`possible_duplicate`). Silero VAD (`speech_ratio_vad`) is not built.

### 3.6 Renditions (`audio.renditions`)

| Rendition | Purpose | Command (core) | Approx. size |
|-----------|---------|----------------|--------------|
| `analysis_flac_16k_mono` | Standard working format for research/ML: 16 kHz, mono, 16-bit, lossless FLAC of the resampled signal | `ffmpeg -i original -map 0:a:0 -ac 1 -ar 16000 -sample_fmt s16 -c:a flac out.flac` | ~1–1.3 MB/min |
| `playback_opus` | Low-bandwidth streaming for reviewers/researchers | `ffmpeg -i original -map 0:a:0 -ac 1 -c:a libopus -b:a 24k -application voip out.webm` | ~0.2 MB/min |
| `waveform_peaks` | Lightweight JSON peaks for the review UI (no audio download needed to draw waveform) | computed from the analysis rendition | few KB |

Notes:

- Downmix to mono uses FFmpeg's default channel averaging; the original keeps both channels. If stereo recordings contain different speakers per channel (rare), reviewers flag it and channel-specific renditions are a future feature.
- **Lossy sources stay lossy.** Converting an Opus or MP3 original to FLAC does not restore quality; `is_lossy_source` is exported so researchers can filter.
- No loudness normalisation is applied to the analysis rendition (keeps signal comparable to the original). The playback rendition may apply `loudnorm` for listening comfort; this is recorded in `params`.
- Opus playback on iOS Safari must be verified (Q-T2); AAC-LC 48 kbit/s M4A is the fallback rendition (`playback_aac`, allowed by the schema since migration `0006`).

As built (`backend/app/audio/renditions.py`):

- Every promoted recording gets all four: `analysis_flac_16k_mono`, `playback_opus` (WebM, 24 kbit/s), `playback_aac` (M4A, 48 kbit/s, made for every recording until Q-T2 is settled), and `waveform_peaks`. They are stored in the `derived` bucket next to the original's key, as `{yyyy}/{mm}/{recording_id}/{kind}-{first 16 characters of params_sha256}.{ext}`.
- `params` holds the exact FFmpeg output arguments and a format version; `params_sha256` is the hash of that JSON. A re-run skips kinds that already exist with the same hash, and a changed recipe adds a new rendition beside the old one (rows are append-only).
- Derived files never carry the original's tags or chapters (`-map_metadata -1 -map_chapters -1`), which can hold names, and are written with `-fflags +bitexact`, so the same original gives byte-identical files.
- The waveform is decoded to 16 kHz mono 16-bit samples and stored as `{"version": 1, "peaks_per_second": 20, "peaks": [...]}`, each peak a whole percentage of full scale (about 100 KB for a 30-minute recording).
- Each row records the FFmpeg version and the `processing_runs` row of the attempt that made it: the queue gives every attempt its run ID up front (`JobContext.run_id`).

### 3.7 Duplicate detection (`audio.dedupe`)

| Level | Method | Action |
|-------|--------|--------|
| Exact file | `sha256_original` equal | Flag `possible_duplicate`, link via `related_items`; tell contributor at upload time if the same user re-uploads. |
| Same audio, different container/encoding | `sha256_pcm`: SHA-256 of `ffmpeg -ac 1 -ar 16000 -f s16le` output | Flag. Valid only between recordings processed with the same FFmpeg version (recorded). |
| Near-duplicate (trimmed, re-recorded) | Chromaprint fingerprint — **experimental for speech** (Q-T5) | Flag only after evaluation shows acceptable precision. |

Duplicates are **never deleted automatically**; a reviewer decides.

As built (`backend/app/audio/duplicates.py`, `audio.dedupe`):

- `sha256_pcm` hashes the FFmpeg version line and the 16 kHz mono 16-bit samples, so fingerprints made by different FFmpeg versions never match. That can miss a duplicate after an upgrade but never invents one; re-fingerprinting old recordings after an upgrade is a later job.
- A match is any other promoted recording with the same `sha256_pcm` or the same `sha256_original`. Both recordings get `possible_duplicate`, and their submissions are linked once in `related_items` (`relation = possible_duplicate`, no `created_by`, the pair stored in ID order). At most 50 matches are linked per recording.
- A PostgreSQL advisory lock on the fingerprint makes two copies processed at the same moment find each other.
- Not built yet: telling the contributor at upload time that they sent the same file before, and Chromaprint near-duplicates (Q-T5).

### 3.8 Processing logs and failure recovery

- Each job attempt writes a `processing_runs` row: job type, target, attempt number, start/end, worker ID, tool versions (`ffmpeg -version` first line, Python package versions), input checksum, outcome, sanitised error.
- Retries: exponential backoff (e.g., 1 min, 5 min, 30 min); max 3 attempts for deterministic failures (decode errors don't retry — they reject), 5 for infrastructure failures (storage timeout).
- After max attempts: job `dead`, submission `processing_failed`, admin dashboard shows it. Re-queue is idempotent: renditions are keyed by `(recording_id, kind, params_sha256)` and overwritten only in `derived/`, never in `originals/`.
- Worker crash mid-job: the job lock expires; the job is retried; partial derived files are written to a temp key and renamed only on success.
- Temporary files live in a per-job temp directory deleted in a `finally` block; the container has a size-limited tmpfs.

As built (M4):

- A job that runs out of attempts, or fails in a way a retry cannot fix, is marked `failed` (the plan's "dead").
- Whenever a job succeeds, fails for good, or is re-queued by an admin, the submission it belongs to is updated in the same transaction (`follow_processing` in `app/modules/submissions/service.py`). Only the latest job of each type for the submission and its recording counts, and `cleanup.quarantine` is ignored because it does not change whether the submission can be accepted:
  - any failed → `processing_failed`;
  - otherwise any queued or running → `processing`;
  - otherwise → `accepted` (migration `0010`; there is no human reviewer, ADR-021).
- A submission already decided by validation (`rejected_invalid`) is left alone.
- Admins see failed jobs on the app's **Failed checks** page (`/admin/jobs`) and can run each one again.
- If updating the submission fails, the job counts as failed with `unexpected_error` and is retried, so a finished check is never lost.
- A draft's upload that waits in quarantine for 30 days (`LKD_DRAFT_UPLOAD_RETENTION_DAYS`, Q-T7) is deleted by `cleanup.expire_drafts` (`app/modules/submissions/expiry.py`), and the recording becomes `expired`. Workers queue this job every hour between jobs (`app/modules/processing/schedule.py`). Uploading the same file again with the same `Idempotency-Key` restores the recording; the app does that by itself when the server answers `recording_expired`.

## 4. Client-side (browser) responsibilities

- Prefer `MediaRecorder` with `audio/webm;codecs=opus`, falling back to `audio/mp4` (Safari) via `MediaRecorder.isTypeSupported()`; record which was used.
- Show a live level meter and a "too quiet" hint; warn on recordings under 1 s. *(M3 shows a timer and the under-1 s warning; the level meter is not built yet.)*
- Save the recorded Blob to IndexedDB **before** upload starts.
- Do **not** transcode in the browser (battery, CPU on low-end phones, and loss of the true original).

## 5. Security notes

- FFmpeg parses untrusted input: run the worker as a non-root user in a container with no network access except to the database and object store, CPU/memory/time limits per job (`timeout` + cgroup limits), and keep FFmpeg patched.
- Never pass user-controlled strings into FFmpeg command lines; use argument arrays, never shell strings.
- Restrict FFmpeg protocols when reading local files (`-protocol_whitelist file`) so crafted playlists cannot fetch remote URLs.
