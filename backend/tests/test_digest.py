"""The daily digest to the maintainers (docs/OBSERVABILITY_AND_BACKUPS.md §2)."""

import smtplib
from email.message import EmailMessage
from types import TracebackType
from typing import ClassVar

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.ops import digest
from app.modules.processing import queue
from app.modules.processing.models import ProcessingRun
from tests.conftest import requires_postgres
from tests.test_ops_status import healthy


def test_a_quiet_day_says_all_is_well() -> None:
    subject, body = digest.render(healthy(), "https://lokdhara.example.org")
    assert subject == "Lokdhara: all well"
    assert "Nothing needs attention." in body
    assert "12 submissions sent, 10 accepted, 1 rejected" in body
    assert "https://lokdhara.example.org/admin/status" in body


def test_alerts_come_first_in_plain_words() -> None:
    status = healthy(alerts=["backup_missing:database", "jobs_failed"])
    subject, body = digest.render(status, "https://lokdhara.example.org/")
    assert subject == "Lokdhara: 2 things need attention"
    attention = body.split("Needs attention:\n")[1].split("\n\n")[0]
    assert attention.splitlines() == [
        "  - No successful database backup in the last 26 hours.",
        "  - Jobs failed for good in the last 24 hours (Failed checks page).",
    ]


def test_every_alert_has_words() -> None:
    from app.modules.ops.models import KINDS

    codes = {f"backup_{what}:{kind}" for what in ("missing", "failed") for kind in KINDS}
    codes |= {"backup_not_off_site", "queue_behind", "jobs_failed", "disk_nearly_full"}
    assert codes | {"many_failed_sign_ins"} == set(digest.ALERT_TEXT)


class FakeSmtp:
    sent: ClassVar[list[EmailMessage]] = []
    fail: ClassVar[bool] = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls = [("connect", host, port)]

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        pass

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        assert (user, password) == ("digest", "mail-secret")

    def send_message(self, message: EmailMessage) -> None:
        if self.fail:
            raise smtplib.SMTPServerDisconnected("gone")
        self.sent.append(message)


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> type[FakeSmtp]:
    FakeSmtp.sent, FakeSmtp.fail = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(digest, "get_settings", lambda: settings)
    return FakeSmtp


def _run_digest(engine: Engine, db: Session) -> ProcessingRun:
    queue.enqueue(db, "ops.digest")
    db.commit()
    while queue.process_one(engine, "test-worker", 60):
        pass
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.job_type == "ops.digest"))
    assert run is not None
    return run


@requires_postgres
def test_without_mail_settings_the_digest_is_only_logged(
    engine: Engine, db: Session, mail: type[FakeSmtp]
) -> None:
    run = _run_digest(engine, db)
    assert (run.status, run.output_summary["sent"]) == ("succeeded", False)
    assert mail.sent == []


@requires_postgres
def test_the_digest_is_mailed_to_the_maintainers(
    engine: Engine, db: Session, mail: type[FakeSmtp], settings: Settings
) -> None:
    settings.smtp_host, settings.smtp_username = "smtp.example.org", "digest"
    settings.smtp_password = SecretStr("mail-secret")
    settings.digest_recipients = "a@example.org, b@example.org"
    run = _run_digest(engine, db)
    assert run.output_summary == {"sent": True, "recipients": 2, "alerts": 2}
    (message,) = mail.sent
    assert message["To"] == "a@example.org, b@example.org"
    assert message["Subject"] == "Lokdhara: 2 things need attention"


@requires_postgres
def test_a_mail_failure_is_retried_without_details(
    engine: Engine, db: Session, mail: type[FakeSmtp], settings: Settings
) -> None:
    settings.smtp_host, settings.digest_recipients = "smtp.example.org", "a@example.org"
    mail.fail = True
    queue.enqueue(db, "ops.digest")
    db.commit()
    queue.process_one(engine, "test-worker", 60)
    error = db.execute(text("SELECT error_code, error_detail FROM processing_runs")).one()
    assert tuple(error) == ("digest_not_sent", "SMTPServerDisconnected")
