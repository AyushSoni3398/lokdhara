import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.languages import LanguageTag, Script
from app.text.safety import LONGEST
from app.text_input import MultiLine, SingleLine

Kind = Literal["audio", "text", "audio_text"]
ContentType = Literal["story", "conversation", "vocabulary", "song", "sentence_list", "other"]
RecordingMode = Literal["free", "prompted", "read"]
CollectionMethod = Literal[
    "self_recorded", "facilitator_field", "facilitator_remote", "imported_archive"
]
SubmissionStatus = Literal[
    "draft",
    "uploading",
    "processing",
    "processing_failed",
    "rejected_invalid",
    "accepted",
    "awaiting_review",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
    "withdrawn",
]
Restriction = Literal[
    "sensitive", "third_party_voice", "contains_pii", "culturally_restricted", "minor"
]
DeviceHint = Literal["browser_recorder", "file_upload"]
LayerType = Literal["standalone", "transcription", "translation"]
EntryType = Literal["word", "phrase", "sentence", "paragraph", "long_text"]
# Kept exactly as sent; app.text.safety checks it and the entry type's limit in the service.
TextContent = Annotated[str, Field(max_length=LONGEST)]


class CollectionContext(BaseModel):
    """The allow-listed keys of docs/DATA_DICTIONARY.md §3; anything else is rejected."""

    model_config = ConfigDict(extra="forbid")

    setting: Literal["indoor_quiet", "indoor_noisy", "outdoor", "unknown"] | None = None
    speaker_count: int | None = Field(default=None, ge=1, le=50)
    equipment: (
        Literal["phone_builtin_mic", "phone_external_mic", "field_recorder", "unknown"] | None
    ) = None
    # Never exported: it may contain personal details.
    notes: MultiLine | None = Field(default=None, max_length=500)


def _not_in_future(value: date | None) -> None:
    # A day of slack: India is ahead of UTC, so "today" there can be tomorrow in UTC.
    if value is not None and value > datetime.now(UTC).date() + timedelta(days=1):
        raise ValueError("recorded_on cannot be in the future")


class SubmissionCreateRequest(BaseModel):
    """`client_submission_id` is generated on the device; sending it again returns the same
    draft, so a retry after a lost response never creates a second one."""

    client_submission_id: uuid.UUID
    speaker_id: uuid.UUID
    kind: Kind
    content_type: ContentType
    title: SingleLine | None = Field(default=None, max_length=200)
    language_tag: LanguageTag = "unr"
    dialect_label: SingleLine | None = Field(default=None, max_length=100)
    region_coarse: SingleLine | None = Field(default=None, max_length=100)
    recorded_on: date | None = None
    collection_method: CollectionMethod
    recording_mode: RecordingMode | None = None
    prompt_id: uuid.UUID | None = None
    collection_context: CollectionContext = Field(default_factory=CollectionContext)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.kind == "text") != (self.recording_mode is None):
            raise ValueError("recording_mode is required for audio, and only for audio")
        if (self.recording_mode in ("prompted", "read")) != (self.prompt_id is not None):
            raise ValueError("prompt_id is required for prompted and read speech, and only then")
        _not_in_future(self.recorded_on)
        return self


class SubmissionUpdateRequest(BaseModel):
    """Descriptive metadata only. What was recorded, of whom, and how is fixed at creation."""

    content_type: ContentType | None = None
    title: SingleLine | None = Field(default=None, max_length=200)
    dialect_label: SingleLine | None = Field(default=None, max_length=100)
    region_coarse: SingleLine | None = Field(default=None, max_length=100)
    recorded_on: date | None = None
    collection_context: CollectionContext | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if "content_type" in self.model_fields_set and self.content_type is None:
            raise ValueError("content_type cannot be removed")
        _not_in_future(self.recorded_on)
        return self


class RecordingOut(BaseModel):
    id: uuid.UUID
    upload_status: str
    size_bytes: int
    duration_ms: int | None
    quality_flags: list[str]
    # Why the checks refused the file (`rejected_invalid`), so the sender can fix it.
    rejection_reason: str | None = Field(default=None, validation_alias="validation_errors")
    created_at: datetime

    @field_validator("rejection_reason", mode="before")
    @classmethod
    def _reason(cls, value: object) -> object:
        return value.get("reason") if isinstance(value, dict) else value


class PlaybackSource(BaseModel):
    url: str
    content_type: str


class PlaybackOut(BaseModel):
    """Short-lived links; empty while the listening copies are still being made."""

    sources: list[PlaybackSource]


class TextLayerCreateRequest(BaseModel):
    """A text layer and its first revision. Standalone text needs an `entry_type`; a
    transcription names the `recording_id` it transcribes; a translation names the
    `source_layer_id` it translates (docs/TEXT_PROCESSING_PIPELINE.md §7)."""

    layer_type: LayerType
    recording_id: uuid.UUID | None = None
    source_layer_id: uuid.UUID | None = None
    entry_type: EntryType | None = None
    language_tag: LanguageTag
    script_code: Script
    content: TextContent

    @model_validator(mode="after")
    def _links(self) -> Self:
        expected = {
            "standalone": (False, False, True),
            "transcription": (True, False, False),
            "translation": (False, True, False),
        }[self.layer_type]
        given = (
            self.recording_id is not None,
            self.source_layer_id is not None,
            self.entry_type is not None,
        )
        if given != expected:
            raise ValueError(
                "standalone text needs entry_type, a transcription recording_id, and a "
                "translation source_layer_id, and nothing else"
            )
        return self


class RevisionCreateRequest(BaseModel):
    """`base_revision_id` is the revision the edit started from; if someone saved a newer one
    in the meantime the edit is refused with 409 instead of silently replacing theirs."""

    base_revision_id: uuid.UUID
    content: TextContent
    change_note: SingleLine | None = Field(default=None, max_length=500)


class RevisionOut(BaseModel):
    id: uuid.UUID
    revision_number: int
    content: str
    origin: str
    based_on_revision_id: uuid.UUID | None
    source_revision_id: uuid.UUID | None
    detected_scripts: list[str]
    uncertainty_markup: bool
    verification_status: str
    change_note: str | None
    created_at: datetime


class RevisionListOut(BaseModel):
    items: list[RevisionOut]


class DiffPart(BaseModel):
    op: Literal["equal", "delete", "insert"]
    text: str


class RevisionDiffOut(BaseModel):
    from_revision_id: uuid.UUID
    to_revision_id: uuid.UUID
    parts: list[DiffPart]


class TextLayerOut(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    layer_type: LayerType
    recording_id: uuid.UUID | None
    source_layer_id: uuid.UUID | None
    entry_type: EntryType | None
    language_tag: str
    script_code: str
    current_revision: RevisionOut | None
    # Translations only: the source text has a newer revision than the one translated.
    source_changed: bool
    # The script chosen for the layer does not appear in its current text: a warning only.
    script_mismatch: bool


class SubmissionOut(BaseModel):
    id: uuid.UUID
    client_submission_id: uuid.UUID
    speaker_id: uuid.UUID
    kind: Kind
    content_type: ContentType
    title: str | None
    language_tag: str
    dialect_label: str | None
    region_coarse: str | None
    recorded_on: date | None
    collection_method: CollectionMethod
    recording_mode: RecordingMode | None
    prompt_id: uuid.UUID | None
    collection_context: CollectionContext
    status: SubmissionStatus
    # Set by an admin to hide the item after a report; shown so the contributor knows.
    restriction_flags: list[Restriction]
    has_consent: bool
    created_at: datetime
    submitted_at: datetime | None
    updated_at: datetime


class SubmissionDetailOut(SubmissionOut):
    # Whether the person asking sent it; only they change it (researchers only read).
    mine: bool
    recordings: list[RecordingOut]
    text_layers: list[TextLayerOut]


class SubmissionListOut(BaseModel):
    items: list[SubmissionOut]
    next_cursor: str | None


class UploadOut(BaseModel):
    recording_id: uuid.UUID
    upload_status: str
