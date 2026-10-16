"""docs/DATABASE_SCHEMA.md §2 and ADR-012. Created by migration 0004; 0014 extends
withdrawal_requests."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk

# Yes/no use permissions (docs/CONSENT_AND_DATA_GOVERNANCE.md §3.1). The other questions are
# attribution_preference and demographics_consented.
PERMISSIONS = (
    "allow_store_and_review",
    "allow_research",
    "allow_public_access",
    "allow_ai_training",
    "allow_commercial_use",
)


class ConsentForm(Base):
    """Immutable once published, except for retirement."""

    __tablename__ = "consent_forms"

    id: Mapped[uuid.UUID] = uuid_pk()
    form_code: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    ethics_reference: Mapped[str | None] = mapped_column(Text)
    is_test_form: Mapped[bool] = mapped_column(Boolean, server_default="true")
    effective_from: Mapped[datetime] = now_default()
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsentRecord(Base):
    """Append-only: a change creates a new record; only `status` is ever updated."""

    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    speaker_id: Mapped[uuid.UUID] = fk("speakers.id")
    consent_form_id: Mapped[uuid.UUID] = fk("consent_forms.id")
    supersedes_id: Mapped[uuid.UUID | None] = optional_fk("consent_records.id")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    method: Mapped[str] = mapped_column(Text)
    obtained_by: Mapped[uuid.UUID] = fk("users.id")
    obtained_at: Mapped[datetime] = now_default()
    guardian_involved: Mapped[bool] = mapped_column(Boolean)
    guardian_relationship: Mapped[str | None] = mapped_column(Text)
    evidence_object_key: Mapped[str | None] = mapped_column(Text)
    paper_reference: Mapped[str | None] = mapped_column(Text)
    allow_store_and_review: Mapped[bool] = mapped_column(Boolean)
    allow_research: Mapped[bool] = mapped_column(Boolean, server_default="false")
    allow_public_access: Mapped[bool] = mapped_column(Boolean, server_default="false")
    allow_ai_training: Mapped[bool] = mapped_column(Boolean, server_default="false")
    allow_commercial_use: Mapped[bool] = mapped_column(Boolean, server_default="false")
    attribution_preference: Mapped[str] = mapped_column(Text, server_default="pseudonymous")
    demographics_consented: Mapped[bool] = mapped_column(Boolean, server_default="false")
    applies_to_past_contributions: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)


class WithdrawalRequest(Base):
    """What was asked, by whom, and when never changes; the rest records how it was handled."""

    __tablename__ = "withdrawal_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    speaker_id: Mapped[uuid.UUID | None] = optional_fk("speakers.id")
    submission_id: Mapped[uuid.UUID | None] = optional_fk("submissions.id")
    received_via: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = now_default()
    recorded_by: Mapped[uuid.UUID] = fk("users.id")
    requested_scope: Mapped[str] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="received")
    actions_taken: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    # Set when the request is closed, whether completed or rejected.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Migration 0014: a note from whoever logged it, and when the deletion routine finished.
    note: Mapped[str | None] = mapped_column(Text)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
