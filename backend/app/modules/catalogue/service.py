"""Searching the catalogue. Which items are listed is decided only by
app.modules.consents.access.catalogue_filter (ADR-012)."""

import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.consents.access import catalogue_filter, viewer_for
from app.modules.identity.service import AuthenticatedUser
from app.modules.submissions.models import Recording, Submission, TextLayer, TextRevision

MAX_PAGE = 100
PREVIEW_LENGTH = 200


@dataclass(frozen=True)
class Filters:
    q: str | None = None
    kind: str | None = None
    content_type: str | None = None
    recording_mode: str | None = None
    dialect_label: str | None = None


@dataclass(frozen=True)
class Entry:
    submission: Submission
    recording: Recording | None
    text: TextRevision | None
    text_script: str | None


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search(
    db: Session,
    user: AuthenticatedUser,
    filters: Filters,
    *,
    limit: int,
    cursor: uuid.UUID | None,
) -> tuple[list[Entry], uuid.UUID | None]:
    viewer = viewer_for(user)
    if not (viewer.is_admin or viewer.is_researcher):
        raise ApiError(403, "forbidden", "You do not have permission for this action.")
    query = select(Submission).where(catalogue_filter(viewer)).order_by(Submission.id.desc())
    if filters.q:
        pattern = _like(unicodedata.normalize("NFC", filters.q.strip()))
        matching_text = (
            select(TextLayer.submission_id)
            .join(TextRevision, TextRevision.id == TextLayer.current_revision_id)
            .where(TextRevision.content_nfc.ilike(pattern, escape="\\"))
        )
        query = query.where(
            or_(Submission.title.ilike(pattern, escape="\\"), Submission.id.in_(matching_text))
        )
    for column, value in (
        (Submission.kind, filters.kind),
        (Submission.content_type, filters.content_type),
        (Submission.recording_mode, filters.recording_mode),
        (Submission.dialect_label, filters.dialect_label),
    ):
        if value is not None:
            query = query.where(column == value)
    if cursor is not None:
        query = query.where(Submission.id < cursor)
    rows = list(db.scalars(query.limit(limit + 1)))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return _entries(db, rows[:limit]), next_cursor


def _entries(db: Session, rows: list[Submission]) -> list[Entry]:
    ids = [row.id for row in rows]
    recordings: dict[uuid.UUID, Recording] = {}
    for recording in db.scalars(
        select(Recording)
        .where(Recording.submission_id.in_(ids), Recording.upload_status == "promoted")
        .order_by(Recording.created_at)
    ):
        recordings.setdefault(recording.submission_id, recording)
    # The first transcription or standalone text of each item; translations are not previews.
    texts: dict[uuid.UUID, tuple[TextRevision, str]] = {}
    for layer, revision in db.execute(
        select(TextLayer, TextRevision)
        .join(TextRevision, TextRevision.id == TextLayer.current_revision_id)
        .where(TextLayer.submission_id.in_(ids), TextLayer.layer_type != "translation")
        .order_by(TextLayer.created_at)
    ).all():
        texts.setdefault(layer.submission_id, (revision, layer.script_code))
    entries = []
    for row in rows:
        text, script = texts.get(row.id, (None, None))
        entries.append(Entry(row, recordings.get(row.id), text, script))
    return entries


def preview(text: TextRevision | None) -> str | None:
    if text is None:
        return None
    content = text.content_original
    return content if len(content) <= PREVIEW_LENGTH else content[: PREVIEW_LENGTH - 1] + "…"
