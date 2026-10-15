"""Reports (docs/API_SPECIFICATION.md §7)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.db import DbSession
from app.modules.identity.deps import AdminUser, Context, CurrentUser
from app.modules.reports import service
from app.modules.reports.schemas import (
    DecisionRequest,
    HideRequest,
    ItemSummary,
    ReportCreateRequest,
    ReportedItemListOut,
    ReportedItemOut,
    ReportOut,
)
from app.modules.submissions.models import Submission

router = APIRouter(tags=["reports"])


@router.post("/submissions/{submission_id}/reports", status_code=status.HTTP_201_CREATED)
def report_submission(
    submission_id: uuid.UUID,
    body: ReportCreateRequest,
    user: CurrentUser,
    db: DbSession,
    context: Context,
) -> ReportOut:
    report = service.report(db, user=user, submission_id=submission_id, body=body, context=context)
    return ReportOut.model_validate(report, from_attributes=True)


def _summary(submission: Submission) -> ItemSummary:
    return ItemSummary.model_validate(submission, from_attributes=True)


@router.get("/admin/reports")
def list_open_reports(
    _admin: AdminUser, db: DbSession, limit: Annotated[int, Query(gt=0, le=200)] = 50
) -> ReportedItemListOut:
    return ReportedItemListOut(
        items=[
            ReportedItemOut(
                submission=_summary(item.submission),
                reports=[ReportOut.model_validate(r, from_attributes=True) for r in item.reports],
            )
            for item in service.open_reports(db, limit)
        ]
    )


@router.post("/admin/submissions/{submission_id}/hide")
def hide_submission(
    submission_id: uuid.UUID, body: HideRequest, admin: AdminUser, db: DbSession, context: Context
) -> ItemSummary:
    submission = service.hide(
        db,
        admin=admin,
        submission_id=submission_id,
        restriction=body.restriction,
        note=body.note,
        context=context,
    )
    return _summary(submission)


@router.post("/admin/submissions/{submission_id}/unhide")
def unhide_submission(
    submission_id: uuid.UUID, body: HideRequest, admin: AdminUser, db: DbSession, context: Context
) -> ItemSummary:
    submission = service.unhide(
        db,
        admin=admin,
        submission_id=submission_id,
        restriction=body.restriction,
        note=body.note,
        context=context,
    )
    return _summary(submission)


@router.post("/admin/submissions/{submission_id}/dismiss-reports")
def dismiss_reports(
    submission_id: uuid.UUID,
    body: DecisionRequest,
    admin: AdminUser,
    db: DbSession,
    context: Context,
) -> ItemSummary:
    submission = service.dismiss(
        db, admin=admin, submission_id=submission_id, note=body.note, context=context
    )
    return _summary(submission)
