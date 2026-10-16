"""Worker jobs for recordings (docs/AUDIO_PROCESSING_PIPELINE.md §3, docs/DATA_LIFECYCLE.md).

`audio.validate` downloads the quarantined upload to a private temporary folder, probes and
fully decodes it, and then either promotes it to originals (a verified byte-for-byte copy under
the same key, ADR-009) or rejects it with a code. `cleanup.quarantine` then removes the
quarantine copy, `audio.analyze` measures a promoted original and flags it for reviewers, and
`audio.renditions` makes the derived listening and research copies, and `audio.dedupe` links
recordings that are the same file or the same sound.
No database transaction stays open while files are copied, decoded, or measured.

A recording the speaker withdrew is `erased` by app.modules.withdrawals.erasure. These jobs then
skip it, and a file one of them made while the routine ran is deleted again.
"""

import hashlib
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audio import duplicates, ffmpeg, quality, renditions
from app.audio.validation import AudioInfo, Limits, Rejection, check_decode, check_probe
from app.config import Settings, get_settings
from app.modules.processing import queue
from app.modules.processing.queue import JobContext, JobError, JobResult, handler, utcnow
from app.modules.submissions.models import Recording, RelatedItem, Rendition, Submission
from app.object_store import (
    Bucket,
    IntegrityError,
    ObjectExists,
    ObjectNotFound,
    ObjectStore,
    get_object_store,
)

ERASED = "erased"


def limits(settings: Settings) -> Limits:
    return Limits(
        max_seconds=settings.max_audio_seconds,
        max_channels=settings.max_audio_channels,
        min_sample_rate_hz=settings.min_sample_rate_hz,
        max_sample_rate_hz=settings.max_sample_rate_hz,
    )


def _recording(db: Session, recording_id: uuid.UUID | None, *, lock: bool = False) -> Recording:
    query = select(Recording).where(Recording.id == recording_id)
    recording = db.scalar(query.with_for_update() if lock else query)
    if recording is None:
        raise JobError("recording_not_found", retryable=False)
    return recording


def _container(key: str) -> str:
    container = PurePosixPath(key).suffix.lstrip(".")
    if container not in ffmpeg.DEMUXERS:
        raise JobError("unknown_container", retryable=False)
    return container


def _download(store: ObjectStore, bucket: Bucket, key: str, sha256: str, path: Path) -> None:
    """Copies a stored recording to `path`, proving it is exactly the file that was uploaded."""
    digest = hashlib.sha256()
    try:
        with path.open("wb") as file:
            for chunk in store.open(bucket, key):
                digest.update(chunk)
                file.write(chunk)
    except ObjectNotFound as exc:
        raise JobError(f"{bucket.value}_missing", retryable=False) from exc
    if digest.hexdigest() != sha256:
        raise JobError("checksum_mismatch", retryable=False)


def _inspect(
    path: Path, container: str, settings: Settings
) -> tuple[ffmpeg.Probe | None, AudioInfo | Rejection, int | None]:
    timeout = settings.ffmpeg_timeout_seconds
    try:
        found = ffmpeg.probe(path, container, timeout=timeout)
        verdict = check_probe(found, limits(settings))
        if isinstance(verdict, Rejection):
            return found, verdict, None
        decoded = ffmpeg.decode(
            path, container, timeout=timeout, max_seconds=settings.max_audio_seconds
        )
    except ffmpeg.FfmpegTimeout as exc:
        # Deterministic for this file, so retrying would only repeat it; an admin can retry.
        raise JobError("ffmpeg_timeout", retryable=False) from exc
    return found, check_decode(decoded, limits(settings)) or verdict, decoded.duration_ms


def _promote(store: ObjectStore, key: str, sha256: str) -> None:
    try:
        store.copy_verified(Bucket.QUARANTINE, key, Bucket.ORIGINALS, key, sha256)
    except ObjectExists:
        # An earlier attempt copied it but did not finish; originals are never overwritten.
        if store.sha256_of(Bucket.ORIGINALS, key) != sha256:
            raise JobError("original_mismatch", retryable=False) from None
    except IntegrityError as exc:
        raise JobError("copy_mismatch") from exc


@handler("audio.validate")
def validate_recording(context: JobContext) -> JobResult:
    settings, store, db = get_settings(), get_object_store(), context.db
    recording = _recording(db, context.target_id)
    if recording.upload_status != "quarantined":  # already decided: re-running changes nothing
        return JobResult(output_summary={"skipped": recording.upload_status})
    key, sha256 = recording.original_object_key, recording.sha256_original
    container = _container(key)
    db.rollback()  # the slow part below must not hold a database connection

    with tempfile.TemporaryDirectory(prefix="lkd-job-") as folder:
        path = Path(folder) / "input"
        _download(store, Bucket.QUARANTINE, key, sha256, path)
        found, verdict, duration_ms = _inspect(path, container, settings)
    if isinstance(verdict, AudioInfo):
        _promote(store, key, sha256)

    recording = _recording(db, context.target_id, lock=True)
    if recording.upload_status != "quarantined":
        if recording.upload_status == ERASED and isinstance(verdict, AudioInfo):
            store.erase(Bucket.ORIGINALS, key)  # withdrawn meanwhile: keep no copy
        return JobResult(output_summary={"skipped": recording.upload_status})
    recording.detected_container = found.format_name if found else None
    recording.duration_ms = duration_ms
    summary: dict[str, Any]
    if isinstance(verdict, AudioInfo):
        recording.detected_codec = verdict.codec
        recording.sample_rate_hz = verdict.sample_rate_hz
        recording.channels = verdict.channels
        recording.bit_depth = verdict.bit_depth
        recording.is_lossy_source = verdict.is_lossy
        recording.upload_status = "promoted"
        summary = {"outcome": "promoted", "codec": verdict.codec, "duration_ms": duration_ms}
        for job_type in ("audio.analyze", "audio.renditions", "audio.dedupe"):
            queue.enqueue(
                db,
                job_type,
                target_type="recording",
                target_id=recording.id,
                dedupe_key=f"{job_type}:{recording.id}",
            )
    else:
        recording.upload_status = "rejected_invalid"
        recording.validation_errors = {"code": verdict.code, "reason": verdict.reason}
        submission = db.scalar(
            select(Submission).where(Submission.id == recording.submission_id).with_for_update()
        )
        if submission is not None and submission.status == "processing":
            submission.status = "rejected_invalid"
            submission.updated_at = utcnow()
        summary = {"outcome": "rejected", "code": verdict.code, "reason": verdict.reason}
    queue.enqueue(
        db,
        "cleanup.quarantine",
        target_type="recording",
        target_id=recording.id,
        dedupe_key=f"cleanup.quarantine:{recording.id}",
    )
    return JobResult(
        output_summary=summary,
        tool_versions=ffmpeg.versions(),
        input_sha256=sha256,
    )


@handler("cleanup.quarantine")
def remove_quarantine_copy(context: JobContext) -> JobResult:
    """Deletes a decided upload from quarantine. A promoted one only once originals has it."""
    store = get_object_store()
    recording = _recording(context.db, context.target_id)
    key = recording.original_object_key
    if recording.upload_status == "quarantined":
        return JobResult(output_summary={"skipped": "quarantined"})
    if recording.upload_status == "promoted" and store.head(Bucket.ORIGINALS, key) is None:
        raise JobError("original_missing", retryable=False)
    store.delete(Bucket.QUARANTINE, key)
    return JobResult(output_summary={"deleted": True})


@handler("audio.analyze")
def analyze_recording(context: JobContext) -> JobResult:
    """Measures the original and sets the reviewer flags. Re-running replaces both."""
    settings, store, db = get_settings(), get_object_store(), context.db
    recording = _recording(db, context.target_id)
    if recording.upload_status == ERASED:
        return JobResult(output_summary={"skipped": ERASED})
    if recording.upload_status != "promoted" or recording.duration_ms is None:
        raise JobError("not_promoted", retryable=False)
    key, sha256, duration_ms = (
        recording.original_object_key,
        recording.sha256_original,
        recording.duration_ms,
    )
    container = _container(key)
    db.rollback()

    with tempfile.TemporaryDirectory(prefix="lkd-job-") as folder:
        path = Path(folder) / "input"
        _download(store, Bucket.ORIGINALS, key, sha256, path)  # also proves it is unchanged
        try:
            log = ffmpeg.analysis_log(
                path, container, quality.FILTERS, timeout=settings.ffmpeg_timeout_seconds
            )
        except ffmpeg.FfmpegTimeout as exc:
            raise JobError("ffmpeg_timeout", retryable=False) from exc
        except ffmpeg.FfmpegFailed as exc:
            raise JobError("analysis_failed", retryable=False) from exc
    try:
        metrics = quality.parse(log, duration_ms)
    except ValueError as exc:
        raise JobError("analysis_unreadable", retryable=False) from exc
    found = quality.flags(metrics, duration_ms, settings.min_audio_seconds)

    recording = _recording(db, context.target_id, lock=True)
    if recording.upload_status == ERASED:
        return JobResult(output_summary={"skipped": ERASED})
    recording.quality_metrics = metrics.as_json()
    # Keep flags set by other jobs (possible_duplicate); replace this job's own.
    recording.quality_flags = sorted(
        (set(recording.quality_flags) - quality.ANALYSIS_FLAGS) | found
    )
    return JobResult(
        output_summary={"flags": sorted(found)},
        tool_versions=ffmpeg.versions(),
        input_sha256=sha256,
    )


def _store_file(store: ObjectStore, path: Path, key: str, content_type: str) -> tuple[str, int]:
    with path.open("rb") as file:
        stored = store.put(Bucket.DERIVED, key, file, content_type=content_type)
    return stored.sha256, stored.size_bytes


@handler("audio.renditions")
def make_renditions(context: JobContext) -> JobResult:
    """Makes the playback, analysis, and waveform files a recording does not have yet.

    Derived files are written under new keys and recorded as append-only rows; re-running
    skips kinds that already exist with the same parameters. The original is only read.
    """
    settings, store, db = get_settings(), get_object_store(), context.db
    recording = _recording(db, context.target_id)
    if recording.upload_status == ERASED:
        return JobResult(output_summary={"skipped": ERASED})
    if recording.upload_status != "promoted":
        raise JobError("not_promoted", retryable=False)
    key, sha256 = recording.original_object_key, recording.sha256_original
    container = _container(key)
    existing = {
        (kind, params_sha256)
        for kind, params_sha256 in db.execute(
            select(Rendition.kind, Rendition.params_sha256).where(
                Rendition.recording_id == recording.id
            )
        )
    }
    wanted = [
        kind
        for kind in (*renditions.AUDIO_KINDS, renditions.WAVEFORM)
        if (kind.name, kind.params_sha256) not in existing
    ]
    if not wanted:
        return JobResult(output_summary={"made": []})
    db.rollback()

    made: list[tuple[renditions.Kind, str, str, int]] = []
    timeout = settings.ffmpeg_timeout_seconds
    with tempfile.TemporaryDirectory(prefix="lkd-job-") as folder:
        source = Path(folder) / "input"
        _download(store, Bucket.ORIGINALS, key, sha256, source)
        for kind in wanted:
            out = Path(folder) / kind.name
            try:
                ffmpeg.convert(source, container, kind.output_args, out, timeout=timeout)
            except ffmpeg.FfmpegTimeout as exc:
                raise JobError("ffmpeg_timeout", retryable=False) from exc
            except ffmpeg.FfmpegFailed as exc:
                raise JobError("rendition_failed", kind.name, retryable=False) from exc
            if kind is renditions.WAVEFORM:
                out.write_bytes(renditions.waveform(out))
            derived = renditions.derived_key(key, kind)
            made.append((kind, derived, *_store_file(store, out, derived, kind.content_type)))

    if _recording(db, context.target_id, lock=True).upload_status == ERASED:
        for _kind, derived, *_ in made:  # withdrawn meanwhile: keep no copy
            store.erase(Bucket.DERIVED, derived)
        return JobResult(output_summary={"skipped": ERASED})
    versions = ffmpeg.versions()
    for kind, derived, file_sha256, size in made:
        # Added, not inserted at once: the run row it points to is written with the job's result.
        db.add(
            Rendition(
                recording_id=context.target_id,
                kind=kind.name,
                object_key=derived,
                sha256=file_sha256,
                size_bytes=size,
                params=kind.params,
                params_sha256=kind.params_sha256,
                tool_versions=versions,
                processing_run_id=context.run_id,
            )
        )
    return JobResult(
        output_summary={"made": [kind.name for kind, *_ in made]},
        tool_versions=versions,
        input_sha256=sha256,
    )


MAX_DUPLICATE_LINKS = 50


def _flag_duplicate(recording: Recording) -> None:
    if "possible_duplicate" not in recording.quality_flags:
        recording.quality_flags = sorted({*recording.quality_flags, "possible_duplicate"})


@handler("audio.dedupe")
def find_duplicates(context: JobContext) -> JobResult:
    """Flags this recording and earlier ones with the same file or the same sound, and links
    their submissions. Nothing is ever deleted: a reviewer decides (docs/DATA_LIFECYCLE.md)."""
    settings, store, db = get_settings(), get_object_store(), context.db
    recording = _recording(db, context.target_id)
    if recording.upload_status == ERASED:
        return JobResult(output_summary={"skipped": ERASED})
    if recording.upload_status != "promoted":
        raise JobError("not_promoted", retryable=False)
    recording_id, key, sha256 = (
        recording.id,
        recording.original_object_key,
        recording.sha256_original,
    )
    container = _container(key)
    db.rollback()

    version = ffmpeg.versions()["ffmpeg"]
    with tempfile.TemporaryDirectory(prefix="lkd-job-") as folder:
        source, pcm = Path(folder) / "input", Path(folder) / "pcm"
        _download(store, Bucket.ORIGINALS, key, sha256, source)
        try:
            ffmpeg.convert(
                source, container, duplicates.PCM_ARGS, pcm, timeout=settings.ffmpeg_timeout_seconds
            )
        except ffmpeg.FfmpegTimeout as exc:
            raise JobError("ffmpeg_timeout", retryable=False) from exc
        except ffmpeg.FfmpegFailed as exc:
            raise JobError("decode_failed", retryable=False) from exc
        sha256_pcm = duplicates.pcm_sha256(pcm, version)

    # Two copies processed at the same moment must still find each other: whoever runs second
    # waits here until the first has committed its fingerprint.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(sha256_pcm))))
    matches = db.scalars(
        select(Recording)
        .where(
            Recording.id != recording_id,
            Recording.upload_status == "promoted",
            or_(Recording.sha256_pcm == sha256_pcm, Recording.sha256_original == sha256),
        )
        .order_by(Recording.id)
        .limit(MAX_DUPLICATE_LINKS)
    ).all()
    # Lock all affected rows in ID order, so jobs touching the same rows cannot deadlock.
    ids = sorted([recording_id, *(match.id for match in matches)])
    locked = {
        row.id: row
        for row in db.scalars(
            select(Recording).where(Recording.id.in_(ids)).order_by(Recording.id).with_for_update()
        )
    }
    recording = locked[recording_id]
    recording.sha256_pcm = sha256_pcm
    same_file = 0
    for match in matches:
        _flag_duplicate(locked[match.id])
        same_file += match.sha256_original == sha256
        pair = sorted([recording.submission_id, match.submission_id])
        if pair[0] != pair[1]:
            db.execute(
                insert(RelatedItem)
                .values(submission_a=pair[0], submission_b=pair[1], relation="possible_duplicate")
                .on_conflict_do_nothing(constraint="uq_related_items_pair")
            )
    if matches:
        _flag_duplicate(recording)
    return JobResult(
        output_summary={"matches": len(matches), "same_file": same_file},
        tool_versions=ffmpeg.versions(),
        input_sha256=sha256,
    )
