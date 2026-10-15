"""docs/DATABASE_SCHEMA.md §4. Created by migration 0012."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk

REASONS = ("personal_information", "third_party_voice", "culturally_restricted", "wrong_content")
DECISIONS = ("hidden", "dismissed")


class Report(Base):
    """Never deleted; only the decision columns are written, once."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_id: Mapped[uuid.UUID] = fk("submissions.id")
    reported_by: Mapped[uuid.UUID] = fk("users.id")
    reason: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_default()
    decision: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
