import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.submissions.schemas import ContentType, Kind, RecordingMode
from app.text_input import MultiLine, SingleLine

Purpose = Literal["internal_research", "external_research", "public", "ai_training"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
DialectLabel = Annotated[SingleLine, Field(max_length=100)]


class SelectionCriteria(BaseModel):
    """Which eligible items a release takes. Empty lists mean "any"."""

    model_config = ConfigDict(extra="forbid")

    kinds: list[Kind] = Field(default_factory=list, max_length=3)
    content_types: list[ContentType] = Field(default_factory=list, max_length=6)
    recording_modes: list[RecordingMode] = Field(default_factory=list, max_length=3)
    dialect_labels: list[DialectLabel] = Field(default_factory=list, max_length=50)
    needs_audio: bool = False
    needs_transcription: bool = False


class ReleaseCreateRequest(BaseModel):
    slug: Slug
    purpose: Purpose
    selection_criteria: SelectionCriteria = Field(default_factory=SelectionCriteria)
    licence: SingleLine | None = Field(default=None, max_length=200)
    data_card_markdown: MultiLine | None = Field(default=None, max_length=50000)


class ReleaseUpdateRequest(BaseModel):
    """Drafts only. Fields left out stay as they are."""

    purpose: Purpose | None = None
    selection_criteria: SelectionCriteria | None = None
    licence: SingleLine | None = Field(default=None, max_length=200)
    data_card_markdown: MultiLine | None = Field(default=None, max_length=50000)


class ReleaseOut(BaseModel):
    id: uuid.UUID
    slug: str
    version: str | None
    purpose: Purpose
    selection_criteria: SelectionCriteria
    status: Literal["draft", "frozen", "retracted"]
    licence: str | None
    data_card_markdown: str
    manifest_sha256: str | None
    created_at: datetime
    updated_at: datetime
    frozen_at: datetime | None
    retracted_at: datetime | None
    retraction_note: str | None


class ReleaseListOut(BaseModel):
    items: list[ReleaseOut]


class SampleItem(BaseModel):
    id: uuid.UUID
    title: str | None
    content_type: ContentType
    duration_ms: int | None


class PreviewOut(BaseModel):
    """What freezing now would take. Consent is checked again at freeze time."""

    item_count: int
    total_duration_ms: int
    # Accepted items matching the criteria that consent or a restriction keeps out.
    left_out_count: int
    by_content_type: dict[str, int]
    by_dialect_label: dict[str, int]
    by_kind: dict[str, int]
    sample: list[SampleItem]
