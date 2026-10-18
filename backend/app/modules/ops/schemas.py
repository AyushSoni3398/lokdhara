from datetime import datetime

from pydantic import BaseModel


class BackupStateOut(BaseModel):
    kind: str
    last_run_at: datetime | None
    last_run_succeeded: bool | None
    last_run_detail: str | None
    last_success_at: datetime | None
    last_success_bytes: int | None


class StatusOut(BaseModel):
    checked_at: datetime
    alerts: list[str]
    jobs_queued: int
    jobs_running: int
    oldest_due_job_since: datetime | None
    jobs_failed_last_day: int
    jobs_failed_waiting: int
    backups: list[BackupStateOut]
    submissions_last_day: int
    accepted_last_day: int
    rejected_last_day: int
    login_failures_last_day: int
    open_reports: int
    open_withdrawals: int
    exports_awaiting_approval: int
    database_bytes: int
    disk_used_share: float | None
