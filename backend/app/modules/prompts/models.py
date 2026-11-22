"""docs/DATABASE_SCHEMA.md §3 (prompts) and docs/RECORDING_MODES.md. Created by migration 0005."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import fk, now_default, optional_fk, uuid_pk


class Prompt(Base):
    """One row per prompt version; editing creates a new version (ADR-018)."""

    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = uuid_pk()
    prompt_key: Mapped[str] = mapped_column(Text)
    # One number per prompt key, shared by its versions: the S012 in a recording code (ADR-034).
    prompt_number: Mapped[int] = mapped_column(
        Integer, server_default=text("nextval('prompts_prompt_number_seq')")
    )
    version: Mapped[int] = mapped_column(Integer)
    prompt_type: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    text_language_tag: Mapped[str | None] = mapped_column(Text)
    script_code: Mapped[str | None] = mapped_column(Text)
    image_object_key: Mapped[str | None] = mapped_column(Text)
    prompt_audio_object_key: Mapped[str | None] = mapped_column(Text)
    source_and_licence: Mapped[str] = mapped_column(Text)
    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    approved_by: Mapped[uuid.UUID | None] = optional_fk("users.id")
    created_by: Mapped[uuid.UUID] = fk("users.id")
    created_at: Mapped[datetime] = now_default()
