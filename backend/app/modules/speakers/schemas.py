import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.languages import LanguageTag
from app.text_input import MultiLine, SingleLine

AgeBand = Literal["18-29", "30-44", "45-59", "60+", "under_18", "undisclosed"]
# Shown as M, F, O, or X at the end of the speaker code (ADR-034).
Gender = Literal["female", "male", "other", "undisclosed"]


class SpeakerCreateRequest(BaseModel):
    # True: the signed-in person's own profile. False: someone else's (facilitators and admins).
    for_self: bool
    dialect_label: SingleLine | None = Field(default=None, max_length=100)


class SpeakerUpdateRequest(BaseModel):
    """Only the fields sent are changed. Demographics need the speaker's consent."""

    dialect_label: SingleLine | None = Field(default=None, max_length=100)
    age_band: AgeBand | None = None
    gender: Gender | None = None
    first_language: LanguageTag | None = None
    other_languages: list[LanguageTag] | None = Field(default=None, max_length=10)
    region_coarse: SingleLine | None = Field(default=None, max_length=100)


class SpeakerOut(BaseModel):
    id: uuid.UUID
    speaker_code: str
    is_self: bool
    status: str
    has_active_consent: bool
    demographics_consented: bool
    dialect_label: str | None
    age_band: str | None
    gender: str | None
    first_language: str | None
    other_languages: list[str] | None
    region_coarse: str | None
    created_at: datetime


class SpeakerListOut(BaseModel):
    items: list[SpeakerOut]


class IdentityRequest(BaseModel):
    """Replaces all identity fields; a missing field is cleared."""

    full_name: SingleLine | None = Field(default=None, max_length=200)
    contact: SingleLine | None = Field(default=None, max_length=200)
    village: SingleLine | None = Field(default=None, max_length=200)
    notes: MultiLine | None = Field(default=None, max_length=2000)


class IdentityOut(BaseModel):
    full_name: str | None
    contact: str | None
    village: str | None
    notes: str | None
    updated_at: datetime | None
