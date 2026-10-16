"""Withdrawal requests (docs/API_SPECIFICATION.md §3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import DbSession
from app.modules.consents.models import WithdrawalRequest
from app.modules.identity.deps import AdminUser, Context, CurrentUser
from app.modules.identity.service import AuthenticatedUser
from app.modules.speakers.models import Speaker
from app.modules.withdrawals import service
from app.modules.withdrawals.schemas import (
    DecisionRequest,
    WithdrawalCreateRequest,
    WithdrawalListOut,
    WithdrawalOut,
)
from app.object_store import ObjectStore, get_object_store

router = APIRouter(tags=["withdrawals"])
Store = Annotated[ObjectStore, Depends(get_object_store)]


def _out(db: Session, user: AuthenticatedUser, request: WithdrawalRequest) -> WithdrawalOut:
    speaker = db.get_one(Speaker, request.speaker_id)
    fields = {
        f: getattr(request, f)
        for f in WithdrawalOut.model_fields
        if f not in ("speaker_code", "actions_taken")
    }
    return WithdrawalOut(
        **fields,
        speaker_code=speaker.speaker_code,
        actions_taken=request.actions_taken if user.has_role("admin") else None,
    )


@router.post("/withdrawal-requests", status_code=status.HTTP_201_CREATED)
def request_withdrawal(
    body: WithdrawalCreateRequest, user: CurrentUser, db: DbSession, context: Context
) -> WithdrawalOut:
    return _out(db, user, service.create(db, user=user, body=body, context=context))


@router.get("/withdrawal-requests")
def my_withdrawals(user: CurrentUser, db: DbSession) -> WithdrawalListOut:
    """What the user asked for, and requests about their own speaker profile."""
    return WithdrawalListOut(items=[_out(db, user, r) for r in service.list_mine(db, user)])


@router.get("/withdrawal-requests/{request_id}")
def get_withdrawal(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WithdrawalOut:
    return _out(db, user, service.get(db, user, request_id))


@router.get("/admin/withdrawal-requests")
def withdrawal_queue(
    admin: AdminUser, db: DbSession, open_only: Annotated[bool, Query(alias="open")] = True
) -> WithdrawalListOut:
    return WithdrawalListOut(
        items=[_out(db, admin, r) for r in service.list_all(db, open_only=open_only)]
    )


@router.post("/admin/withdrawal-requests/{request_id}/verify")
def verify_withdrawal(
    request_id: uuid.UUID,
    body: DecisionRequest,
    admin: AdminUser,
    db: DbSession,
    store: Store,
    context: Context,
) -> WithdrawalOut:
    """`note`: how the requester was confirmed as the speaker or their representative."""
    request = service.verify(
        db, store, admin=admin, request_id=request_id, note=body.note, context=context
    )
    return _out(db, admin, request)


@router.post("/admin/withdrawal-requests/{request_id}/reject")
def reject_withdrawal(
    request_id: uuid.UUID, body: DecisionRequest, admin: AdminUser, db: DbSession, context: Context
) -> WithdrawalOut:
    request = service.reject(
        db, admin=admin, request_id=request_id, note=body.note, context=context
    )
    return _out(db, admin, request)


@router.post("/admin/withdrawal-requests/{request_id}/complete")
def complete_withdrawal(
    request_id: uuid.UUID, body: DecisionRequest, admin: AdminUser, db: DbSession, context: Context
) -> WithdrawalOut:
    """`note`: how the requester was told that their request was carried out."""
    request = service.complete(
        db, admin=admin, request_id=request_id, note=body.note, context=context
    )
    return _out(db, admin, request)
