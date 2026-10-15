"""A submission moves on as its checks settle (docs/DATA_LIFECYCLE.md stage 4,
docs/ARCHITECTURE_DIAGRAM.md state machine).

Sample text is synthetic Hindi, never collected community text.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.processing import queue
from app.modules.processing.models import Job
from app.modules.processing.queue import JobContext, JobError, JobResult
from app.modules.submissions.models import Submission
from tests.conftest import MakeUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, give_consent, own_speaker

pytestmark = requires_postgres


@pytest.fixture
def submission_id(client: TestClient, make_user: MakeUser, db: Session) -> uuid.UUID:
    """A submitted text submission whose `text.derive` job is queued."""
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker)
    draft = str(create_draft(client, speaker, kind="text", recording_mode=None)["id"])
    layer = {
        "layer_type": "standalone",
        "entry_type": "sentence",
        "language_tag": "unr",
        "script_code": "Deva",
        "content": "यह एक परीक्षण वाक्य है।",
    }
    assert client.post(f"{SUBMISSIONS}/{draft}/text-layers", json=layer).status_code == 201
    assert client.post(f"{SUBMISSIONS}/{draft}/submit").status_code == 200
    return uuid.UUID(draft)


def run_jobs(engine: Engine) -> None:
    while queue.process_one(engine, "test-worker", 60):
        pass


def status(db: Session, submission_id: uuid.UUID) -> str:
    db.expire_all()
    submission = db.get(Submission, submission_id)
    assert submission is not None
    return submission.status


def test_a_submission_is_accepted_once_its_checks_succeed(
    submission_id: uuid.UUID, engine: Engine, db: Session
) -> None:
    assert status(db, submission_id) == "processing"
    run_jobs(engine)
    assert status(db, submission_id) == "accepted"


def test_a_check_that_keeps_failing_fails_the_submission_until_an_admin_retries(
    submission_id: uuid.UUID,
    client: TestClient,
    make_user: MakeUser,
    engine: Engine,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_: JobContext) -> JobResult:
        raise JobError("tool_missing", retryable=False)

    working = queue._handlers["text.derive"]
    monkeypatch.setitem(queue._handlers, "text.derive", broken)
    run_jobs(engine)
    assert status(db, submission_id) == "processing_failed"

    monkeypatch.setitem(queue._handlers, "text.derive", working)
    act_as(client, make_user("admin1", "admin"))
    [job_id] = db.scalars(select(Job.id).where(Job.target_id == submission_id))
    assert client.post(f"/api/v1/admin/jobs/{job_id}/retry").status_code == 200
    assert status(db, submission_id) == "processing"
    run_jobs(engine)
    assert status(db, submission_id) == "accepted"


def test_a_retried_failure_keeps_the_submission_processing(
    submission_id: uuid.UUID, engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(_: JobContext) -> JobResult:
        raise JobError("storage_unavailable")  # retryable: the job is queued again

    monkeypatch.setitem(queue._handlers, "text.derive", flaky)
    queue.process_one(engine, "test-worker", 60)
    assert status(db, submission_id) == "processing"


def test_a_failing_status_update_fails_the_job_instead_of_losing_it(
    submission_id: uuid.UUID, engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_db: Session, _job: Job) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(queue, "_listeners", [broken])
    queue.process_one(engine, "test-worker", 60)
    [job] = db.scalars(select(Job).where(Job.target_id == submission_id))
    assert (job.status, job.last_error_code) == ("queued", "unexpected_error")
    assert status(db, submission_id) == "processing"
