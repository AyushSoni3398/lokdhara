"""docs/DATABASE_SCHEMA.md §6. Created by migration 0013."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, BigInteger, DateTime, ForeignKey, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk

PURPOSES = ("internal_research", "external_research", "public", "ai_training")
RELEASE_STATUSES = ("draft", "frozen", "retracted")
EXPORT_STATUSES = ("requested", "approved", "building", "ready", "expired", "rejected", "failed")


class DatasetRelease(Base):
    """A draft changes freely; once frozen, only retraction changes it (a trigger enforces it)."""

    __tablename__ = "dataset_releases"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    selection_criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    licence: Mapped[str | None] = mapped_column(Text)
    data_card_markdown: Mapped[str] = mapped_column(Text, server_default="")
    manifest_object_key: Mapped[str | None] = mapped_column(Text)
    manifest_sha256: Mapped[str | None] = mapped_column(Text)
    code_version: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = fk("users.id")
    approved_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    created_at: Mapped[datetime] = now_default()
    updated_at: Mapped[datetime] = now_default()
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_note: Mapped[str | None] = mapped_column(Text)


class DatasetReleaseItem(Base):
    """Exactly what a frozen release holds. Only `withdrawn_after_release_at` is set later."""

    __tablename__ = "dataset_release_items"

    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_releases.id"), primary_key=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), primary_key=True)
    recording_id: Mapped[uuid.UUID | None] = optional_fk("recordings.id")
    rendition_id: Mapped[uuid.UUID | None] = optional_fk("renditions.id")
    text_revision_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default="{}")
    consent_record_id: Mapped[uuid.UUID] = fk("consent_records.id")
    consent_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    item_sha256s: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    withdrawn_after_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportRequest(Base):
    __tablename__ = "export_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    release_id: Mapped[uuid.UUID] = fk("dataset_releases.id")
    requested_by: Mapped[uuid.UUID] = fk("users.id")
    purpose_statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="requested")
    decided_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = now_default()
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloaded_at: Mapped[list[datetime]] = mapped_column(
        ARRAY(DateTime(timezone=True)), server_default="{}"
    )
