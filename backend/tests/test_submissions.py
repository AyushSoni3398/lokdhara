"""Submission drafts (docs/API_SPECIFICATION.md §4, docs/USER_FLOWS.md F1)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.prompts.models import Prompt
from app.modules.submissions.models import Submission
from app.modules.topics.models import Topic
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, draft_body, own_speaker

pytestmark = requires_postgres


@pytest.fixture
def asha(client: TestClient, make_user: MakeUser) -> TestUser:
    user = make_user("asha", "contributor")
    act_as(client, user)
    return user


@pytest.fixture
def speaker_id(client: TestClient, asha: TestUser) -> str:
    return own_speaker(client)


def _prompt(
    db: Session,
    author: uuid.UUID,
    prompt_type: str,
    status: str = "approved",
    topic_tags: tuple[str, ...] = (),
) -> str:
    prompt = Prompt(
        prompt_key=f"test-{uuid.uuid4().hex[:8]}",
        version=1,
        prompt_type=prompt_type,
        text="एक वाक्य पढ़िए।",
        text_language_tag="hi",
        script_code="Deva",
        source_and_licence="test",
        topic_tags=list(topic_tags),
        status=status,
        approved_by=None if status == "draft" else author,
        created_by=author,
    )
    db.add(prompt)
    db.commit()
    return str(prompt.id)


# ------------------------------------------------------------------ creating drafts


def test_a_draft_starts_without_consent_or_media(client: TestClient, speaker_id: str) -> None:
    draft = create_draft(
        client,
        speaker_id,
        title="A morning story",
        collection_context={"setting": "outdoor", "speaker_count": 1},
    )
    assert draft["status"] == "draft"
    assert draft["has_consent"] is False
    assert draft["language_tag"] == "unr"
    assert (draft["recordings"], draft["text_layers"]) == ([], [])
    assert draft["collection_context"]["setting"] == "outdoor"


def test_retrying_a_create_returns_the_same_draft(client: TestClient, speaker_id: str) -> None:
    body = draft_body(speaker_id)
    first = client.post(SUBMISSIONS, json=body)
    again = client.post(SUBMISSIONS, json=body)
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert len(client.get(SUBMISSIONS).json()["items"]) == 1


def test_another_users_draft_id_is_refused(
    client: TestClient, speaker_id: str, make_user: MakeUser
) -> None:
    body = draft_body(speaker_id)
    client.post(SUBMISSIONS, json=body)
    act_as(client, make_user("ravi", "contributor"))
    body["speaker_id"] = own_speaker(client)
    assert client.post(SUBMISSIONS, json=body).json()["code"] == "client_submission_id_taken"


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "text"},  # text has no recording mode
        {"recording_mode": None},  # audio needs one
        {"recording_mode": "prompted"},  # prompted needs a prompt
        {"prompt_id": str(uuid.uuid4())},  # free speech takes none
        {"collection_context": {"location": "Khunti"}},  # not an allow-listed key
        {"recorded_on": str((datetime.now(UTC) + timedelta(days=3)).date())},
        {"title": "line‮break"},  # bidi override
    ],
)
def test_inconsistent_drafts_are_rejected(
    client: TestClient, speaker_id: str, fields: dict[str, object]
) -> None:
    response = client.post(SUBMISSIONS, json=draft_body(speaker_id, **fields))
    assert response.status_code == 422, response.text


def test_text_drafts_have_no_recording_mode(client: TestClient, speaker_id: str) -> None:
    draft = create_draft(client, speaker_id, kind="text", recording_mode=None)
    assert draft["recording_mode"] is None


def test_the_collection_method_must_fit(
    client: TestClient, speaker_id: str, make_user: MakeUser
) -> None:
    for method in ("facilitator_field", "imported_archive"):
        response = client.post(SUBMISSIONS, json=draft_body(speaker_id, collection_method=method))
        assert response.json()["code"] == "collection_method_not_allowed"

    act_as(client, make_user("ravi", "facilitator"))
    other = client.post("/api/v1/speakers", json={"for_self": False}).json()["id"]
    assert client.post(SUBMISSIONS, json=draft_body(other)).json()["code"] == (
        "collection_method_not_allowed"
    )
    create_draft(client, other, collection_method="facilitator_field")


def test_drafts_are_only_for_speakers_you_act_for(
    client: TestClient, speaker_id: str, make_user: MakeUser
) -> None:
    act_as(client, make_user("ravi", "contributor"))
    response = client.post(SUBMISSIONS, json=draft_body(speaker_id))
    assert response.json()["code"] == "speaker_not_found"
    act_as(client, make_user("meera", "researcher"))
    assert client.post(SUBMISSIONS, json=draft_body(speaker_id)).status_code == 403


def test_prompts_must_be_approved_and_fit_the_mode(
    client: TestClient, speaker_id: str, make_user: MakeUser, db: Session
) -> None:
    admin = make_user("admin", "admin").id
    situation = _prompt(db, admin, "situation")
    sentence = _prompt(db, admin, "read_sentence")
    unapproved = _prompt(db, admin, "situation", status="draft")

    def attempt(mode: str, prompt_id: str) -> object:
        body = draft_body(speaker_id, recording_mode=mode, prompt_id=prompt_id)
        return client.post(SUBMISSIONS, json=body).json().get("code")

    assert attempt("read", situation) == "prompt_mismatch"
    assert attempt("prompted", sentence) == "prompt_mismatch"
    assert attempt("prompted", unapproved) == "prompt_not_found"
    db.execute(update(Prompt).where(Prompt.id == uuid.UUID(sentence)).values(status="retired"))
    db.commit()
    assert attempt("read", sentence) == "prompt_retired"
    assert attempt("prompted", situation) is None  # created


def test_items_carry_topics_from_the_list(
    client: TestClient, speaker_id: str, make_user: MakeUser, db: Session
) -> None:
    chosen = create_draft(client, speaker_id, topics=["health_and_medicine", "agriculture"])
    assert chosen["topics"] == ["agriculture", "health_and_medicine"]
    assert create_draft(client, speaker_id)["topics"] == []
    unknown = client.post(SUBMISSIONS, json=draft_body(speaker_id, topics=["astrology"]))
    assert unknown.json()["code"] == "unknown_topic"
    too_many = draft_body(speaker_id, topics=[f"t{i}x" for i in range(11)])
    assert client.post(SUBMISSIONS, json=too_many).status_code == 422

    # A prompt's tags that are on the list become the starting topics.
    tags = ("forest-and-nature", "seasons")
    prompt_id = _prompt(db, make_user("admin", "admin").id, "situation", topic_tags=tags)
    prompted = create_draft(client, speaker_id, recording_mode="prompted", prompt_id=prompt_id)
    assert prompted["topics"] == ["forest_and_nature"]
    own = create_draft(
        client, speaker_id, recording_mode="prompted", prompt_id=prompt_id, topics=["education"]
    )
    assert own["topics"] == ["education"]

    # A topic retired after it was chosen may stay on the item, but cannot be chosen anew.
    db.execute(update(Topic).where(Topic.key == "agriculture").values(retired_at=datetime.now(UTC)))
    db.commit()
    path = f"{SUBMISSIONS}/{chosen['id']}"
    kept = client.patch(path, json={"topics": ["agriculture", "education"]})
    assert kept.json()["topics"] == ["agriculture", "education"]
    other = f"{SUBMISSIONS}/{prompted['id']}"
    assert client.patch(other, json={"topics": ["agriculture"]}).json()["code"] == "unknown_topic"
    assert client.patch(path, json={"title": "x"}).json()["topics"] == ["agriculture", "education"]


# ------------------------------------------------------------------ seeing drafts


def test_people_see_their_own_submissions_only(
    client: TestClient, speaker_id: str, make_user: MakeUser
) -> None:
    draft = create_draft(client, speaker_id)
    act_as(client, make_user("ravi", "contributor"))
    assert client.get(f"{SUBMISSIONS}/{draft['id']}").json()["code"] == "submission_not_found"
    assert client.get(SUBMISSIONS).json()["items"] == []
    act_as(client, make_user("rita", "reviewer"))
    assert client.get(f"{SUBMISSIONS}/{draft['id']}").status_code == 404
    act_as(client, make_user("admin", "admin"))
    assert client.get(f"{SUBMISSIONS}/{draft['id']}").status_code == 200
    everyone = client.get(SUBMISSIONS, params={"mine": False}).json()["items"]
    assert [item["id"] for item in everyone] == [draft["id"]]


def test_facilitators_see_what_was_recorded_of_their_speakers(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    facilitator = make_user("ravi", "facilitator")
    act_as(client, facilitator)
    speaker = client.post("/api/v1/speakers", json={"for_self": False}).json()["id"]
    draft = create_draft(client, speaker, collection_method="facilitator_field")
    act_as(client, make_user("admin", "admin"))
    admin_draft = create_draft(client, speaker, collection_method="facilitator_remote")
    act_as(client, facilitator)
    assert client.get(f"{SUBMISSIONS}/{admin_draft['id']}").status_code == 200
    mine = client.get(SUBMISSIONS).json()["items"]
    assert [item["id"] for item in mine] == [draft["id"]]
    both = client.get(SUBMISSIONS, params={"mine": False}).json()["items"]
    assert {item["id"] for item in both} == {draft["id"], admin_draft["id"]}

    db.execute(
        update(Submission)
        .where(Submission.id == uuid.UUID(admin_draft["id"]))
        .values(status="withdrawn")
    )
    db.commit()
    assert client.get(f"{SUBMISSIONS}/{admin_draft['id']}").status_code == 404


def test_lists_are_paged_newest_first(client: TestClient, speaker_id: str) -> None:
    ids = [create_draft(client, speaker_id)["id"] for _ in range(3)]
    first = client.get(SUBMISSIONS, params={"limit": 2}).json()
    assert [item["id"] for item in first["items"]] == [ids[2], ids[1]]
    rest = client.get(SUBMISSIONS, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [item["id"] for item in rest["items"]] == [ids[0]]
    assert rest["next_cursor"] is None
    drafts = client.get(SUBMISSIONS, params={"status": "processing"}).json()["items"]
    assert drafts == []


# ------------------------------------------------------------------ editing drafts


def test_owners_edit_the_description_of_a_draft(
    client: TestClient, speaker_id: str, make_user: MakeUser
) -> None:
    draft = create_draft(client, speaker_id, title="Old title", dialect_label="Hasada")
    path = f"{SUBMISSIONS}/{draft['id']}"
    edited = client.patch(
        path,
        json={"title": None, "content_type": "song", "collection_context": {"setting": "outdoor"}},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["title"], body["content_type"], body["dialect_label"]) == (None, "song", "Hasada")
    assert body["collection_context"] == {
        "setting": "outdoor",
        "speaker_count": None,
        "equipment": None,
        "notes": None,
    }
    assert client.patch(path, json={"content_type": None}).status_code == 422
    assert client.patch(path, json={"kind": "text"}).json()["kind"] == "audio"  # ignored

    act_as(client, make_user("admin", "admin"))
    assert client.patch(path, json={"title": "x"}).json()["code"] == "forbidden"
