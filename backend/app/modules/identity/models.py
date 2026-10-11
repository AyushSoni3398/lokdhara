"""Identity tables (docs/DATABASE_SCHEMA.md §1). Created by migration 0001."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLES = ("contributor", "facilitator", "reviewer", "researcher", "admin")
STAFF_ROLES = frozenset({"reviewer", "admin"})
USER_STATUSES = ("invited", "active", "suspended", "deactivated")
LOCALES = ("hi", "en")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=text("uuidv7()"))


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"status IN {USER_STATUSES}", name="status"),
        CheckConstraint(f"preferred_locale IN {LOCALES}", name="preferred_locale"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(Text)  # unique on lower(username), see migration
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)  # restricted
    phone: Mapped[str | None] = mapped_column(Text)  # restricted
    password_hash: Mapped[str] = mapped_column(Text)  # restricted
    status: Mapped[str] = mapped_column(Text, server_default="active")
    preferred_locale: Mapped[str] = mapped_column(Text, server_default="hi")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserRole(Base):
    """Grants are never deleted; revocation sets revoked_at."""

    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    scope: Mapped[str | None] = mapped_column(Text)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_hash: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)


class LoginThrottle(Base):
    """Failed-login counters keyed by a keyed hash of the username or client IP."""

    __tablename__ = "login_throttle"

    key_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    window_started_at: Mapped[datetime] = _now()
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
