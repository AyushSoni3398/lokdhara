"""docs/DATABASE_SCHEMA.md §3 (topics) and ADR-030. Created by migration 0018."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import now_default, optional_fk


class Topic(Base):
    """One subject a recording can be about. The key never changes; retiring hides it."""

    __tablename__ = "topics"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    label_en: Mapped[str] = mapped_column(Text)
    label_hi: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="1000")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    created_at: Mapped[datetime] = now_default()
