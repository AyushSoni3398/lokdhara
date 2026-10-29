"""The deletion routine that follows a verified withdrawal (docs/DATA_RETENTION_AND_DELETION.md
§2.6). Synthetic data only: a tone made by FFmpeg and invented text."""

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.consents import service as consents
from app.modules.consents.models import ConsentRecord, WithdrawalRequest
from app.modules.processing import queue
from app.modules.releases.freeze import stored_file_key
from app.modules.speakers.models import Speaker, SpeakerIdentity
from app.modules.submissions import processing
from app.modules.submissions.models import Recording, Rendition, Submission
from app.modules.withdrawals import erasure
from app.object_store import Bucket, ObjectStore
from tests.audio_fixtures import make_audio, requires_ffmpeg
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import (
    SUBMISSIONS,
    accepted_text_item,
    create_draft,
    give_consent,
    own_speaker,
    upload,
)

pytestmark = [requires_postgres, requires_ffmpeg]

QUEUE = "/api/v1/admin/withdrawal-requests"
CHECKED = {"note": "Confirmed in person by the facilitator."}


@pytest.fixture(autouse=True)
def worker_uses_test_storage(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, object_store: ObjectStore
) -> Iterator[None]:
    for module in (processing, erasure):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "get_object_store", lambda: object_store)
    yield


def run_jobs(engine: Engine) -> None:
    while queue.process_one(engine, "test-worker", 60):
        pass


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


def oral_consent(client: TestClient, db: Session, speaker_id: str) -> None:
    consents.ensure_dev_forms(db)
    db.commit()
    form = consents.current_form(db, Settings(_env_file=None, env="test"), "hi")
    answers = {
        "consent_form_id": str(form.id),
        "method": "oral_recorded",
        "allow_store_and_review": True,
        "allow_research": True,
        "notes": "Recorded at the village meeting.",
    }
    response = client.post(
        f"/api/v1/speakers/{speaker_id}/consents",
        data={"consent": json.dumps(answers)},
        files={"evidence": ("consent.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm")},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def world(
    client: TestClient,
    engine: Engine,
    db: Session,
    make_user: MakeUser,
    admin: TestUser,
    tmp_path: Path,
) -> dict[str, Any]:
    """asha: oral consent, identity details, a recording and a text item, both in a frozen
    release. ravi: one text item that must stay untouched."""
    asha = make_user("asha", "contributor")
    act_as(client, asha)
    speaker = own_speaker(client)
    oral_consent(client, db, speaker)
    draft = create_draft(client, speaker, title="Story of the river")
    assert upload(client, draft["id"], make_audio(tmp_path / "a", seconds=2)).status_code == 202
    assert client.post(f"{SUBMISSIONS}/{draft['id']}/submit").status_code == 200
    story = accepted_text_item(client, engine, speaker, "नदी के किनारे")
    run_jobs(engine)
    assert client.get(f"{SUBMISSIONS}/{draft['id']}").json()["status"] == "accepted"

    act_as(client, make_user("ravi", "contributor"))
    ravi = own_speaker(client)
    give_consent(client, db, ravi, allow_research=True)
    other = accepted_text_item(client, engine, ravi, "दूसरा वाक्य")

    act_as(client, admin)
    identity = {"full_name": "Synthetic Name", "contact": "000-TEST", "village": "Test Village"}
    assert client.put(f"/api/v1/speakers/{speaker}/identity", json=identity).status_code == 200
    made = client.post(
        "/api/v1/datasets", json={"slug": "mundari-pilot", "purpose": "internal_research"}
    ).json()
    frozen = client.post(f"/api/v1/datasets/{made['id']}/freeze", json={"version": "0.1.0"})
    assert frozen.status_code == 200, frozen.text
    return {
        "asha": asha,
        "speaker": speaker,
        "audio": draft["id"],
        "story": story,
        "other": other,
        "release": frozen.json()["id"],
    }


def verified(client: TestClient, admin: TestUser, **body: Any) -> str:
    act_as(client, admin)
    request = client.post("/api/v1/withdrawal-requests", json=body).json()
    response = client.post(f"{QUEUE}/{request['id']}/verify", json=CHECKED)
    assert response.status_code == 200, response.text
    return str(request["id"])


def files_of(db: Session, submission_id: str) -> list[tuple[Bucket, str]]:
    recordings = db.scalars(
        select(Recording).where(Recording.submission_id == uuid.UUID(submission_id))
    ).all()
    found = [(Bucket.ORIGINALS, r.original_object_key) for r in recordings]
    renditions = db.scalars(
        select(Rendition).where(Rendition.recording_id.in_([r.id for r in recordings]))
    ).all()
    return found + [(Bucket.DERIVED, r.object_key) for r in renditions]


def texts_of(db: Session, submission_id: str) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT r.content_original FROM text_revisions r "
                "JOIN text_layers l ON l.id = r.layer_id WHERE l.submission_id = :id"
            ),
            {"id": submission_id},
        )
    )


def test_a_full_withdrawal_deletes_the_speakers_files_and_words(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    world: dict[str, Any],
    admin: TestUser,
) -> None:
    files = files_of(db, world["audio"])
    assert len(files) == 5  # the original and four derived files
    release_id = uuid.UUID(world["release"])
    items_list = stored_file_key(release_id, "items.jsonl")
    spreadsheet = stored_file_key(release_id, "metadata.csv")
    assert object_store.head(Bucket.EXPORTS, items_list) is not None
    assert object_store.head(Bucket.EXPORTS, spreadsheet) is not None

    request_id = verified(client, admin, scope="full", speaker_id=world["speaker"])
    run_jobs(engine)
    db.expire_all()

    assert all(object_store.head(bucket, key) is None for bucket, key in files)
    assert object_store.head(Bucket.EXPORTS, items_list) is None
    assert object_store.head(Bucket.EXPORTS, spreadsheet) is None
    assert object_store.head(Bucket.EXPORTS, stored_file_key(release_id, "manifest.json"))
    assert {r.upload_status for r in db.scalars(select(Recording))} == {"erased"}
    assert texts_of(db, world["story"]) == [""]
    assert texts_of(db, world["other"]) == ["दूसरा वाक्य"]
    audio = db.get_one(Submission, uuid.UUID(world["audio"]))
    assert (audio.title, audio.collection_context) == (None, {})

    speaker_id = uuid.UUID(world["speaker"])
    assert db.get(SpeakerIdentity, speaker_id) is None
    record = db.scalar(select(ConsentRecord).where(ConsentRecord.speaker_id == speaker_id))
    assert record is not None and record.notes is None
    # Proof of consent stays until the institution decides otherwise (Q-G8).
    assert object_store.head(Bucket.CONSENT_EVIDENCE, record.evidence_object_key or "")

    request = db.get_one(WithdrawalRequest, uuid.UUID(request_id))
    assert request.erased_at is not None
    done = request.actions_taken[-1]
    assert (done["action"], done["items"], done["recordings"], done["files"]) == (
        "erased",
        2,
        1,
        8,  # quarantine copy, original, four derived files, a release's two item lists
    )
    assert (done["identity_deleted"], done["consent_evidence"]) == (True, "kept")
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "withdrawal.erase"))
    assert event is not None and event.actor_type == "worker"

    # Running the routine again changes nothing.
    queue.enqueue(db, "withdrawal.erase", target_type="withdrawal_request", target_id=request.id)
    db.commit()
    run_jobs(engine)
    db.expire_all()
    assert len(db.get_one(WithdrawalRequest, request.id).actions_taken) == 2


def test_a_request_is_completed_once_its_items_are_deleted(
    client: TestClient, engine: Engine, db: Session, world: dict[str, Any], admin: TestUser
) -> None:
    request_id = verified(client, admin, scope="specific_items", submission_id=world["audio"])
    complete = f"{QUEUE}/{request_id}/complete"
    told = {"note": "Told the speaker by phone that the recording was deleted."}
    assert client.post(complete, json=told).json()["code"] == "erasure_pending"
    run_jobs(engine)
    done = client.post(complete, json=told).json()
    assert (done["status"], done["actions_taken"][-1]["note"]) == ("completed", told["note"])
    assert done["completed_at"] is not None
    assert client.post(complete, json=told).json()["code"] == "withdrawal_decided"
    assert client.get(QUEUE).json()["items"] == []
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "withdrawal.complete"))


def test_consent_evidence_is_deleted_when_the_project_does_not_keep_it(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    settings: Settings,
    world: dict[str, Any],
    admin: TestUser,
) -> None:
    settings.withdrawal_keep_consent_evidence = False
    request_id = verified(client, admin, scope="full", speaker_id=world["speaker"])
    run_jobs(engine)
    record = db.scalar(
        select(ConsentRecord).where(ConsentRecord.speaker_id == uuid.UUID(world["speaker"]))
    )
    assert record is not None
    assert object_store.head(Bucket.CONSENT_EVIDENCE, record.evidence_object_key or "") is None
    request = db.get_one(WithdrawalRequest, uuid.UUID(request_id), populate_existing=True)
    assert request.actions_taken[-1]["consent_evidence"] == "deleted"


def test_one_withdrawn_item_is_erased_and_the_rest_kept(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    world: dict[str, Any],
    admin: TestUser,
) -> None:
    files = files_of(db, world["audio"])
    verified(client, admin, scope="specific_items", submission_id=world["audio"])
    run_jobs(engine)
    db.expire_all()
    assert all(object_store.head(bucket, key) is None for bucket, key in files)
    assert texts_of(db, world["story"]) == ["नदी के किनारे"]
    speaker_id = uuid.UUID(world["speaker"])
    assert db.get(SpeakerIdentity, speaker_id) is not None
    assert db.get_one(Speaker, speaker_id).status == "active"


# ------------------------------------------------------------------ database roles


@pytest.fixture
def login_role(engine: Engine) -> Iterator[Callable[[str], Engine]]:
    """Makes a login role in the given group and an engine that connects as it."""
    made: list[tuple[str, Engine]] = []

    def make(group: str) -> Engine:
        name = f"lkd_test_{uuid.uuid4().hex[:8]}"
        with engine.begin() as connection:
            connection.execute(text(f"CREATE ROLE {name} LOGIN PASSWORD 'test' IN ROLE {group}"))
        url = make_url(str(engine.url.render_as_string(hide_password=False))).set(
            username=name, password="test"
        )
        role_engine = create_engine(url)
        made.append((name, role_engine))
        return role_engine

    yield make
    for name, role_engine in made:
        role_engine.dispose()
        with engine.begin() as connection:
            connection.execute(text(f"DROP OWNED BY {name}"))
            connection.execute(text(f"DROP ROLE {name}"))


def test_only_an_app_erasure_login_runs_the_routine(
    client: TestClient,
    db: Session,
    object_store: ObjectStore,
    world: dict[str, Any],
    admin: TestUser,
    login_role: Callable[[str], Engine],
) -> None:
    request_id = uuid.UUID(verified(client, admin, scope="full", speaker_id=world["speaker"]))
    with (
        Session(login_role("app_rw")) as api_login,
        api_login.begin(),
        pytest.raises(DBAPIError, match="permission denied to set role"),
    ):
        erasure.erase(api_login, object_store, request_id)
    with Session(login_role("app_erasure")) as eraser, eraser.begin():
        assert erasure.erase(eraser, object_store, request_id) is not None
    db.expire_all()
    assert db.get_one(WithdrawalRequest, request_id).erased_at is not None


# ------------------------------------------------------------------ withdrawn while being checked


def stored_files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "objects").rglob("*") if p.is_file()]


@pytest.fixture
def sent_recording(
    client: TestClient, db: Session, make_user: MakeUser, tmp_path: Path
) -> dict[str, str]:
    """A recording that was sent but whose checks have not run yet."""
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    draft = create_draft(client, speaker)
    assert upload(client, draft["id"], make_audio(tmp_path / "a", seconds=2)).status_code == 202
    assert client.post(f"{SUBMISSIONS}/{draft['id']}/submit").status_code == 200
    return {"speaker": speaker, "submission": draft["id"]}


def test_an_item_withdrawn_while_being_checked_leaves_no_files(
    client: TestClient,
    engine: Engine,
    db: Session,
    admin: TestUser,
    sent_recording: dict[str, str],
    tmp_path: Path,
) -> None:
    verified(client, admin, scope="specific_items", submission_id=sent_recording["submission"])
    run_jobs(engine)
    assert stored_files(tmp_path) == []
    failed = db.scalars(text("SELECT job_type FROM jobs WHERE status = 'failed'")).all()
    assert failed == []


def test_a_copy_made_while_the_routine_ran_is_deleted_again(
    client: TestClient,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    sent_recording: dict[str, str],
    tmp_path: Path,
) -> None:
    promote = processing._promote

    def promote_then_erased(store: ObjectStore, key: str, sha256: str) -> None:
        promote(store, key, sha256)
        with engine.begin() as connection:  # the deletion routine finishes meanwhile
            connection.execute(text("UPDATE recordings SET upload_status = 'erased'"))

    monkeypatch.setattr(processing, "_promote", promote_then_erased)
    run_jobs(engine)
    buckets = {p.relative_to(tmp_path / "objects").parts[0] for p in stored_files(tmp_path)}
    assert "test-originals" not in buckets
