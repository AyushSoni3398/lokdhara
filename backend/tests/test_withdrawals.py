"""Withdrawal requests (docs/DATA_RETENTION_AND_DELETION.md §2, docs/USER_FLOWS.md F3).
Synthetic data only."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import accepted_text_item, give_consent, own_speaker

pytestmark = requires_postgres

REQUESTS = "/api/v1/withdrawal-requests"
QUEUE = "/api/v1/admin/withdrawal-requests"


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


@pytest.fixture
def asha(make_user: MakeUser) -> TestUser:
    return make_user("asha", "contributor")


@pytest.fixture
def items(client: TestClient, engine: Engine, db: Session, asha: TestUser) -> dict[str, str]:
    """asha's own speaker profile with two accepted research items."""
    act_as(client, asha)
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    story = accepted_text_item(client, engine, speaker, "नदी के किनारे")
    song = accepted_text_item(client, engine, speaker, "एक गीत", content_type="song")
    return {"speaker": speaker, "story": story, "song": song}


def ask(client: TestClient, **body: Any) -> Any:
    return client.post(REQUESTS, json=body)


def test_speakers_ask_for_everything_or_one_item_from_the_app(
    client: TestClient, db: Session, items: dict[str, str], asha: TestUser
) -> None:
    act_as(client, asha)
    full = ask(client, scope="full", speaker_id=items["speaker"], note="Please remove all.")
    assert full.status_code == 201, full.text
    body = full.json()
    assert (body["status"], body["received_via"], body["requested_scope"]) == (
        "received",
        "in_app",
        "full",
    )
    assert body["speaker_code"].startswith("SPK-")
    assert body["actions_taken"] is None  # only admins see what was done and their notes
    again = ask(client, scope="full", speaker_id=items["speaker"])
    assert again.json()["code"] == "already_requested"

    one = ask(client, scope="specific_items", submission_id=items["story"]).json()
    assert (one["speaker_id"], one["submission_id"]) == (items["speaker"], items["story"])
    assert {r["id"] for r in client.get(REQUESTS).json()["items"]} == {body["id"], one["id"]}
    assert client.get(f"{REQUESTS}/{one['id']}").status_code == 200
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "withdrawal.request"))
    assert event is not None
    assert "note" not in event.details


def test_requests_must_name_the_right_subject(
    client: TestClient, items: dict[str, str], asha: TestUser
) -> None:
    act_as(client, asha)
    for body in (
        {"scope": "specific_items", "speaker_id": items["speaker"]},
        {"scope": "full", "submission_id": items["story"]},
        {"scope": "narrow"},
        {"scope": "full", "speaker_id": items["speaker"], "note": "  "},
    ):
        assert ask(client, **body).status_code == 422, body


def test_only_people_who_act_for_the_speaker_can_ask(
    client: TestClient, items: dict[str, str], make_user: MakeUser
) -> None:
    act_as(client, make_user("ravi", "contributor"))
    response = ask(client, scope="full", speaker_id=items["speaker"])
    assert response.json()["code"] == "speaker_not_found"
    response = ask(client, scope="specific_items", submission_id=items["story"])
    assert response.json()["code"] == "submission_not_found"
    assert client.get(REQUESTS).json()["items"] == []

    # A researcher reads the item in the catalogue but cannot withdraw it.
    act_as(client, make_user("kiran", "researcher"))
    assert client.get(f"/api/v1/submissions/{items['story']}").status_code == 200
    response = ask(client, scope="specific_items", submission_id=items["story"])
    assert response.json()["code"] == "submission_not_found"


def test_facilitators_and_admins_log_requests_they_received(
    client: TestClient, db: Session, admin: TestUser, make_user: MakeUser, items: dict[str, str]
) -> None:
    act_as(client, make_user("sunita", "facilitator"))
    speaker = client.post("/api/v1/speakers", json={"for_self": False}).json()["id"]
    logged = ask(client, scope="narrow", speaker_id=speaker).json()
    assert logged["received_via"] == "facilitator"

    act_as(client, admin)
    by_phone = ask(client, scope="full", speaker_id=items["speaker"], received_via="phone")
    assert by_phone.json()["received_via"] == "phone"
    queue = client.get(QUEUE).json()["items"]
    assert [r["id"] for r in queue] == [logged["id"], by_phone.json()["id"]]  # oldest first
    assert queue[0]["actions_taken"] == []
    assert client.get(f"{REQUESTS}/{logged['id']}").status_code == 200

    act_as(client, make_user("ravi", "contributor"))
    assert client.get(QUEUE).json()["code"] == "forbidden"
    assert client.get(f"{REQUESTS}/{logged['id']}").json()["code"] == "withdrawal_not_found"
