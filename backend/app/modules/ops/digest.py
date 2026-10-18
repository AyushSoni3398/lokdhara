"""The daily digest: one short email to the maintainers about the service (M8).

docs/OBSERVABILITY_AND_BACKUPS.md §2. It holds counts and times only, never names, contacts or
contributed content, so it can go through an ordinary mail provider. Without mail settings the
worker only logs that a digest was made; the same facts are on the admin status page.
"""

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from app.config import Settings, get_settings
from app.modules.ops.status import Status, collect, disk_used_share
from app.modules.processing.queue import JobContext, JobError, JobResult, handler, utcnow

log = logging.getLogger("lokdhara.digest")

ALERT_TEXT = {
    "backup_missing:database": "No successful database backup in the last 26 hours.",
    "backup_missing:withdrawal_log": "No successful withdrawal log backup in the last 2 hours.",
    "backup_failed:database": "The last database backup failed.",
    "backup_failed:withdrawal_log": "The last withdrawal log backup failed.",
    "backup_not_off_site": "Backups are kept on the server only: no off-site copy is set up.",
    "queue_behind": "A job has been waiting for more than an hour: is the worker running?",
    "jobs_failed": "Jobs failed for good in the last 24 hours (Failed checks page).",
    "disk_nearly_full": "The server disk is more than 80% full.",
    "many_failed_sign_ins": "Unusually many failed sign-ins in the last 24 hours.",
}


def _when(moment: datetime | None) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment else "never"


def render(status: Status, base_url: str) -> tuple[str, str]:
    """The subject and plain-text body of the digest."""
    attention = [ALERT_TEXT.get(code, code) for code in status.alerts]
    subject = (
        f"Lokdhara: {len(attention)} thing{'s' if len(attention) != 1 else ''} need attention"
        if attention
        else "Lokdhara: all well"
    )
    database, log_backup = status.backups["database"], status.backups["withdrawal_log"]
    lines = [
        f"Daily summary for {base_url}, {status.checked_at:%Y-%m-%d %H:%M} UTC.",
        "",
        "Needs attention:" if attention else "Nothing needs attention.",
        *(f"  - {text}" for text in attention),
        "",
        "Last 24 hours:",
        f"  {status.submissions_last_day} submissions sent, {status.accepted_last_day} accepted, "
        f"{status.rejected_last_day} rejected by the automatic checks",
        f"  {status.jobs_failed_last_day} jobs failed, {status.login_failures_last_day} failed "
        "sign-ins",
        "",
        "Waiting for an admin:",
        f"  {status.open_reports} reports, {status.open_withdrawals} withdrawal requests, "
        f"{status.exports_awaiting_approval} export requests",
        "",
        "Backups:",
        f"  Database: last success {_when(database.last_success_at)}",
        f"  Withdrawal log: last success {_when(log_backup.last_success_at)}",
        "",
        f"Jobs: {status.jobs_queued} queued, {status.jobs_running} running, "
        f"{status.jobs_failed_waiting} failed and waiting for a retry.",
        f"Database size: {status.database_bytes / 1_000_000:.0f} MB."
        + (
            f" Disk {status.disk_used_share:.0%} full."
            if status.disk_used_share is not None
            else ""
        ),
        "",
        f"Details: {base_url.rstrip('/')}/admin/status",
    ]
    return subject, "\n".join(lines) + "\n"


def send(settings: Settings, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from or settings.smtp_username or "lokdhara@localhost"
    message["To"] = ", ".join(settings.digest_recipient_list)
    message.set_content(body)
    assert settings.smtp_host is not None  # noqa: S101 - checked by the caller
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


@handler("ops.digest")
def send_digest(context: JobContext) -> JobResult:
    settings = get_settings()
    status = collect(context.db, utcnow(), disk_used_share())
    subject, body = render(status, settings.base_url)
    recipients = settings.digest_recipient_list
    if not (settings.smtp_host and recipients):
        log.info("digest made but not sent: no mail server or recipients set")
        return JobResult(output_summary={"sent": False, "alerts": len(status.alerts)})
    try:
        send(settings, subject, body)
    except (OSError, smtplib.SMTPException) as exc:
        raise JobError("digest_not_sent", type(exc).__name__) from exc
    return JobResult(
        output_summary={"sent": True, "recipients": len(recipients), "alerts": len(status.alerts)}
    )
