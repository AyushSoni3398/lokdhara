import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.text_input import MultiLine

Restriction = Literal[
    "sensitive", "third_party_voice", "contains_pii", "culturally_restricted", "minor"
]
Reason = Literal[
    "personal_information", "third_party_voice", "culturally_restricted", "wrong_content"
]


class ReportCreateRequest(BaseModel):
    reason: Reason
    note: MultiLine | None = Field(default=None, max_length=1000)


class ReportOut(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    reason: Reason
    note: str | None
    created_at: datetime


class DecisionRequest(BaseModel):
    """Why the admin decided this; kept with the reports and in the review history."""

    note: MultiLine = Field(max_length=2000)


class HideRequest(DecisionRequest):
    restriction: Restriction


class ItemSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    kind: str
    content_type: str
    status: str
    restriction_flags: list[Restriction]
    submitted_at: datetime | None


class ReportedItemOut(BaseModel):
    submission: ItemSummary
    reports: list[ReportOut]


class ReportedItemListOut(BaseModel):
    items: list[ReportedItemOut]
