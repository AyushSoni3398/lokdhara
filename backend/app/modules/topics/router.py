"""Topics (docs/API_SPECIFICATION.md §4a, ADR-030)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.db import DbSession
from app.modules.identity.deps import Context, CurrentUser, require_roles
from app.modules.identity.service import AuthenticatedUser
from app.modules.topics import service
from app.modules.topics.models import Topic
from app.modules.topics.schemas import (
    AdminTopicListOut,
    AdminTopicOut,
    TopicCreateRequest,
    TopicListOut,
    TopicOut,
    TopicUpdateRequest,
)

router = APIRouter(tags=["topics"])

Admin = Annotated[AuthenticatedUser, Depends(require_roles("admin"))]


def _admin_out(topic: Topic) -> AdminTopicOut:
    return AdminTopicOut.model_validate(topic, from_attributes=True)


@router.get("/topics")
def list_topics(_user: CurrentUser, db: DbSession) -> TopicListOut:
    """The topics offered when describing a recording, in display order."""
    return TopicListOut(
        items=[TopicOut.model_validate(t, from_attributes=True) for t in service.list_topics(db)]
    )


@router.get("/admin/topics")
def admin_list_topics(_admin: Admin, db: DbSession) -> AdminTopicListOut:
    topics = service.list_topics(db, include_retired=True)
    return AdminTopicListOut(items=[_admin_out(t) for t in topics])


@router.post("/admin/topics", status_code=status.HTTP_201_CREATED)
def create_topic(
    body: TopicCreateRequest, admin: Admin, db: DbSession, context: Context
) -> AdminTopicOut:
    return _admin_out(service.create(db, admin=admin, body=body, context=context))


@router.patch("/admin/topics/{key}")
def update_topic(
    key: str, body: TopicUpdateRequest, admin: Admin, db: DbSession, context: Context
) -> AdminTopicOut:
    return _admin_out(service.update(db, admin=admin, key=key, body=body, context=context))
