"""docs/DATABASE_SCHEMA.md §5. Created by migration 0015."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules._columns import now_default, uuid_pk

KINDS = ("database", "withdrawal_log")


class BackupRun(Base):
    """Written once by infra/prod/backup/backup.sh when a run ends; never changed."""

    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = now_default()
    succeeded: Mapped[bool] = mapped_column(Boolean)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_name: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
