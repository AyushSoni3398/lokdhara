"""Listen and write (ADR-035): contributors write down other people's recordings in
Devanagari, with optional Hindi and English translations. All data is synthetic."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.processing import queue
from app.modules.submissions import processing
from app.modules.submissions.models import Recording, Submission, TextLayer, TextRevision
from app.object_store import ObjectStore
from tests.audio_fixtures import make_audio, requires_ffmpeg
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, give_consent, own_speaker, upload

pytestmark = [requires_postgres, requires_ffmpeg]
NEXT = "/api/v1/clips/next"
HEARD = "एनेम सेनोः तना"
# "Nag Mundari" letters (U+1E4D0 block), as the Mundari Bani keyboard types them.
NAG_MUNDARI = "\U0001e4d0\U0001e4d1\U0001e4d2 \U0001e4d3\U0001e4d4"


@pytest.fixture(autouse=True)
def worker_uses_test_storage(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, object_store: ObjectStore
) -> Iterator[None]:
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(processing, "get_object_store", lambda: object_store)
    yield


def run_jobs(engine: Engine) -> None:
    while queue.process_one(engine, "test-worker", 60):
        pass


@pytest.fixture
def asha(make_user: MakeUser) -> TestUser:
    return make_user("asha", "contributor")


@pytest.fixture
def ravi(make_user: MakeUser) -> TestUser:
    return make_user("ravi", "contributor")


def record(
    client: TestClient,
    db: Session,
    engine: Engine,
    tmp_path: Path,
    *,
    public: bool = True,
    **fields: str,
) -> uuid.UUID:
    """The signed-in person records one accepted clip of their own voice."""
    speaker = own_speaker(client) if not _speakers(client) else _speakers(client)[0]
    give_consent(client, db, speaker, allow_research=True, allow_public_access=public)
    draft = create_draft(client, speaker, **fields)
    audio = make_audio(tmp_path / str(uuid.uuid4()), "m4a", seconds=2)
    recording_id = uuid.UUID(upload(client, draft["id"], audio).json()["recording_id"])
    assert client.post(f"{SUBMISSIONS}/{draft['id']}/submit").status_code == 200
    run_jobs(engine)
    db.expire_all()
    assert db.get_one(Submission, uuid.UUID(draft["id"])).status == "accepted"
    return recording_id


def _speakers(client: TestClient) -> list[str]:
    items = client.get("/api/v1/speakers", params={"mine": "true"}).json()["items"]
    return [str(s["id"]) for s in items if s["is_self"]]


def test_a_listener_gets_someone_elses_clip_and_writes_it_down(
    client: TestClient, db: Session, engine: Engine, tmp_path: Path, asha: TestUser, ravi: TestUser
) -> None:
    act_as(client, asha)
    clip_id = record(client, db, engine, tmp_path)
    # Your own voice is never handed to you.
    assert client.get(NEXT).json()["code"] == "no_clip_available"

    act_as(client, ravi)
    clip = client.get(NEXT).json()
    assert clip["recording_id"] == str(clip_id)
    assert [s["content_type"] for s in clip["sources"]] == ["audio/webm", "audio/mp4"]
    assert set(clip) == {"recording_id", "duration_ms", "recording_mode", "sources"}

    saved = client.post(
        f"/api/v1/clips/{clip_id}/text",
        json={"transcription": HEARD, "translation_hi": "मेरा नाम", "translation_en": ""},
    )
    assert saved.status_code == 201, saved.text
    layers = db.scalars(
        select(TextLayer).where(
            TextLayer.recording_id.is_not(None) | TextLayer.source_layer_id.is_not(None)
        )
    ).all()
    by_type = {(layer.layer_type, layer.language_tag): layer for layer in layers}
    assert set(by_type) == {("transcription", "unr"), ("translation", "hi")}
    transcription = by_type[("transcription", "unr")]
    assert (transcription.recording_id, transcription.script_code) == (clip_id, "Deva")
    revision = db.get_one(TextRevision, transcription.current_revision_id)
    assert (revision.content_original, revision.origin, revision.verification_status) == (
        HEARD,
        "human_contributor",
        "unverified",
    )
    assert revision.author_user_id == ravi.id
    # Once written down, it is no longer handed out.
    assert client.get(NEXT).json()["code"] == "no_clip_available"
    again = client.post(f"/api/v1/clips/{clip_id}/text", json={"transcription": HEARD})
    assert (again.status_code, again.json()["code"]) == (409, "already_transcribed")

    # The speaker sees the text on their own submission.
    act_as(client, asha)
    submission_id = db.get_one(Recording, clip_id).submission_id
    texts = client.get(f"{SUBMISSIONS}/{submission_id}").json()["text_layers"]
    assert [
        t["current_revision"]["content"] for t in texts if t["layer_type"] == "transcription"
    ] == [HEARD]


def test_transcription_is_devanagari_or_mundari_bani_and_translations_need_their_script(
    client: TestClient, db: Session, engine: Engine, tmp_path: Path, asha: TestUser, ravi: TestUser
) -> None:
    act_as(client, asha)
    clip_id = record(client, db, engine, tmp_path)
    act_as(client, ravi)
    url = f"/api/v1/clips/{clip_id}/text"
    latin = client.post(url, json={"transcription": "enem seno tana"})
    assert (latin.status_code, latin.json()["code"]) == (422, "wrong_script")
    # Devanagari text sent as Mundari Bani is refused too.
    mixed_up = client.post(url, json={"transcription": HEARD, "script": "Nagm"})
    assert (mixed_up.status_code, mixed_up.json()["code"]) == (422, "wrong_script")
    roman = client.post(url, json={"transcription": "enem", "script": "Latn"})
    assert roman.status_code == 422
    english = client.post(url, json={"transcription": HEARD, "translation_en": "मेरा नाम"})
    assert english.json()["code"] == "translation_en_script"

    saved = client.post(
        url,
        json={"transcription": NAG_MUNDARI, "script": "Nagm", "translation_en": "My name"},
    )
    assert saved.status_code == 201
    layer = db.get_one(TextLayer, uuid.UUID(saved.json()["transcription_layer_id"]))
    assert (layer.script_code, layer.language_tag) == ("Nagm", "unr")
    # One transcription in either script is enough: the clip is no longer handed out.
    again = client.post(url, json={"transcription": HEARD})
    assert (again.status_code, again.json()["code"]) == (409, "already_transcribed")


def test_clips_follow_consent_restrictions_mode_and_skips(
    client: TestClient, db: Session, engine: Engine, tmp_path: Path, asha: TestUser, ravi: TestUser
) -> None:
    act_as(client, asha)
    private = record(client, db, engine, tmp_path, public=False)
    hidden = record(client, db, engine, tmp_path)
    open_one = record(client, db, engine, tmp_path)
    second = record(client, db, engine, tmp_path)
    hidden_submission = db.get_one(Recording, hidden).submission_id
    db.execute(
        update(Submission)
        .where(Submission.id == hidden_submission)
        .values(restriction_flags=["sensitive"])
    )
    db.commit()
    act_as(client, ravi)
    seen = {client.get(NEXT).json()["recording_id"] for _ in range(20)}
    assert seen <= {str(open_one), str(second)}
    # Not public (the later consent did not reach back to it) and hidden: never handed out.
    skipped = client.get(NEXT, params={"exclude": [str(open_one), str(second)]})
    assert skipped.json()["code"] == "no_clip_available"
    assert str(private) not in seen and str(hidden) not in seen
