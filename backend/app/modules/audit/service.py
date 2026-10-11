"""Write audit events in the same transaction as the action they record."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent

# Keys that must never appear in audit details (content, identity, secrets).
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {"password", "token", "email", "phone", "name", "full_name", "content", "text", "ip"}
)


@dataclass(frozen=True)
class RequestContext:
    """Who is acting and from where, as hashes only."""

    request_id: uuid.UUID
    ip_hash: str | None
    user_agent_hash: str | None


def record(
    db: Session,
    *,
    action: str,
    context: RequestContext | None,
    actor_user_id: uuid.UUID | None,
    actor_type: str = "user",
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    details = details or {}
    leaked = _FORBIDDEN_DETAIL_KEYS & details.keys()
    if leaked:
        raise ValueError(f"audit details must not contain {sorted(leaked)}")
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            target_type=target_type,
            target_id=target_id,
            request_id=context.request_id if context else None,
            ip_hash=context.ip_hash if context else None,
            details=details,
        )
    )
