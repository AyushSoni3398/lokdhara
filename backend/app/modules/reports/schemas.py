import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.text_input import MultiLine

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
