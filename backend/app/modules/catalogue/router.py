"""Researcher catalogue (docs/API_SPECIFICATION.md §8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.db import DbSession
from app.modules.catalogue import service
from app.modules.catalogue.schemas import CatalogueItemOut, CatalogueListOut
from app.modules.identity.deps import CurrentUser
from app.modules.submissions.schemas import ContentType, Kind, RecordingMode

router = APIRouter(tags=["catalogue"])


def _item(entry: service.Entry) -> CatalogueItemOut:
    submission, recording = entry.submission, entry.recording
    return CatalogueItemOut(
        id=submission.id,
        title=submission.title,
        kind=submission.kind,
        content_type=submission.content_type,
        recording_mode=submission.recording_mode,
        language_tag=submission.language_tag,
        dialect_label=submission.dialect_label,
        region_coarse=submission.region_coarse,
        submitted_at=submission.submitted_at,
        restriction_flags=submission.restriction_flags,
        duration_ms=recording.duration_ms if recording else None,
        quality_flags=recording.quality_flags if recording else [],
        text_preview=service.preview(entry.text),
        text_script=entry.text_script,
    )


@router.get("/catalogue")
def search_catalogue(
    user: CurrentUser,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=200)] = None,
    kind: Kind | None = None,
    content_type: ContentType | None = None,
    recording_mode: RecordingMode | None = None,
    dialect: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE)] = 50,
    cursor: uuid.UUID | None = None,
) -> CatalogueListOut:
    filters = service.Filters(
        q=q or None,
        kind=kind,
        content_type=content_type,
        recording_mode=recording_mode,
        dialect_label=dialect or None,
    )
    entries, next_cursor = service.search(db, user, filters, limit=limit, cursor=cursor)
    return CatalogueListOut(
        items=[_item(entry) for entry in entries],
        next_cursor=str(next_cursor) if next_cursor else None,
    )
