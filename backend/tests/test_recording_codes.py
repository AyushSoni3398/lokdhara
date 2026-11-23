"""Recording codes: speaker, gender letter, sentence number, and how it was recorded (ADR-034).
All data is synthetic."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.prompts.models import Prompt
from app.modules.speakers.codes import hide_gender
from app.modules.submissions.models import Recording
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, give_consent, own_speaker, upload

pytestmark = requires_postgres


@pytest.fixture
def asha(make_user: MakeUser) -> TestUser:
    return make_user("asha", "contributor")


@pytest.fixture
def speaker_id(client: TestClient, asha: TestUser, db: Session) -> str:
    act_as(client, asha)
    speaker = own_speaker(client)
    give_consent(client, db, speaker, demographics_consented=True)
    return speaker


def _prompt(db: Session, make_user: MakeUser, key: str) -> Prompt:
    admin = make_user(f"admin-{key}", "admin").id
    prompt = Prompt(
        prompt_key=key,
        version=1,
        prompt_type="read_sentence",
        text="एक छोटा वाक्य।",
        text_language_tag="hi",
        script_code="Deva",
        source_and_licence="test",
        status="approved",
        approved_by=admin,
        created_by=admin,
    )
    db.add(prompt)
    db.commit()
    return prompt


def _send(client: TestClient, speaker_id: str, **fields: str) -> uuid.UUID:
    draft = create_draft(client, speaker_id, **fields)
    recording_id = upload(client, draft["id"]).json()["recording_id"]
    response = client.post(f"{SUBMISSIONS}/{draft['id']}/submit")
    assert response.status_code == 200, response.text
    return uuid.UUID(recording_id)


def _codes(db: Session, *ids: uuid.UUID) -> list[str | None]:
    db.expire_all()
    return [db.scalar(select(Recording.recording_code).where(Recording.id == i)) for i in ids]


def _speaker_code(client: TestClient, speaker_id: str) -> str:
    return str(client.get(f"/api/v1/speakers/{speaker_id}").json()["speaker_code"])


def test_drafts_have_no_code_and_sent_recordings_do(
    client: TestClient, speaker_id: str, db: Session
) -> None:
    draft = create_draft(client, speaker_id)
    recording_id = uuid.UUID(upload(client, draft["id"]).json()["recording_id"])
    assert _codes(db, recording_id) == [None]
    client.post(f"{SUBMISSIONS}/{draft['id']}/submit")
    code = _speaker_code(client, speaker_id)
    assert _codes(db, recording_id) == [f"{code}_S000_free"]
    shown = client.get(f"{SUBMISSIONS}/{draft['id']}").json()["recordings"][0]
    assert shown["recording_code"] == f"{code}_S000_free"


def test_sentences_are_numbered_and_takes_counted(
    client: TestClient, speaker_id: str, db: Session, make_user: MakeUser
) -> None:
    first = _prompt(db, make_user, "test-read-one")
    second = _prompt(db, make_user, "test-read-two")
    assert second.prompt_number == first.prompt_number + 1
    takes = [
        _send(client, speaker_id, recording_mode="read", prompt_id=str(first.id)),
        _send(client, speaker_id, recording_mode="read", prompt_id=str(first.id)),
        _send(client, speaker_id, recording_mode="read", prompt_id=str(second.id)),
        _send(client, speaker_id),
    ]
    code = _speaker_code(client, speaker_id)
    one, two = f"S{first.prompt_number:03d}", f"S{second.prompt_number:03d}"
    assert _codes(db, *takes) == [
        f"{code}_{one}_read",
        f"{code}_{one}_read_2",
        f"{code}_{two}_read",
        f"{code}_S000_free",
    ]


def test_a_new_gender_renames_the_speakers_recordings(
    client: TestClient, speaker_id: str, db: Session
) -> None:
    recordings = [_send(client, speaker_id), _send(client, speaker_id)]
    code = _speaker_code(client, speaker_id)
    assert code.endswith("_X")
    client.patch(f"/api/v1/speakers/{speaker_id}", json={"gender": "female"})
    female = f"{code[:-1]}F"
    assert _speaker_code(client, speaker_id) == female
    assert _codes(db, *recordings) == [f"{female}_S000_free", f"{female}_S000_free_2"]

    # Taking back the answer about sharing details clears the gender and the letter is X again.
    give_consent(client, db, speaker_id, demographics_consented=False)
    assert _speaker_code(client, speaker_id) == code
    assert _codes(db, *recordings) == [f"{code}_S000_free", f"{code}_S000_free_2"]


def test_other_speakers_recordings_keep_their_codes(
    client: TestClient, speaker_id: str, db: Session, make_user: MakeUser, asha: TestUser
) -> None:
    mine = _send(client, speaker_id)
    act_as(client, make_user("ravi", "contributor"))
    other = own_speaker(client)
    give_consent(client, db, other)
    theirs = _send(client, other)
    before = _codes(db, theirs)
    act_as(client, asha)
    client.patch(f"/api/v1/speakers/{speaker_id}", json={"gender": "male"})
    assert _codes(db, theirs) == before
    assert str(_codes(db, mine)[0]).split("_")[2] == "M"


def test_gender_letters_are_hidden_where_gender_may_not_be_shared() -> None:
    assert hide_gender("SPK_7Q3M9A_F") == "SPK_7Q3M9A_X"
    assert hide_gender("SPK_7Q3M9A_M_S012_read_2") == "SPK_7Q3M9A_X_S012_read_2"
    assert hide_gender("not-a-code") == "not-a-code"
