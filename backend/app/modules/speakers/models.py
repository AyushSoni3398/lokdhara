"""docs/DATABASE_SCHEMA.md §2. Created by migration 0004."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk

AGE_BANDS = ("18-29", "30-44", "45-59", "60+", "under_18", "undisclosed")


class Speaker(Base):
    """Pseudonymous profile. Demographic columns must stay NULL without demographics consent."""

    __tablename__ = "speakers"

    id: Mapped[uuid.UUID] = uuid_pk()
    # SPK_<random>_<gender letter>, e.g. SPK_7Q3M9A_F. Only the letter ever changes (ADR-034).
    speaker_code: Mapped[str] = mapped_column(Text)
    linked_user_id: Mapped[uuid.UUID | None] = optional_fk("users.id")
    created_by: Mapped[uuid.UUID] = fk("users.id")
    age_band: Mapped[str | None] = mapped_column(Text)
    # female, male, other, or undisclosed; its letter ends the speaker code (ADR-034).
    gender: Mapped[str | None] = mapped_column(Text)
    first_language: Mapped[str | None] = mapped_column(Text)
    other_languages: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    dialect_label: Mapped[str | None] = mapped_column(Text)
    region_coarse: Mapped[str | None] = mapped_column(Text)
    demographics_consented: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = now_default()


class SpeakerIdentity(Base):
    """Restricted: application-encrypted ciphertext only. Admin and creating facilitator."""

    __tablename__ = "speaker_identities"

    speaker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("speakers.id"), primary_key=True)
    full_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    contact_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    village_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    notes_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = now_default()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
