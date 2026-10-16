"""Withdrawal requests (docs/DATA_RETENTION_AND_DELETION.md §2, docs/USER_FLOWS.md F3).
Synthetic data only."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.releases.models import DatasetReleaseItem
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


# ------------------------------------------------------------------ admin decisions

CATALOGUE = "/api/v1/catalogue"
CHECKED = {"note": "Phoned the speaker back on the number in the consent record."}


def catalogue_ids(client: TestClient, researcher: TestUser) -> set[str]:
    act_as(client, researcher)
    return {item["id"] for item in client.get(CATALOGUE).json()["items"]}


def frozen_release(client: TestClient, admin: TestUser) -> Any:
    act_as(client, admin)
    draft = client.post(
        "/api/v1/datasets", json={"slug": "mundari-pilot", "purpose": "internal_research"}
    ).json()
    response = client.post(f"/api/v1/datasets/{draft['id']}/freeze", json={"version": "0.1.0"})
    assert response.status_code == 200, response.text
    return response.json()


def test_verifying_a_full_withdrawal_restricts_everything_at_once(
    client: TestClient,
    db: Session,
    items: dict[str, str],
    asha: TestUser,
    admin: TestUser,
    make_user: MakeUser,
) -> None:
    researcher = make_user("kiran", "researcher")
    assert catalogue_ids(client, researcher) == {items["story"], items["song"]}
    release = frozen_release(client, admin)
    act_as(client, asha)
    request = ask(client, scope="full", speaker_id=items["speaker"]).json()
    verify = f"{QUEUE}/{request['id']}/verify"
    assert client.post(verify, json=CHECKED).json()["code"] == "forbidden"

    act_as(client, admin)
    assert client.post(verify, json={"note": ""}).status_code == 422
    verified = client.post(verify, json=CHECKED).json()
    assert verified["status"] == "verified"
    assert verified["verified_at"] is not None
    action = verified["actions_taken"][0]
    assert (action["action"], action["note"], action["items"], action["releases_marked"]) == (
        "verified",
        CHECKED["note"],
        2,
        1,
    )
    assert client.post(verify, json=CHECKED).json()["code"] == "withdrawal_decided"

    speaker = client.get(f"/api/v1/speakers/{items['speaker']}").json()
    assert speaker["status"] == "withdrawn"
    consents = client.get(f"/api/v1/speakers/{items['speaker']}/consents").json()["items"]
    assert consents[0]["status"] == "withdrawn"
    assert client.get(f"/api/v1/submissions/{items['story']}").json()["status"] == "withdrawn"
    marked = db.scalars(
        select(DatasetReleaseItem.submission_id).where(
            DatasetReleaseItem.release_id == uuid.UUID(release["id"]),
            DatasetReleaseItem.withdrawn_after_release_at.is_not(None),
        )
    )
    assert {str(m) for m in marked} == {items["story"], items["song"]}

    assert catalogue_ids(client, researcher) == set()
    act_as(client, asha)
    assert client.get(f"/api/v1/submissions/{items['story']}").status_code == 404
    assert client.get("/api/v1/submissions").json()["items"] == []
    mine = client.get(f"{REQUESTS}/{request['id']}").json()
    assert (mine["status"], mine["actions_taken"]) == ("verified", None)
    again = ask(client, scope="specific_items", submission_id=items["song"])
    assert again.json()["code"] == "already_withdrawn"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "withdrawal.verify"))


def test_withdrawing_one_item_leaves_the_others(
    client: TestClient,
    items: dict[str, str],
    asha: TestUser,
    admin: TestUser,
    make_user: MakeUser,
) -> None:
    act_as(client, asha)
    request = ask(client, scope="specific_items", submission_id=items["story"]).json()
    act_as(client, admin)
    verified = client.post(f"{QUEUE}/{request['id']}/verify", json=CHECKED).json()
    assert verified["actions_taken"][0]["items"] == 1
    assert client.get(f"/api/v1/speakers/{items['speaker']}").json()["status"] == "active"
    assert catalogue_ids(client, make_user("kiran", "researcher")) == {items["song"]}


def test_a_narrower_consent_is_recorded_before_the_request_is_verified(
    client: TestClient, db: Session, items: dict[str, str], asha: TestUser, admin: TestUser
) -> None:
    act_as(client, asha)
    request = ask(client, scope="narrow", speaker_id=items["speaker"], note="No research.").json()
    act_as(client, admin)
    verify = f"{QUEUE}/{request['id']}/verify"
    assert client.post(verify, json=CHECKED).json()["code"] == "consent_not_changed"
    give_consent(client, db, items["speaker"], allow_research=False)
    verified = client.post(verify, json=CHECKED).json()
    assert verified["status"] == "verified"
    assert client.get(f"/api/v1/speakers/{items['speaker']}").json()["status"] == "active"
    assert client.get(f"/api/v1/submissions/{items['story']}").json()["status"] == "accepted"
    # Nothing is deleted for a narrower consent, so it can be closed straight away.
    done = client.post(f"{QUEUE}/{request['id']}/complete", json={"note": "Told by phone."})
    assert done.json()["status"] == "completed"


def test_a_request_that_cannot_be_confirmed_is_rejected(
    client: TestClient, items: dict[str, str], asha: TestUser, admin: TestUser
) -> None:
    act_as(client, admin)
    request = ask(client, scope="full", speaker_id=items["speaker"], received_via="email").json()
    note = {"note": "The email did not come from the speaker or their facilitator."}
    rejected = client.post(f"{QUEUE}/{request['id']}/reject", json=note).json()
    assert (rejected["status"], rejected["actions_taken"][0]["action"]) == ("rejected", "rejected")
    assert rejected["completed_at"] is not None
    assert client.post(f"{QUEUE}/{request['id']}/verify", json=CHECKED).json()["code"] == (
        "withdrawal_decided"
    )
    assert client.get(f"/api/v1/speakers/{items['speaker']}").json()["status"] == "active"
    assert client.get(QUEUE).json()["items"] == []
    assert len(client.get(f"{QUEUE}?open=false").json()["items"]) == 1
    other = ask(client, scope="narrow", speaker_id=items["speaker"]).json()
    response = client.post(f"{QUEUE}/{other['id']}/complete", json={"note": "Done."})
    assert response.json()["code"] == "withdrawal_not_verified"
