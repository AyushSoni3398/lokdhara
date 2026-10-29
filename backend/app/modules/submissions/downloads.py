"""Contributors save copies of their own recordings to their device (ADR-026).

They get the listening copy they can already play, never the original, which stays admin-only
(docs/ACCESS_CONTROL.md §2). AAC comes first because every phone's music app plays `.m4a`.
Only recordings the user sent themselves count, and not ones an admin has hidden after a report.
The zip of all of them also holds details.csv, which says what each file is (ADR-029).
"""

import csv
import io
import tempfile
import uuid
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, Any

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.audio import renditions
from app.errors import ApiError
from app.modules.identity.service import AuthenticatedUser
from app.modules.prompts.models import Prompt
from app.modules.releases.package import csv_cell
from app.modules.submissions.models import (
    Recording,
    Rendition,
    Submission,
    TextLayer,
    TextRevision,
)
from app.object_store import Bucket, ObjectNotFound, ObjectStore
from app.object_store.base import CHUNK_SIZE

DOWNLOAD_KINDS = (renditions.PLAYBACK_AAC, renditions.PLAYBACK_OPUS)
# A zip is built on disk once it outgrows this much memory.
_SPOOL_BYTES = 8 * 1024 * 1024


DETAIL_COLUMNS = (
    "file",
    "recorded_on",
    "title",
    "content_type",
    "recording_mode",
    "prompt",
    "dialect_label",
    "area",
    "duration_seconds",
    "status",
    "transcription",
    "translations",
)


@dataclass(frozen=True)
class DownloadFile:
    object_key: str
    content_type: str
    name: str
    # DETAIL_COLUMNS other than `file`.
    details: dict[str, Any] = field(default_factory=dict)


def _downloadable(user: AuthenticatedUser) -> ColumnElement[bool]:
    return and_(
        Submission.submitted_by == user.id,
        Submission.status != "withdrawn",
        func.cardinality(Submission.restriction_flags) == 0,
    )


def file_name(submission: Submission, recording: Recording, kind: renditions.Kind) -> str:
    """No titles or names, which may hold personal details: the day it was recorded, how and
    what (fixed words), and the random end of the recording's ID, e.g.
    lokdhara-2026-10-12-read-story-3f9a0c21.m4a."""
    day = submission.recorded_on or (submission.submitted_at or submission.created_at).date()
    parts = [day.isoformat(), submission.recording_mode, submission.content_type]
    words = "-".join(part.replace("_", "-") for part in parts if part)
    return f"lokdhara-{words}-{str(recording.id)[-8:]}.{kind.extension}"


def _details(db: Session, submissions: list[Submission]) -> dict[uuid.UUID, dict[str, Any]]:
    ids = [s.id for s in submissions]
    texts: dict[uuid.UUID, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for layer, revision in db.execute(
        select(TextLayer, TextRevision)
        .join(TextRevision, TextRevision.id == TextLayer.current_revision_id)
        .where(TextLayer.submission_id.in_(ids))
        .order_by(TextLayer.created_at, TextLayer.id)
    ):
        text = revision.content_original
        if layer.layer_type == "translation":
            text = f"{layer.language_tag}: {text}"
        texts[layer.submission_id][layer.layer_type].append(text)
    prompt_ids = {s.prompt_id for s in submissions if s.prompt_id}
    prompts = {
        prompt_id: text
        for prompt_id, text in db.execute(
            select(Prompt.id, Prompt.text).where(Prompt.id.in_(prompt_ids))
        )
    }
    return {
        s.id: {
            "recorded_on": s.recorded_on,
            "title": s.title,
            "content_type": s.content_type,
            "recording_mode": s.recording_mode,
            "prompt": prompts.get(s.prompt_id) if s.prompt_id else None,
            "dialect_label": s.dialect_label,
            "area": s.region_coarse,
            "status": s.status,
            "transcription": " | ".join(texts[s.id]["transcription"]),
            "translations": " | ".join(texts[s.id]["translation"]),
        }
        for s in submissions
    }


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
    details = _details(db, [submission for _, submission in pairs])
    files = []
    for recording, submission in pairs:
        for kind in DOWNLOAD_KINDS:
            rendition = by_recording.get((recording.id, kind.name))
            if rendition is not None:
                name = file_name(submission, recording, kind)
                duration = recording.duration_ms
                about = details[submission.id] | {
                    "duration_seconds": round(duration / 1000, 1) if duration else None
                }
                files.append(DownloadFile(rendition.object_key, kind.content_type, name, about))
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
    compressed), then details.csv about them. Returns how many were added; a file deleted
    meanwhile is left out."""
    added: list[DownloadFile] = []
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
            added.append(file)
        if added:
            archive.writestr("details.csv", details_csv(added), zipfile.ZIP_DEFLATED)
    return len(added)


def details_csv(files: list[DownloadFile]) -> bytes:
    """What each file in the zip is, for a spreadsheet; UTF-8 with a byte order mark."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(DETAIL_COLUMNS)
    for file in files:
        values = file.details | {"file": file.name}
        writer.writerow([csv_cell(_text(values.get(column))) for column in DETAIL_COLUMNS])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def _text(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def zip_chunks(store: ObjectStore, files: list[DownloadFile]) -> Iterator[bytes]:
    """The zip's bytes, built when the response starts."""
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES) as spool:
        write_zip(store, files, spool)
        spool.seek(0)
        while chunk := spool.read(CHUNK_SIZE):
            yield chunk
