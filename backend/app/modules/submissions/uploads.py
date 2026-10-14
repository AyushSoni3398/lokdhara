"""Recording uploads into quarantine (docs/SYSTEM_ARCHITECTURE.md §4.1).

The API only checks the first bytes and the size, and records the checksum. The full decode
happens later in the isolated worker (M4), which promotes the file to originals. The object key
is chosen once and used in both buckets, so `original_object_key` never has to change: while
`upload_status` is `quarantined` the bytes are in the quarantine bucket, after promotion in
originals. Keys contain only the date, the recording ID, and a fixed name (ADR-009).

A draft left unsent for 30 days loses its quarantine copy (`expired`, app.modules.submissions.
expiry). Uploading the same file again with the same Idempotency-Key puts it back under the same
key, so the recording and any transcription linked to it stay as they were.
"""

import re
import uuid
from datetime import timedelta
from pathlib import PurePath, PurePosixPath
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audio_formats import CONTENT_TYPES, SNIFF_BYTES, sniff_audio_container
from app.config import Settings
from app.errors import ApiError
from app.modules.consents import service as consents
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.speakers import service as speakers
from app.modules.submissions import service
from app.modules.submissions.models import Recording, Submission
from app.object_store import Bucket, ObjectStore, ObjectTooLarge, new_key

_EXTENSION = re.compile(r"^\.[a-z0-9]{1,8}$")


def _existing(db: Session, submission_id: uuid.UUID, upload_key: uuid.UUID) -> Recording | None:
    return db.scalar(
        select(Recording).where(
            Recording.submission_id == submission_id, Recording.upload_key == upload_key
        )
    )


def _check_accepts_audio(db: Session, submission: Submission) -> None:
    if submission.status != "draft":
        raise ApiError(409, "submission_not_draft", "Recordings can only be added to drafts.")
    if submission.kind not in service.AUDIO_KINDS:
        raise ApiError(422, "recording_not_expected", "This submission is text only.")
    if service.recordings_of(db, submission.id):
        # One recording per submission in the MVP; a retake is recorded again on the device
        # before uploading, and a second part is a separate, linked submission.
        raise ApiError(409, "recording_exists", "This submission already has its recording.")


def _needs_restore(store: ObjectStore, submission: Submission, recording: Recording) -> bool:
    if submission.status != "draft":
        return False
    if recording.upload_status == "expired":
        return True
    # A sweep whose database commit failed after deleting the file leaves it `quarantined`.
    return (
        recording.upload_status == "quarantined"
        and store.head(Bucket.QUARANTINE, recording.original_object_key) is None
    )


def _check_rate(db: Session, settings: Settings, user: AuthenticatedUser) -> None:
    window = timedelta(hours=1)
    since = utcnow() - window
    count, oldest = db.execute(
        select(func.count(), func.min(Recording.created_at))
        .join(Submission, Submission.id == Recording.submission_id)
        .where(Submission.submitted_by == user.id, Recording.created_at > since)
    ).one()
    if count >= settings.uploads_per_user_per_hour:
        retry_after = max(1, int((oldest + window - utcnow()).total_seconds()))
        raise ApiError(
            429,
            "upload_rate_limited",
            "Too many uploads in the last hour. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _client_extension(filename: str | None) -> str | None:
    """Kept for diagnostics only; the client's filename itself may contain names."""
    suffix = PurePath(filename or "").suffix.lower()
    return suffix if _EXTENSION.fullmatch(suffix) else None


def upload_recording(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    user: AuthenticatedUser,
    submission_id: uuid.UUID,
    upload_key: uuid.UUID,
    stream: BinaryIO,
    filename: str | None,
    device_hint: str | None,
) -> Recording:
    submission = service.get_owned(db, user, submission_id)
    replay = _existing(db, submission.id, upload_key)
    if replay is not None and not _needs_restore(store, submission, replay):
        return replay
    if replay is None:
        _check_accepts_audio(db, submission)
    speakers.get_for_action(db, user, submission.speaker_id)
    if consents.active_consent(db, submission.speaker_id) is None:
        raise service.consent_required()
    _check_rate(db, settings, user)
    if replay is not None:
        return _restore(db, store, settings, user=user, recording=replay, stream=stream)

    container = sniff_audio_container(stream.read(SNIFF_BYTES))
    if container is None:
        raise ApiError(415, "bad_signature", "This file is not a supported audio format.")
    stream.seek(0)
    recording_id: uuid.UUID = db.execute(select(func.uuidv7())).scalar_one()
    now = utcnow()
    key = new_key(f"{now:%Y}", f"{now:%m}", recording_id, "original", suffix=f".{container}")
    # End the read transaction: storing a large file must not hold a database connection open.
    db.rollback()
    try:
        stored = store.put(
            Bucket.QUARANTINE,
            key,
            stream,
            content_type=CONTENT_TYPES[container],
            max_bytes=settings.max_upload_bytes,
        )
    except ObjectTooLarge as exc:
        raise ApiError(413, "too_large", "The recording is larger than allowed.") from exc

    try:
        # Check again under the submission's lock: it may have changed during the upload.
        submission = service.get_owned(db, user, submission_id, for_update=True)
        replay = _existing(db, submission.id, upload_key)
        if replay is not None:
            store.delete(Bucket.QUARANTINE, key)
            return replay
        _check_accepts_audio(db, submission)
        recording = Recording(
            id=recording_id,
            submission_id=submission.id,
            original_object_key=key,
            original_filename_ext=_client_extension(filename),
            sha256_original=stored.sha256,
            size_bytes=stored.size_bytes,
            upload_status="quarantined",
            recorded_device_hint=device_hint,
            upload_key=upload_key,
        )
        db.add(recording)
        submission.updated_at = utcnow()
        db.commit()
    except BaseException:
        db.rollback()
        # Never keep audio that no recording row points to.
        store.delete(Bucket.QUARANTINE, key)
        raise
    return recording


def _restore(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    user: AuthenticatedUser,
    recording: Recording,
    stream: BinaryIO,
) -> Recording:
    """Puts the same file back for a draft whose quarantine copy expired."""
    recording_id, submission_id = recording.id, recording.submission_id
    key, sha256 = recording.original_object_key, recording.sha256_original
    content_type = CONTENT_TYPES[PurePosixPath(key).suffix.removeprefix(".")]
    db.rollback()  # as above: no database connection held while storing
    try:
        stored = store.put(
            Bucket.QUARANTINE,
            key,
            stream,
            content_type=content_type,
            max_bytes=settings.max_upload_bytes,
        )
    except ObjectTooLarge as exc:
        raise ApiError(413, "too_large", "The recording is larger than allowed.") from exc
    if stored.sha256 != sha256:
        store.delete(Bucket.QUARANTINE, key)
        raise ApiError(
            409, "recording_changed", "This is not the recording uploaded to this draft before."
        )

    submission = service.get_owned(db, user, submission_id, for_update=True)
    restored = db.scalar(select(Recording).where(Recording.id == recording_id).with_for_update())
    if restored is None:  # erased meanwhile (withdrawal): the bytes must not stay either
        store.delete(Bucket.QUARANTINE, key)
        raise ApiError(404, "recording_not_found", "Recording not found.")
    if submission.status == "draft" and restored.upload_status in ("expired", "quarantined"):
        restored.upload_status = "quarantined"
        restored.quarantined_at = submission.updated_at = utcnow()
    db.commit()
    return restored
