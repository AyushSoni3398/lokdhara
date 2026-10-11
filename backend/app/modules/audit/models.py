import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ACTOR_TYPES = ("user", "system", "worker")


class AuditEvent(Base):
    """Append-only (trigger-enforced). `details` must never hold content, names, or contacts."""

    __tablename__ = "audit_events"
    __table_args__ = (CheckConstraint(f"actor_type IN {ACTOR_TYPES}", name="actor_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
