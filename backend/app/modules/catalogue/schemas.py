import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.submissions.schemas import ContentType, Kind, RecordingMode, Restriction


class CatalogueItemOut(BaseModel):
    id: uuid.UUID
    title: str | None
    kind: Kind
    content_type: ContentType
    recording_mode: RecordingMode | None
    language_tag: str
    dialect_label: str | None
    region_coarse: str | None
    submitted_at: datetime | None
    # Only `culturally_restricted` can show here; other flags keep an item out of the list.
    restriction_flags: list[Restriction]
    duration_ms: int | None
    quality_flags: list[str]
    text_preview: str | None
    text_script: str | None
    # Contributors' text is never checked by a reviewer (ADR-021).
    text_status: Literal["unverified"] = "unverified"


class CatalogueListOut(BaseModel):
    items: list[CatalogueItemOut]
    next_cursor: str | None
