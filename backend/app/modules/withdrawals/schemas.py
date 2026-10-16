import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.text_input import MultiLine

Scope = Literal["full", "narrow", "specific_items"]
ReceivedVia = Literal["in_app", "facilitator", "phone", "in_person", "email"]
Status = Literal["received", "verified", "in_progress", "completed", "rejected"]


class WithdrawalCreateRequest(BaseModel):
    """`full` takes back everything of a speaker, `narrow` changes some consent answers, and
    `specific_items` takes back one submission."""

    scope: Scope
    speaker_id: uuid.UUID | None = None
    submission_id: uuid.UUID | None = None
    # Admins say how the request reached them; for everyone else it follows from who asks.
    received_via: ReceivedVia | None = None
    note: MultiLine | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _subject(self) -> Self:
        if self.scope == "specific_items":
            if self.submission_id is None or self.speaker_id is not None:
                raise ValueError("a request for one item names its submission only")
        elif self.speaker_id is None or self.submission_id is not None:
            raise ValueError("this request names its speaker only")
        return self


class DecisionRequest(BaseModel):
    """How the requester was checked, why a request was refused, or how they were told."""

    note: MultiLine = Field(max_length=2000)


class WithdrawalOut(BaseModel):
    id: uuid.UUID
    speaker_id: uuid.UUID
    speaker_code: str
    submission_id: uuid.UUID | None
    requested_scope: Scope
    received_via: ReceivedVia
    received_at: datetime
    status: Status
    note: str | None
    verified_at: datetime | None
    erased_at: datetime | None
    completed_at: datetime | None
    # What was done, with the admins' notes; only admins see it.
    actions_taken: list[dict[str, Any]] | None


class WithdrawalListOut(BaseModel):
    items: list[WithdrawalOut]
