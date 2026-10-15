"""Reporting an item. Anyone who can see an item may report it; admins decide (ADR-021)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser
from app.modules.reports.models import Report
from app.modules.reports.schemas import ReportCreateRequest
from app.modules.submissions import service as submissions

# Drafts are private and unfinished; withdrawn items are already on their way out.
NOT_REPORTABLE = ("draft", "withdrawn")


def _already_reported() -> ApiError:
    return ApiError(
        409, "already_reported", "You have already reported this. An admin will look at it."
    )


def report(
    db: Session,
    *,
    user: AuthenticatedUser,
    submission_id: uuid.UUID,
    body: ReportCreateRequest,
    context: RequestContext,
) -> Report:
    submission = submissions.get_visible(db, user, submission_id)
    if submission.status in NOT_REPORTABLE:
        raise ApiError(409, "not_reportable", "This item cannot be reported.")
    open_report = db.scalar(
        select(Report.id).where(
            Report.submission_id == submission.id,
            Report.reported_by == user.id,
            Report.decision.is_(None),
        )
    )
    if open_report is not None:
        raise _already_reported()
    report = Report(
        submission_id=submission.id, reported_by=user.id, reason=body.reason, note=body.note
    )
    try:
        with db.begin_nested():
            db.add(report)
    except IntegrityError as exc:
        if "uq_reports_open" not in str(exc.orig):
            raise
        raise _already_reported() from exc
    audit.record(
        db,
        action="report.create",
        context=context,
        actor_user_id=user.id,
        target_type="submission",
        target_id=submission.id,
        details={"reason": body.reason},
    )
    db.commit()
    return report
