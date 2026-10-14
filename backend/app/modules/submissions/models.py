"""docs/DATABASE_SCHEMA.md §3. Created by migrations 0005 and 0006; 0009 adds upload keys,
0010 the `accepted` status, 0011 draft audio expiry.

Prompts, also created by 0005, are in app.modules.prompts.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk

SCRIPT_CODES = ("Deva", "Latn", "Nagm", "Beng", "Orya", "Zyyy")
SUBMISSION_STATUSES = (
    "draft",
    "uploading",
    "processing",
    "processing_failed",
    "rejected_invalid",
    "accepted",
    "awaiting_review",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
    "withdrawn",
)
RESTRICTION_FLAGS = (
    "sensitive",
    "third_party_voice",
    "contains_pii",
    "culturally_restricted",
    "minor",
)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_submission_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    submitted_by: Mapped[uuid.UUID] = fk("users.id")
    speaker_id: Mapped[uuid.UUID] = fk("speakers.id")
    consent_record_id: Mapped[uuid.UUID | None] = optional_fk("consent_records.id")
    kind: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    language_tag: Mapped[str] = mapped_column(Text, server_default="unr")
    dialect_label: Mapped[str | None] = mapped_column(Text)
    region_coarse: Mapped[str | None] = mapped_column(Text)
    recorded_on: Mapped[date | None] = mapped_column(Date)
    recording_mode: Mapped[str | None] = mapped_column(Text)
    prompt_id: Mapped[uuid.UUID | None] = optional_fk("prompts.id")
    collection_method: Mapped[str] = mapped_column(Text)
    collection_context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    restriction_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    created_at: Mapped[datetime] = now_default()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = now_default()


class RelatedItem(Base):
    __tablename__ = "related_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_a: Mapped[uuid.UUID] = fk("submissions.id")
    submission_b: Mapped[uuid.UUID] = fk("submissions.id")
    relation: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    created_at: Mapped[datetime] = now_default()


class Recording(Base):
    """The original's key, checksum, and size never change (ADR-009)."""

    __tablename__ = "recordings"

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_id: Mapped[uuid.UUID] = fk("submissions.id")
    original_object_key: Mapped[str] = mapped_column(Text)
    original_filename_ext: Mapped[str | None] = mapped_column(Text)
    sha256_original: Mapped[str] = mapped_column(Text)
    sha256_pcm: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    detected_container: Mapped[str | None] = mapped_column(Text)
    detected_codec: Mapped[str | None] = mapped_column(Text)
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    bit_depth: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    is_lossy_source: Mapped[bool | None] = mapped_column(Boolean)
    upload_status: Mapped[str] = mapped_column(Text, server_default="quarantined")
    validation_errors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quality_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quality_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    recorded_device_hint: Mapped[str | None] = mapped_column(Text)
    # The Idempotency-Key of the upload that created it (migration 0009).
    upload_key: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # When the bytes were last stored in quarantine; a draft's audio expires from here (0011).
    quarantined_at: Mapped[datetime] = now_default()
    created_at: Mapped[datetime] = now_default()


class Rendition(Base):
    """Append-only derived file (playback, analysis copy, waveform)."""

    __tablename__ = "renditions"

    id: Mapped[uuid.UUID] = uuid_pk()
    recording_id: Mapped[uuid.UUID] = fk("recordings.id")
    kind: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    params_sha256: Mapped[str] = mapped_column(Text)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    processing_run_id: Mapped[uuid.UUID | None] = optional_fk("processing_runs.id")
    created_at: Mapped[datetime] = now_default()


class TextLayer(Base):
    __tablename__ = "text_layers"

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_id: Mapped[uuid.UUID] = fk("submissions.id")
    layer_type: Mapped[str] = mapped_column(Text)
    recording_id: Mapped[uuid.UUID | None] = optional_fk("recordings.id")
    source_layer_id: Mapped[uuid.UUID | None] = optional_fk("text_layers.id")
    entry_type: Mapped[str | None] = mapped_column(Text)
    language_tag: Mapped[str] = mapped_column(Text)
    script_code: Mapped[str] = mapped_column(Text)
    # text_layers and text_revisions reference each other; use_alter breaks the cycle.
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "text_revisions.id",
            use_alter=True,
            name="fk_text_layers_current_revision_id_text_revisions",
        )
    )
    created_at: Mapped[datetime] = now_default()


class TextRevision(Base):
    """Append-only (ADR-011). `content_original` is verbatim; only verification changes."""

    __tablename__ = "text_revisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    layer_id: Mapped[uuid.UUID] = fk("text_layers.id")
    revision_number: Mapped[int] = mapped_column(Integer)
    based_on_revision_id: Mapped[uuid.UUID | None] = optional_fk("text_revisions.id")
    source_revision_id: Mapped[uuid.UUID | None] = optional_fk("text_revisions.id")
    content_original: Mapped[str] = mapped_column(Text)
    content_nfc: Mapped[str] = mapped_column(Text)
    content_normalized: Mapped[str | None] = mapped_column(Text)
    normalization_policy_version: Mapped[str | None] = mapped_column(Text)
    detected_scripts: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    uncertainty_markup: Mapped[bool] = mapped_column(Boolean, server_default="false")
    origin: Mapped[str] = mapped_column(Text)
    author_user_id: Mapped[uuid.UUID | None] = optional_fk("users.id")
    tool_name: Mapped[str | None] = mapped_column(Text)
    tool_version: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    verification_status: Mapped[str] = mapped_column(Text, server_default="unverified")
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_default()
