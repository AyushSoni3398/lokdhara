"""How the service is doing, for the admin status page and the daily digest.

docs/OBSERVABILITY_AND_BACKUPS.md §2. Counts and times only: nothing here names a person or
shows contributed content. `alerts()` is a pure function so each threshold is easy to test.
"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.modules.audit.models import AuditEvent
from app.modules.consents.models import WithdrawalRequest
from app.modules.ops.models import KINDS, BackupRun
from app.modules.processing.models import Job
from app.modules.releases.models import ExportRequest
from app.modules.reports.models import Report
from app.modules.submissions.models import Submission

# Alert thresholds (docs/OBSERVABILITY_AND_BACKUPS.md §2).
QUEUE_BEHIND = timedelta(hours=1)
BACKUP_MAX_AGE = {"database": timedelta(hours=26), "withdrawal_log": timedelta(hours=2)}
DISK_FULL_SHARE = 0.8
LOGIN_FAILURES_PER_DAY = 50
LOCAL_ONLY_DETAIL = "kept on this server only"  # written by backup.sh without BACKUP_REMOTE


@dataclass(frozen=True)
class BackupState:
    kind: str
    last_run_at: datetime | None
    last_run_succeeded: bool | None
    last_run_detail: str | None
    last_success_at: datetime | None
    last_success_bytes: int | None


@dataclass(frozen=True)
class Status:
    checked_at: datetime
    jobs_queued: int
    jobs_running: int
    oldest_due_job_since: datetime | None
    jobs_failed_last_day: int
    jobs_failed_waiting: int
    backups: dict[str, BackupState]
    submissions_last_day: int
    accepted_last_day: int
    rejected_last_day: int
    login_failures_last_day: int
    open_reports: int
    open_withdrawals: int
    exports_awaiting_approval: int
    database_bytes: int
    disk_used_share: float | None
    alerts: list[str] = field(default_factory=list)


def _count(db: Session, statement: Executable) -> int:
    return int(db.scalar(statement) or 0)


def _backup_state(db: Session, kind: str) -> BackupState:
    last = db.scalar(
        select(BackupRun).where(BackupRun.kind == kind).order_by(BackupRun.finished_at.desc())
    )
    success = db.scalar(
        select(BackupRun)
        .where(BackupRun.kind == kind, BackupRun.succeeded)
        .order_by(BackupRun.finished_at.desc())
    )
    return BackupState(
        kind=kind,
        last_run_at=last.finished_at if last else None,
        last_run_succeeded=last.succeeded if last else None,
        last_run_detail=last.detail if last else None,
        last_success_at=success.finished_at if success else None,
        last_success_bytes=success.size_bytes if success else None,
    )


def disk_used_share(path: Path = Path("/")) -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.used / usage.total if usage.total else None


def alerts(status: Status) -> list[str]:
    """Codes for what needs an admin's attention, most urgent first."""
    found: list[str] = []
    now = status.checked_at
    for kind in KINDS:
        backup = status.backups[kind]
        if backup.last_success_at is None or now - backup.last_success_at > BACKUP_MAX_AGE[kind]:
            found.append(f"backup_missing:{kind}")
        elif backup.last_run_succeeded is False:
            found.append(f"backup_failed:{kind}")
    database = status.backups["database"]
    if database.last_run_detail and database.last_run_detail.startswith(LOCAL_ONLY_DETAIL):
        found.append("backup_not_off_site")
    if status.oldest_due_job_since and now - status.oldest_due_job_since > QUEUE_BEHIND:
        found.append("queue_behind")
    if status.jobs_failed_last_day:
        found.append("jobs_failed")
    if status.disk_used_share is not None and status.disk_used_share > DISK_FULL_SHARE:
        found.append("disk_nearly_full")
    if status.login_failures_last_day > LOGIN_FAILURES_PER_DAY:
        found.append("many_failed_sign_ins")
    return found


def collect(db: Session, now: datetime, disk_share: float | None) -> Status:
    day_ago = now - timedelta(days=1)
    jobs_by_status: dict[str, int] = {
        job_status: count
        for job_status, count in db.execute(select(Job.status, func.count()).group_by(Job.status))
    }
    status = Status(
        checked_at=now,
        jobs_queued=jobs_by_status.get("queued", 0),
        jobs_running=jobs_by_status.get("running", 0),
        oldest_due_job_since=db.scalar(
            select(func.min(Job.run_after)).where(Job.status == "queued", Job.run_after <= now)
        ),
        jobs_failed_last_day=_count(
            db,
            select(func.count())
            .select_from(Job)
            .where(Job.status == "failed", Job.finished_at >= day_ago),
        ),
        jobs_failed_waiting=jobs_by_status.get("failed", 0),
        backups={kind: _backup_state(db, kind) for kind in KINDS},
        submissions_last_day=_count(
            db,
            select(func.count()).select_from(Submission).where(Submission.submitted_at >= day_ago),
        ),
        accepted_last_day=_count(
            db,
            select(func.count())
            .select_from(Submission)
            .where(Submission.status == "accepted", Submission.updated_at >= day_ago),
        ),
        rejected_last_day=_count(
            db,
            select(func.count())
            .select_from(Submission)
            .where(Submission.status == "rejected_invalid", Submission.updated_at >= day_ago),
        ),
        login_failures_last_day=_count(
            db,
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "auth.login_failed", AuditEvent.occurred_at >= day_ago),
        ),
        open_reports=_count(
            db, select(func.count()).select_from(Report).where(Report.decision.is_(None))
        ),
        open_withdrawals=_count(
            db,
            select(func.count())
            .select_from(WithdrawalRequest)
            .where(WithdrawalRequest.status.in_(("received", "verified", "in_progress"))),
        ),
        exports_awaiting_approval=_count(
            db,
            select(func.count())
            .select_from(ExportRequest)
            .where(ExportRequest.status == "requested"),
        ),
        database_bytes=_count(db, text("SELECT pg_database_size(current_database())")),
        disk_used_share=disk_share,
    )
    status.alerts.extend(alerts(status))
    return status
