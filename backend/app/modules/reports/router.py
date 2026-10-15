"""Reports (docs/API_SPECIFICATION.md §7)."""

import uuid

from fastapi import APIRouter, status

from app.db import DbSession
from app.modules.identity.deps import Context, CurrentUser
from app.modules.reports import service
from app.modules.reports.schemas import ReportCreateRequest, ReportOut

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
