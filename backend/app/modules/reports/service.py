"""Reporting an item. Anyone who can see an item may report it; admins decide (ADR-021)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.reports.models import Report
from app.modules.reports.schemas import ReportCreateRequest
from app.modules.review.models import ReviewEvent
from app.modules.submissions import service as submissions
from app.modules.submissions.models import Submission

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


# ------------------------------------------------------------------ admin decisions


@dataclass(frozen=True)
class ReportedItem:
    submission: Submission
    reports: list[Report]


def open_reports(db: Session, limit: int) -> list[ReportedItem]:
    """Items with undecided reports, the longest-waiting first."""
    grouped: dict[uuid.UUID, list[Report]] = {}
    for open_report in db.scalars(
        select(Report).where(Report.decision.is_(None)).order_by(Report.created_at, Report.id)
    ):
        if open_report.submission_id not in grouped and len(grouped) == limit:
            continue
        grouped.setdefault(open_report.submission_id, []).append(open_report)
    items = db.scalars(select(Submission).where(Submission.id.in_(grouped)))
    by_id = {item.id: item for item in items}
    return [ReportedItem(by_id[item_id], reports) for item_id, reports in grouped.items()]


def _for_decision(db: Session, admin: AuthenticatedUser, submission_id: uuid.UUID) -> Submission:
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id).with_for_update()
    )
    if submission is None or submission.status == "withdrawn":
        raise ApiError(404, "submission_not_found", "Submission not found.")
    if submission.submitted_by == admin.id:
        # The database refuses this too (review_events_no_self_review).
        raise ApiError(403, "own_submission", "Another admin must decide on your own submission.")
    return submission


def _decide_reports(
    db: Session, admin: AuthenticatedUser, submission: Submission, decision: str, note: str
) -> int:
    pending = list(
        db.scalars(
            select(Report)
            .where(Report.submission_id == submission.id, Report.decision.is_(None))
            .with_for_update()
        )
    )
    now = utcnow()
    for pending_report in pending:
        pending_report.decision = decision
        pending_report.decided_by = admin.id
        pending_report.decided_at = now
        pending_report.decision_note = note
    return len(pending)


def _set_flags(submission: Submission, flags: list[str]) -> None:
    submission.restriction_flags = flags
    submission.updated_at = utcnow()


def hide(
    db: Session,
    *,
    admin: AuthenticatedUser,
    submission_id: uuid.UUID,
    restriction: str,
    note: str,
    context: RequestContext,
) -> Submission:
    """Adds a restriction flag, which takes the item out of the catalogue and of releases, and
    closes the item's open reports. Hiding something already hidden only closes the reports."""
    submission = _for_decision(db, admin, submission_id)
    if restriction not in submission.restriction_flags:
        _set_flags(submission, [*submission.restriction_flags, restriction])
        db.add(
            ReviewEvent(
                submission_id=submission.id,
                reviewer_id=admin.id,
                action="add_restriction",
                restriction=restriction,
                note=note,
            )
        )
    closed = _decide_reports(db, admin, submission, "hidden", note)
    audit.record(
        db,
        action="report.hide",
        context=context,
        actor_user_id=admin.id,
        target_type="submission",
        target_id=submission.id,
        details={"restriction": restriction, "reports_closed": closed},
    )
    db.commit()
    return submission


def dismiss(
    db: Session,
    *,
    admin: AuthenticatedUser,
    submission_id: uuid.UUID,
    note: str,
    context: RequestContext,
) -> Submission:
    """Closes the item's open reports without changing the item."""
    submission = _for_decision(db, admin, submission_id)
    closed = _decide_reports(db, admin, submission, "dismissed", note)
    if closed == 0:
        raise ApiError(409, "no_open_reports", "This item has no open reports.")
    audit.record(
        db,
        action="report.dismiss",
        context=context,
        actor_user_id=admin.id,
        target_type="submission",
        target_id=submission.id,
        details={"reports_closed": closed},
    )
    db.commit()
    return submission


def unhide(
    db: Session,
    *,
    admin: AuthenticatedUser,
    submission_id: uuid.UUID,
    restriction: str,
    note: str,
    context: RequestContext,
) -> Submission:
    submission = _for_decision(db, admin, submission_id)
    if restriction not in submission.restriction_flags:
        raise ApiError(409, "not_restricted", "This item does not have that restriction.")
    _set_flags(submission, [f for f in submission.restriction_flags if f != restriction])
    db.add(
        ReviewEvent(
            submission_id=submission.id,
            reviewer_id=admin.id,
            action="remove_restriction",
            restriction=restriction,
            note=note,
        )
    )
    audit.record(
        db,
        action="report.unhide",
        context=context,
        actor_user_id=admin.id,
        target_type="submission",
        target_id=submission.id,
        details={"restriction": restriction},
    )
    db.commit()
    return submission
