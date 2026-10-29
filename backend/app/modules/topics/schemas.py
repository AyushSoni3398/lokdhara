from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.text_input import SingleLine

TopicKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
TopicLabel = Annotated[SingleLine, Field(min_length=1, max_length=80)]
# How many topics one item may have (also a database check).
MAX_TOPICS = 10


class TopicOut(BaseModel):
    key: str
    label_en: str
    label_hi: str


class TopicListOut(BaseModel):
    items: list[TopicOut]


class AdminTopicOut(TopicOut):
    sort_order: int
    retired_at: datetime | None
    created_at: datetime


class AdminTopicListOut(BaseModel):
    items: list[AdminTopicOut]


class TopicCreateRequest(BaseModel):
    key: TopicKey
    label_en: TopicLabel
    label_hi: TopicLabel
    sort_order: int = Field(default=1000, ge=0, le=100_000)


class TopicUpdateRequest(BaseModel):
    """Fields left out stay as they are. The key never changes, so exports keep their meaning."""

    label_en: TopicLabel | None = None
    label_hi: TopicLabel | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    retired: bool | None = None
