"""The topic list (ADR-030): contributors pick from it, admins add to it and retire topics.

Items keep the keys they were given; a retired topic is no longer offered but stays on items
that have it, and an item being edited may keep it.
"""

from collections.abc import Collection, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.topics.models import Topic
from app.modules.topics.schemas import MAX_TOPICS, TopicCreateRequest, TopicUpdateRequest


def list_topics(db: Session, *, include_retired: bool = False) -> list[Topic]:
    query = select(Topic).order_by(Topic.sort_order, Topic.key)
    if not include_retired:
        query = query.where(Topic.retired_at.is_(None))
    return list(db.scalars(query))


def active_keys(db: Session) -> set[str]:
    return set(db.scalars(select(Topic.key).where(Topic.retired_at.is_(None))))


def checked(db: Session, keys: Iterable[str], *, kept: Collection[str] = ()) -> list[str]:
    """The keys, sorted and without repeats, if each is offered (or already on the item)."""
    chosen = sorted(set(keys))
    if len(chosen) > MAX_TOPICS:
        raise ApiError(422, "too_many_topics", f"Choose at most {MAX_TOPICS} topics.")
    unknown = [key for key in chosen if key not in kept and key not in active_keys(db)]
    if unknown:
        raise ApiError(
            422,
            "unknown_topic",
            "Choose topics from the list.",
            f"Not offered: {', '.join(unknown)}",
        )
    return chosen


def from_prompt(db: Session, topic_tags: Iterable[str]) -> list[str]:
    """A prompt's tags that are on the topic list: the starting topics of its recordings."""
    offered = active_keys(db)
    return sorted({tag.replace("-", "_") for tag in topic_tags} & offered)[:MAX_TOPICS]


def _get(db: Session, key: str) -> Topic:
    topic = db.scalar(select(Topic).where(Topic.key == key).with_for_update())
    if topic is None:
        raise ApiError(404, "topic_not_found", "Topic not found.")
    return topic


def _audit(
    db: Session, action: str, admin: AuthenticatedUser, topic: Topic, context: RequestContext
) -> None:
    audit.record(
        db,
        action=action,
        context=context,
        actor_user_id=admin.id,
        target_type="topic",
        details={"key": topic.key},
    )


def create(
    db: Session, *, admin: AuthenticatedUser, body: TopicCreateRequest, context: RequestContext
) -> Topic:
    if db.get(Topic, body.key) is not None:
        raise ApiError(409, "topic_exists", "A topic with this key already exists.")
    topic = Topic(**body.model_dump(), created_by=admin.id)
    db.add(topic)
    _audit(db, "topic.create", admin, topic, context)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - two admins adding the same key
        db.rollback()
        raise ApiError(409, "topic_exists", "A topic with this key already exists.") from exc
    return topic


def update(
    db: Session,
    *,
    admin: AuthenticatedUser,
    key: str,
    body: TopicUpdateRequest,
    context: RequestContext,
) -> Topic:
    topic = _get(db, key)
    changes = body.model_dump(exclude_unset=True, exclude={"retired"})
    for field, value in changes.items():
        if value is not None:
            setattr(topic, field, value)
    if body.retired is not None:
        topic.retired_at = (topic.retired_at or utcnow()) if body.retired else None
    _audit(db, "topic.update", admin, topic, context)
    db.commit()
    return topic
