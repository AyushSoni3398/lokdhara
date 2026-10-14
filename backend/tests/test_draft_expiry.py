"""Audio of drafts left unsent for 30 days is deleted and can be uploaded again (Q-T7)."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.processing import queue, schedule
from app.modules.processing.models import Job
from app.modules.submissions import expiry
from app.modules.submissions.models import Recording
from app.object_store import Bucket, ObjectStore
from tests.conftest import MakeUser, act_as, requires_postgres
from tests.submission_helpers import (
    FAKE_WEBM,
    SUBMISSIONS,
    create_draft,
    give_consent,
    own_speaker,
    upload,
)

pytestmark = requires_postgres

KEY = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def worker_services(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, object_store: ObjectStore
) -> None:
    monkeypatch.setattr(expiry, "get_settings", lambda: settings)
    monkeypatch.setattr(expiry, "get_object_store", lambda: object_store)


@pytest.fixture
def speaker(client: TestClient, make_user: MakeUser, db: Session) -> str:
    act_as(client, make_user("asha", "contributor"))
    speaker_id = own_speaker(client)
    give_consent(client, db, speaker_id)
    return speaker_id


def _draft_with_audio(client: TestClient, speaker: str) -> tuple[str, uuid.UUID]:
    draft = str(create_draft(client, speaker)["id"])
    response = upload(client, draft, key=KEY)
    assert response.status_code == 202, response.text
    return draft, uuid.UUID(response.json()["recording_id"])


def _age(db: Session, recording_id: uuid.UUID, days: int) -> None:
    db.execute(
        text(
            "UPDATE recordings SET quarantined_at = now() - make_interval(days => :days) "
            "WHERE id = :id"
        ),
        {"days": days, "id": recording_id},
    )
    db.commit()


def _sweep(db: Session, engine: Engine) -> None:
    queue.enqueue(db, "cleanup.expire_drafts")
    db.commit()
    while queue.process_one(engine, "test-worker", 60):
        pass


def _recording(db: Session, recording_id: uuid.UUID) -> Recording:
    db.expire_all()
    recording = db.get(Recording, recording_id)
    assert recording is not None
    return recording


def _in_quarantine(store: ObjectStore, recording: Recording) -> bool:
    return store.head(Bucket.QUARANTINE, recording.original_object_key) is not None


def test_audio_of_a_draft_unsent_for_30_days_is_deleted_but_the_draft_stays(
    client: TestClient, speaker: str, db: Session, engine: Engine, object_store: ObjectStore
) -> None:
    draft, recording_id = _draft_with_audio(client, speaker)
    _age(db, recording_id, days=31)
    _sweep(db, engine)

    recording = _recording(db, recording_id)
    assert recording.upload_status == "expired"
    assert not _in_quarantine(object_store, recording)
    assert client.get(f"{SUBMISSIONS}/{draft}").json()["status"] == "draft"
    submitted = client.post(f"{SUBMISSIONS}/{draft}/submit").json()
    assert submitted["code"] == "recording_expired"


def test_newer_uploads_and_submitted_drafts_are_kept(
    client: TestClient, speaker: str, db: Session, engine: Engine, object_store: ObjectStore
) -> None:
    _, fresh = _draft_with_audio(client, speaker)
    _age(db, fresh, days=29)
    sent, old_but_sent = _draft_with_audio(client, speaker)
    assert client.post(f"{SUBMISSIONS}/{sent}/submit").status_code == 200
    _age(db, old_but_sent, days=31)
    # Only the sweep runs: validation of the submitted one is not what this test is about.
    db.execute(text("DELETE FROM jobs"))
    _sweep(db, engine)

    for recording_id in (fresh, old_but_sent):
        recording = _recording(db, recording_id)
        assert recording.upload_status == "quarantined"
        assert _in_quarantine(object_store, recording)


def test_uploading_the_same_file_again_restores_the_same_recording(
    client: TestClient, speaker: str, db: Session, engine: Engine, object_store: ObjectStore
) -> None:
    draft, recording_id = _draft_with_audio(client, speaker)
    _age(db, recording_id, days=31)
    _sweep(db, engine)

    again = upload(client, draft, key=KEY)
    assert again.status_code == 202
    assert again.json() == {"recording_id": str(recording_id), "upload_status": "quarantined"}
    recording = _recording(db, recording_id)
    assert _in_quarantine(object_store, recording)
    _sweep(db, engine)  # the 30 days start again
    assert _recording(db, recording_id).upload_status == "quarantined"
    assert client.post(f"{SUBMISSIONS}/{draft}/submit").json()["status"] == "processing"


def test_a_different_file_cannot_replace_the_expired_one(
    client: TestClient, speaker: str, db: Session, engine: Engine, object_store: ObjectStore
) -> None:
    draft, recording_id = _draft_with_audio(client, speaker)
    _age(db, recording_id, days=31)
    _sweep(db, engine)

    other = upload(client, draft, content=FAKE_WEBM + b"\x00", key=KEY)
    assert other.json()["code"] == "recording_changed"
    recording = _recording(db, recording_id)
    assert recording.upload_status == "expired"
    assert not _in_quarantine(object_store, recording)


def test_a_lost_quarantine_copy_of_a_draft_can_be_uploaded_again(
    client: TestClient, speaker: str, db: Session, object_store: ObjectStore
) -> None:
    draft, recording_id = _draft_with_audio(client, speaker)
    object_store.delete(Bucket.QUARANTINE, _recording(db, recording_id).original_object_key)
    assert client.post(f"{SUBMISSIONS}/{draft}/submit").json()["code"] == "recording_missing"

    assert upload(client, draft, key=KEY).status_code == 202
    assert _in_quarantine(object_store, _recording(db, recording_id))
    assert client.post(f"{SUBMISSIONS}/{draft}/submit").json()["status"] == "processing"


def test_the_sweep_is_queued_once_an_hour(db: Session) -> None:
    now = queue.utcnow()
    assert schedule.enqueue_due(db, now) == ["cleanup.expire_drafts"]
    assert schedule.enqueue_due(db, now) == []  # still pending
    db.execute(text("UPDATE jobs SET status = 'succeeded'"))
    db.commit()
    assert schedule.enqueue_due(db, now + timedelta(minutes=59)) == []
    assert schedule.enqueue_due(db, now + timedelta(minutes=61)) == ["cleanup.expire_drafts"]


def test_the_scheduler_checks_at_most_once_a_minute(engine: Engine, db: Session) -> None:
    clock = [0.0]
    scheduler = schedule.Scheduler(engine, check_every_seconds=60, clock=lambda: clock[0])
    scheduler.tick()
    db.execute(text("DELETE FROM jobs"))
    db.commit()
    clock[0] = 59
    scheduler.tick()
    assert db.scalars(select(Job)).all() == []
    clock[0] = 60
    scheduler.tick()
    assert [job.job_type for job in db.scalars(select(Job))] == ["cleanup.expire_drafts"]
