"""Logging and deciding withdrawal requests (docs/DATA_RETENTION_AND_DELETION.md §2).

Anyone who may act for a speaker can ask: the speaker in the app, the facilitator who
registered them, or an admin who heard it by phone, in person or by email. An admin then checks
that the request really comes from the speaker or someone allowed to speak for them.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.consents import service as consents
from app.modules.consents.models import ConsentRecord, WithdrawalRequest
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.releases import withdrawals as releases
from app.modules.speakers import service as speakers
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import Submission
from app.modules.withdrawals.schemas import WithdrawalCreateRequest
from app.object_store import ObjectStore

# Requests an admin has not decided yet, and those still being carried out.
OPEN_STATUSES = ("received", "verified", "in_progress")
MAX_LIST = 200


def _not_found() -> ApiError:
    return ApiError(404, "withdrawal_not_found", "Withdrawal request not found.")


def _subject(
    db: Session, user: AuthenticatedUser, body: WithdrawalCreateRequest
) -> tuple[Speaker, Submission | None]:
    """The speaker (and item) the user may ask for. Researchers who can only read an item in
    the catalogue cannot withdraw it."""
    submission = None
    if body.submission_id is None and body.speaker_id is not None:
        speaker = speakers.get_visible(db, user, body.speaker_id)
        if not speakers.can_act_for(user, speaker):
            raise ApiError(403, "forbidden", "You do not have permission for this action.")
    elif body.submission_id is not None:
        submission = db.get(Submission, body.submission_id)
        if submission is None:
            raise ApiError(404, "submission_not_found", "Submission not found.")
        speaker = db.get_one(Speaker, submission.speaker_id)
        if not (submission.submitted_by == user.id or speakers.can_act_for(user, speaker)):
            raise ApiError(404, "submission_not_found", "Submission not found.")
        if submission.status == "withdrawn":
            raise ApiError(409, "already_withdrawn", "This item has already been withdrawn.")
    else:  # pragma: no cover - the schema requires one of them
        raise ApiError(422, "validation_error", "Name the speaker or the item.")
    if speaker.status == "withdrawn":
        raise ApiError(409, "speaker_withdrawn", "This speaker has withdrawn.")
    return speaker, submission


def _received_via(user: AuthenticatedUser, speaker: Speaker, body: WithdrawalCreateRequest) -> str:
    if user.has_role("admin"):
        return body.received_via or "in_app"
    if speaker.linked_user_id == user.id:
        return "in_app"
    return "facilitator"


def create(
    db: Session, *, user: AuthenticatedUser, body: WithdrawalCreateRequest, context: RequestContext
) -> WithdrawalRequest:
    speaker, submission = _subject(db, user, body)
    request = WithdrawalRequest(
        speaker_id=speaker.id,
        submission_id=submission.id if submission else None,
        received_via=_received_via(user, speaker, body),
        recorded_by=user.id,
        requested_scope=body.scope,
        note=body.note,
    )
    try:
        with db.begin_nested():
            db.add(request)
    except IntegrityError as exc:
        if "uq_withdrawal_requests_waiting" not in str(exc.orig):
            raise
        raise ApiError(
            409, "already_requested", "This has already been asked for. An admin will act on it."
        ) from exc
    audit.record(
        db,
        action="withdrawal.request",
        context=context,
        actor_user_id=user.id,
        target_type="withdrawal_request",
        target_id=request.id,
        details={"scope": body.scope, "received_via": request.received_via},
    )
    db.commit()
    return request


def list_mine(db: Session, user: AuthenticatedUser) -> list[WithdrawalRequest]:
    """Requests the user logged, and those about their own speaker profile."""
    own_speaker = select(Speaker.id).where(Speaker.linked_user_id == user.id)
    return list(
        db.scalars(
            select(WithdrawalRequest)
            .where(
                or_(
                    WithdrawalRequest.recorded_by == user.id,
                    WithdrawalRequest.speaker_id.in_(own_speaker),
                )
            )
            .order_by(WithdrawalRequest.received_at.desc())
            .limit(MAX_LIST)
        )
    )


def list_all(db: Session, *, open_only: bool) -> list[WithdrawalRequest]:
    """For admins: open requests oldest first (the ones waiting longest on top), or all
    requests newest first."""
    query = select(WithdrawalRequest)
    if open_only:
        query = query.where(WithdrawalRequest.status.in_(OPEN_STATUSES)).order_by(
            WithdrawalRequest.received_at
        )
    else:
        query = query.order_by(WithdrawalRequest.received_at.desc())
    return list(db.scalars(query.limit(MAX_LIST)))


def get(db: Session, user: AuthenticatedUser, request_id: uuid.UUID) -> WithdrawalRequest:
    request = db.get(WithdrawalRequest, request_id)
    if request is None:
        raise _not_found()
    speaker = db.get_one(Speaker, request.speaker_id)
    if user.has_role("admin") or user.id in (request.recorded_by, speaker.linked_user_id):
        return request
    raise _not_found()


# ------------------------------------------------------------------ admin decisions


def _to_decide(db: Session, request_id: uuid.UUID) -> WithdrawalRequest:
    request = db.scalar(
        select(WithdrawalRequest).where(WithdrawalRequest.id == request_id).with_for_update()
    )
    if request is None:
        raise _not_found()
    if request.status != "received":
        raise ApiError(409, "withdrawal_decided", "This request has already been decided.")
    return request


def _record_action(
    request: WithdrawalRequest, action: str, admin: AuthenticatedUser, now: datetime, **facts: Any
) -> None:
    entry = {"action": action, "at": now.isoformat(), "by": str(admin.id), **facts}
    request.actions_taken = [*request.actions_taken, entry]


def _withdraw_speaker(db: Session, speaker: Speaker, now: datetime) -> list[uuid.UUID]:
    """Everything of the speaker becomes invisible to all but admins. Returns every submission
    of the speaker, including ones withdrawn before."""
    speaker.status = "withdrawn"
    active = consents.active_consent(db, speaker.id)
    if active is not None:
        active.status = "withdrawn"
    submissions = db.scalars(
        select(Submission).where(Submission.speaker_id == speaker.id).with_for_update()
    ).all()
    for submission in submissions:
        if submission.status != "withdrawn":
            submission.status = "withdrawn"
            submission.updated_at = now
    return [submission.id for submission in submissions]


def _withdraw_item(db: Session, submission_id: uuid.UUID, now: datetime) -> list[uuid.UUID]:
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id).with_for_update()
    )
    if submission is None:  # pragma: no cover - a foreign key guarantees it
        raise _not_found()
    if submission.status != "withdrawn":
        submission.status = "withdrawn"
        submission.updated_at = now
    return [submission.id]


def verify(
    db: Session,
    store: ObjectStore,
    *,
    admin: AuthenticatedUser,
    request_id: uuid.UUID,
    note: str,
    context: RequestContext,
) -> WithdrawalRequest:
    """The admin has checked that the request comes from the speaker or someone allowed to
    speak for them (§2.2). The items are restricted at once (§2.3) and frozen releases that
    hold them are marked (§2.4).

    A `narrow` request is carried out by recording the speaker's new consent answers, which
    marks frozen releases by itself; verifying it only checks that this was done."""
    request = _to_decide(db, request_id)
    speaker = db.scalar(select(Speaker).where(Speaker.id == request.speaker_id).with_for_update())
    if speaker is None:  # pragma: no cover - a foreign key guarantees it
        raise _not_found()
    now = utcnow()
    withdrawn: list[uuid.UUID] = []
    marked = 0
    if request.requested_scope == "narrow":
        changed = db.scalar(
            select(ConsentRecord.id)
            .where(
                ConsentRecord.speaker_id == speaker.id,
                ConsentRecord.obtained_at >= request.received_at,
            )
            .limit(1)
        )
        if changed is None:
            raise ApiError(
                409,
                "consent_not_changed",
                "Record the speaker's new consent answers first, then verify the request.",
            )
    else:
        if request.requested_scope == "full":
            withdrawn = _withdraw_speaker(db, speaker, now)
        elif request.submission_id is not None:
            withdrawn = _withdraw_item(db, request.submission_id, now)
        marked = releases.mark_withdrawn(
            db, store, submission_ids=withdrawn, actor_id=admin.id, now=now, context=context
        )
    request.status = "verified"
    request.verified_by = admin.id
    request.verified_at = now
    _record_action(
        request, "verified", admin, now, note=note, items=len(withdrawn), releases_marked=marked
    )
    audit.record(
        db,
        action="withdrawal.verify",
        context=context,
        actor_user_id=admin.id,
        target_type="withdrawal_request",
        target_id=request.id,
        details={
            "scope": request.requested_scope,
            "items": len(withdrawn),
            "releases_marked": marked,
        },
    )
    db.commit()
    return request


def reject(
    db: Session,
    *,
    admin: AuthenticatedUser,
    request_id: uuid.UUID,
    note: str,
    context: RequestContext,
) -> WithdrawalRequest:
    """The request could not be confirmed as coming from the speaker; nothing changes."""
    request = _to_decide(db, request_id)
    now = utcnow()
    request.status = "rejected"
    request.completed_at = now
    _record_action(request, "rejected", admin, now, note=note)
    audit.record(
        db,
        action="withdrawal.reject",
        context=context,
        actor_user_id=admin.id,
        target_type="withdrawal_request",
        target_id=request.id,
        details={"scope": request.requested_scope},
    )
    db.commit()
    return request
