"""Job queue behaviour against real PostgreSQL (ROADMAP M2: enqueue → worker → processing_runs)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.processing import (
    handlers,  # noqa: F401 - registers system.ping
    queue,
)
from app.modules.processing.models import Job, ProcessingRun
from app.modules.processing.queue import JobContext, JobError, JobResult, enqueue, process_one
from tests.conftest import MakeUser, login, requires_postgres

pytestmark = requires_postgres

LEASE = 60.0


def _job(db: Session, job_id: object) -> Job:
    db.expire_all()
    job = db.get(Job, job_id)
    assert job is not None
    return job


@pytest.fixture
def unhandled(monkeypatch: pytest.MonkeyPatch) -> str:
    """A job type whose handler is taken away for the test."""
    monkeypatch.delitem(queue._handlers, "dataset.export")
    return "dataset.export"


def _runs(db: Session) -> list[ProcessingRun]:
    return list(db.scalars(select(ProcessingRun).order_by(ProcessingRun.finished_at)))


def test_ping_runs_end_to_end(engine: Engine, db: Session) -> None:
    job_id = enqueue(db, "system.ping")
    db.commit()
    assert process_one(engine, "w1", LEASE)
    assert not process_one(engine, "w1", LEASE)  # queue now empty
    job = _job(db, job_id)
    assert job.status == "succeeded"
    assert job.locked_by is None
    [run] = _runs(db)
    assert (run.job_id, run.status, run.attempt, run.worker_id) == (job_id, "succeeded", 1, "w1")
    assert run.output_summary == {"pong": True, "attempt": 1}


def test_enqueue_is_part_of_the_callers_transaction(engine: Engine, db: Session) -> None:
    enqueue(db, "system.ping")
    db.rollback()
    assert not process_one(engine, "w1", LEASE)


def test_dedupe_key_allows_one_pending_job(db: Session) -> None:
    first = enqueue(db, "system.ping", dedupe_key="recording:1")
    second = enqueue(db, "system.ping", dedupe_key="recording:1")
    db.commit()
    assert first is not None
    assert second is None


def test_delayed_jobs_wait(engine: Engine, db: Session) -> None:
    enqueue(db, "system.ping", delay=timedelta(minutes=5))
    db.commit()
    assert not process_one(engine, "w1", LEASE)


def test_two_workers_never_take_the_same_job(engine: Engine, db: Session) -> None:
    enqueue(db, "system.ping")
    enqueue(db, "system.ping")
    db.commit()
    first = queue.claim(engine, "w1", LEASE)
    second = queue.claim(engine, "w2", LEASE)
    assert first is not None and second is not None
    assert first.id != second.id
    assert queue.claim(engine, "w3", LEASE) is None


def test_retryable_failure_is_requeued_with_backoff(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(_: JobContext) -> JobResult:
        raise JobError("ffmpeg_timeout", "decoder timed out")

    monkeypatch.setitem(queue._handlers, "audio.validate", flaky)
    job_id = enqueue(db, "audio.validate")
    db.commit()
    assert process_one(engine, "w1", LEASE)
    job = _job(db, job_id)
    assert (job.status, job.attempts, job.last_error_code) == ("queued", 1, "ffmpeg_timeout")
    assert job.run_after > queue.utcnow() + timedelta(seconds=20)
    [run] = _runs(db)
    assert (run.status, run.error_code, run.error_detail) == (
        "failed",
        "ffmpeg_timeout",
        "decoder timed out",
    )


def test_job_fails_after_max_attempts(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: JobContext) -> JobResult:
        raise JobError("corrupt_audio")

    monkeypatch.setitem(queue._handlers, "audio.validate", broken)
    job_id = enqueue(db, "audio.validate", max_attempts=2)
    db.commit()
    for _ in range(2):
        db.execute(update(Job).values(run_after=queue.utcnow()))  # skip the backoff wait
        db.commit()
        assert process_one(engine, "w1", LEASE)
    job = _job(db, job_id)
    assert (job.status, job.attempts) == ("failed", 2)
    assert job.finished_at is not None
    assert [r.attempt for r in _runs(db)] == [1, 2]


def test_non_retryable_failure_fails_at_once(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(_: JobContext) -> JobResult:
        raise JobError("unsupported_format", retryable=False)

    monkeypatch.setitem(queue._handlers, "audio.validate", reject)
    job_id = enqueue(db, "audio.validate")
    db.commit()
    process_one(engine, "w1", LEASE)
    assert _job(db, job_id).status == "failed"


def test_unexpected_errors_store_no_message(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leaky(_: JobContext) -> JobResult:
        raise RuntimeError("could not parse transcript 'Asha Munda sang …'")

    monkeypatch.setitem(queue._handlers, "text.derive", leaky)
    enqueue(db, "text.derive")
    db.commit()
    process_one(engine, "w1", LEASE)
    [run] = _runs(db)
    assert (run.error_code, run.error_detail) == ("unexpected_error", "RuntimeError")


def test_handlers_know_the_id_of_their_run(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def remember(context: JobContext) -> JobResult:
        seen.append(context.run_id)
        if len(seen) == 1:
            raise JobError("try_again")
        return JobResult()

    monkeypatch.setitem(queue._handlers, "audio.renditions", remember)
    job_id = enqueue(db, "audio.renditions")
    db.commit()
    process_one(engine, "w1", LEASE)
    db.execute(update(Job).where(Job.id == job_id).values(run_after=text("now()")))
    db.commit()
    process_one(engine, "w1", LEASE)

    assert [run.id for run in _runs(db)] == seen
    assert seen[0] != seen[1]  # each attempt has its own run


def test_handler_writes_roll_back_on_failure(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def half_done(context: JobContext) -> JobResult:
        enqueue(context.db, "system.ping")  # a write that must not survive
        raise JobError("later_step_failed", retryable=False)

    monkeypatch.setitem(queue._handlers, "audio.analyze", half_done)
    enqueue(db, "audio.analyze")
    db.commit()
    process_one(engine, "w1", LEASE)
    assert db.scalar(select(Job).where(Job.job_type == "system.ping")) is None


def test_job_without_handler_fails(engine: Engine, db: Session, unhandled: str) -> None:
    job_id = enqueue(db, unhandled)
    db.commit()
    process_one(engine, "w1", LEASE)
    job = _job(db, job_id)
    assert (job.status, job.last_error_code) == ("failed", "no_handler")


def test_jobs_from_a_crashed_worker_are_picked_up(engine: Engine, db: Session) -> None:
    job_id = enqueue(db, "system.ping")
    db.commit()
    assert queue.claim(engine, "crashed", LEASE) is not None  # never finishes
    assert not process_one(engine, "w2", LEASE)  # lease still valid
    db.execute(update(Job).values(lock_expires_at=queue.utcnow() - timedelta(seconds=1)))
    db.commit()
    assert process_one(engine, "w2", LEASE)
    job = _job(db, job_id)
    assert (job.status, job.attempts) == ("succeeded", 2)


def test_a_worker_that_lost_its_lease_discards_its_result(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(context: JobContext) -> JobResult:
        # Meanwhile the lease expired and another worker took the job over.
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE jobs SET locked_by = 'w2' WHERE id = :id"), {"id": context.job_id}
            )
        return JobResult()

    monkeypatch.setitem(queue._handlers, "audio.renditions", slow)
    job_id = enqueue(db, "audio.renditions")
    db.commit()
    process_one(engine, "w1", LEASE)
    assert _job(db, job_id).status == "running"
    assert _runs(db) == []


def test_processing_runs_are_append_only(engine: Engine, db: Session) -> None:
    enqueue(db, "system.ping")
    db.commit()
    process_one(engine, "w1", LEASE)
    with engine.connect() as connection, pytest.raises(DBAPIError, match="append_only"):
        connection.execute(text("SET ROLE app_rw"))
        connection.execute(text("UPDATE processing_runs SET status = 'failed'"))


def test_backoff_grows_and_is_capped() -> None:
    assert [queue.backoff(n).total_seconds() for n in (1, 2, 3)] == [30, 60, 120]
    assert queue.backoff(20) == queue.MAX_BACKOFF


def test_unknown_job_types_are_rejected(db: Session) -> None:
    with pytest.raises(ValueError, match="unknown job type"):
        enqueue(db, "email.send")


# ------------------------------------------------------------------ admin API


def test_admin_lists_and_retries_failed_jobs(
    client: TestClient, make_user: MakeUser, engine: Engine, db: Session, unhandled: str
) -> None:
    job_id = enqueue(db, unhandled)  # fails for want of a handler
    db.commit()
    process_one(engine, "w1", LEASE)
    headers = {"X-CSRF-Token": login(client, make_user("admin1", "admin"))}
    listed = client.get("/api/v1/admin/jobs?status=failed").json()["items"]
    assert [item["id"] for item in listed] == [str(job_id)]
    assert listed[0]["last_error_code"] == "no_handler"
    assert "payload" not in listed[0]
    retried = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
    assert retried.status_code == 200
    assert (retried.json()["status"], retried.json()["attempts"]) == ("queued", 0)
    again = client.post(f"/api/v1/admin/jobs/{job_id}/retry", headers=headers)
    assert again.json()["code"] == "job_not_failed"
    assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "job.retry"))


def test_only_admins_see_jobs(client: TestClient, make_user: MakeUser) -> None:
    login(client, make_user("ravi", "reviewer"))
    assert client.get("/api/v1/admin/jobs").status_code == 403
