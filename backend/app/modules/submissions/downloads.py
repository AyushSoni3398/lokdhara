"""Contributors save copies of their own recordings to their device (ADR-026).

They get the listening copy they can already play, never the original, which stays admin-only
(docs/ACCESS_CONTROL.md §2). AAC comes first because every phone's music app plays `.m4a`.
Only recordings the user sent themselves count, and not ones an admin has hidden after a report.
"""

import tempfile
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.audio import renditions
from app.errors import ApiError
from app.modules.identity.service import AuthenticatedUser
from app.modules.submissions.models import Recording, Rendition, Submission
from app.object_store import Bucket, ObjectNotFound, ObjectStore
from app.object_store.base import CHUNK_SIZE

DOWNLOAD_KINDS = (renditions.PLAYBACK_AAC, renditions.PLAYBACK_OPUS)
# A zip is built on disk once it outgrows this much memory.
_SPOOL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class DownloadFile:
    object_key: str
    content_type: str
    name: str


def _downloadable(user: AuthenticatedUser) -> ColumnElement[bool]:
    return and_(
        Submission.submitted_by == user.id,
        Submission.status != "withdrawn",
        func.cardinality(Submission.restriction_flags) == 0,
    )


def file_name(submission: Submission, recording: Recording, kind: renditions.Kind) -> str:
    """No titles or names, which may hold personal details: the day it was recorded and the
    random end of the recording's ID, e.g. lokdhara-2026-10-12-3f9a0c21.m4a."""
    day = submission.recorded_on or (submission.submitted_at or submission.created_at).date()
    return f"lokdhara-{day.isoformat()}-{str(recording.id)[-8:]}.{kind.extension}"


def _files(db: Session, pairs: list[tuple[Recording, Submission]]) -> list[DownloadFile]:
    """The preferred listening copy of each recording; recordings without one are skipped."""
    if not pairs:
        return []
    latest = db.scalars(
        select(Rendition)
        .where(
            Rendition.recording_id.in_([recording.id for recording, _ in pairs]),
            Rendition.kind.in_([kind.name for kind in DOWNLOAD_KINDS]),
        )
        .ext(distinct_on(Rendition.recording_id, Rendition.kind))
        .order_by(Rendition.recording_id, Rendition.kind, Rendition.created_at.desc())
    )
    by_recording: dict[tuple[uuid.UUID, str], Rendition] = {
        (r.recording_id, r.kind): r for r in latest
    }
    files = []
    for recording, submission in pairs:
        for kind in DOWNLOAD_KINDS:
            rendition = by_recording.get((recording.id, kind.name))
            if rendition is not None:
                name = file_name(submission, recording, kind)
                files.append(DownloadFile(rendition.object_key, kind.content_type, name))
                break
    return files


def own_file(db: Session, user: AuthenticatedUser, recording_id: uuid.UUID) -> DownloadFile:
    row = db.execute(
        select(Recording, Submission)
        .join(Submission, Submission.id == Recording.submission_id)
        .where(Recording.id == recording_id, _downloadable(user))
    ).first()
    if row is None:
        # Same answer whether it does not exist or is someone else's.
        raise ApiError(404, "recording_not_found", "Recording not found.")
    files = _files(db, [(row[0], row[1])])
    if not files:
        raise ApiError(
            409, "download_not_ready", "This recording is still being prepared. Try again later."
        )
    return files[0]


def own_files(db: Session, user: AuthenticatedUser) -> list[DownloadFile]:
    """Oldest first."""
    rows = db.execute(
        select(Recording, Submission)
        .join(Submission, Submission.id == Recording.submission_id)
        .where(_downloadable(user))
        .order_by(Recording.created_at)
    ).all()
    return _files(db, [(recording, submission) for recording, submission in rows])


def write_zip(store: ObjectStore, files: list[DownloadFile], target: IO[bytes]) -> int:
    """Writes the files into a zip without compressing them again (audio is already
    compressed). Returns how many were added; a file deleted meanwhile is left out."""
    added = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for file in files:
            try:
                chunks = store.open(Bucket.DERIVED, file.object_key)
                first = next(chunks, b"")
            except ObjectNotFound:
                continue
            with archive.open(file.name, "w", force_zip64=True) as entry:
                entry.write(first)
                for chunk in chunks:
                    entry.write(chunk)
            added += 1
    return added


def zip_chunks(store: ObjectStore, files: list[DownloadFile]) -> Iterator[bytes]:
    """The zip's bytes, built when the response starts."""
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES) as spool:
        write_zip(store, files, spool)
        spool.seek(0)
        while chunk := spool.read(CHUNK_SIZE):
            yield chunk
