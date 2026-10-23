"""Speaker profiles and restricted identity (docs/ACCESS_CONTROL.md §2)."""

import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.speakers.models import Speaker, SpeakerIdentity
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres

pytestmark = requires_postgres

SPEAKERS = "/api/v1/speakers"


def _create(client: TestClient, *, for_self: bool, **extra: object) -> dict[str, object]:
    response = client.post(SPEAKERS, json={"for_self": for_self, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def _allow_demographics(db: Session, speaker_id: object) -> None:
    db.execute(
        update(Speaker)
        .where(Speaker.id == uuid.UUID(str(speaker_id)))
        .values(demographics_consented=True)
    )
    db.commit()


def _audit_actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


# ------------------------------------------------------------------ creating profiles


def test_contributor_creates_one_pseudonymous_self_profile(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("asha", "contributor"))
    speaker = _create(client, for_self=True, dialect_label="Hasada")
    assert re.fullmatch(r"SPK-[2-9A-HJKMNP-TV-Z]{6}", str(speaker["speaker_code"]))
    assert speaker["is_self"] is True
    assert speaker["has_active_consent"] is False
    assert speaker["dialect_label"] == "Hasada"
    again = client.post(SPEAKERS, json={"for_self": True})
    assert again.status_code == 409
    assert again.json()["code"] == "self_speaker_exists"


def test_only_facilitators_and_admins_create_profiles_for_others(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("asha", "contributor"))
    assert client.post(SPEAKERS, json={"for_self": False}).json()["code"] == "forbidden"
    act_as(client, make_user("ravi", "facilitator"))
    assert _create(client, for_self=False)["is_self"] is False


def test_researchers_do_not_record(client: TestClient, make_user: MakeUser) -> None:
    act_as(client, make_user("meera", "researcher"))
    assert client.post(SPEAKERS, json={"for_self": True}).status_code == 403


def test_speaker_creation_is_audited(client: TestClient, make_user: MakeUser, db: Session) -> None:
    act_as(client, make_user("ravi", "facilitator"))
    _create(client, for_self=False)
    assert _audit_actions(db)[-1] == "speaker.create"


# ------------------------------------------------------------------ visibility


def test_profiles_are_visible_to_their_people_and_admins_only(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("ravi", "facilitator"))
    speaker = _create(client, for_self=False)
    path = f"{SPEAKERS}/{speaker['id']}"
    assert client.get(path).status_code == 200

    act_as(client, make_user("sita", "facilitator"))
    missing = client.get(path)
    assert missing.status_code == 404
    assert missing.json()["code"] == "speaker_not_found"
    assert client.get(SPEAKERS).json()["items"] == []

    act_as(client, make_user("admin", "admin"))
    assert client.get(path).status_code == 200
    assert len(client.get(SPEAKERS, params={"mine": "false"}).json()["items"]) == 1


def test_list_shows_my_profile_and_people_i_added(client: TestClient, make_user: MakeUser) -> None:
    act_as(client, make_user("ravi", "facilitator", "contributor"))
    mine = _create(client, for_self=True)
    other = _create(client, for_self=False)
    listed = {item["id"] for item in client.get(SPEAKERS).json()["items"]}
    assert listed == {mine["id"], other["id"]}


# ------------------------------------------------------------------ demographics


def test_demographics_need_the_speakers_consent(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    act_as(client, make_user("asha", "contributor"))
    speaker = _create(client, for_self=True)
    path = f"{SPEAKERS}/{speaker['id']}"
    refused = client.patch(path, json={"age_band": "30-44"})
    assert refused.status_code == 422
    assert refused.json()["code"] == "demographics_not_consented"
    assert client.patch(path, json={"dialect_label": "Kera"}).json()["dialect_label"] == "Kera"

    _allow_demographics(db, speaker["id"])
    changed = client.patch(path, json={"age_band": "30-44", "first_language": "unr"})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["age_band"], changed.json()["first_language"]) == ("30-44", "unr")


def test_minors_can_be_turned_off(
    client: TestClient, make_user: MakeUser, db: Session, settings: Settings
) -> None:
    act_as(client, make_user("ravi", "facilitator"))
    speaker = _create(client, for_self=False)
    _allow_demographics(db, speaker["id"])
    path = f"{SPEAKERS}/{speaker['id']}"
    assert client.patch(path, json={"age_band": "under_18"}).status_code == 200
    settings.allow_minors = False
    assert client.patch(path, json={"age_band": "under_18"}).json()["code"] == "minors_not_enabled"


def test_only_the_people_acting_for_a_speaker_may_edit(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("asha", "contributor"))
    speaker = _create(client, for_self=True)
    act_as(client, make_user("admin", "admin"))
    assert client.patch(f"{SPEAKERS}/{speaker['id']}", json={"dialect_label": "x"}).is_success
    act_as(client, make_user("ravi", "facilitator"))
    assert client.patch(f"{SPEAKERS}/{speaker['id']}", json={"dialect_label": "y"}).status_code == (
        404
    )


def test_free_text_rejects_hidden_direction_controls(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("asha", "contributor"))
    response = client.post(SPEAKERS, json={"for_self": True, "dialect_label": "Ker‮a"})
    assert response.status_code == 422


# ------------------------------------------------------------------ restricted identity


def _facilitator_with_speaker(client: TestClient, make_user: MakeUser) -> tuple[TestUser, str]:
    facilitator = make_user("ravi", "facilitator")
    act_as(client, facilitator)
    return facilitator, str(_create(client, for_self=False)["id"])


def test_identity_is_stored_encrypted_and_read_back_by_its_facilitator(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    _, speaker_id = _facilitator_with_speaker(client, make_user)
    path = f"{SPEAKERS}/{speaker_id}/identity"
    details = {"full_name": "Synthetic Name", "contact": "000-TEST", "village": "Test Village"}
    written = client.put(path, json=details)
    assert written.status_code == 200, written.text
    assert written.json()["notes"] is None

    row = db.get(SpeakerIdentity, uuid.UUID(speaker_id))
    assert row is not None and row.full_name_enc is not None
    assert b"Synthetic" not in row.full_name_enc
    assert client.get(path).json()["full_name"] == "Synthetic Name"
    assert _audit_actions(db)[-2:] == ["speaker_identity.write", "speaker_identity.read"]


def test_identity_is_hidden_from_everyone_else(client: TestClient, make_user: MakeUser) -> None:
    _, speaker_id = _facilitator_with_speaker(client, make_user)
    path = f"{SPEAKERS}/{speaker_id}/identity"
    client.put(path, json={"full_name": "Synthetic Name"})

    act_as(client, make_user("sita", "facilitator"))
    assert client.get(path).status_code == 404
    act_as(client, make_user("admin", "admin"))
    assert client.get(path).json()["full_name"] == "Synthetic Name"


def test_contributors_manage_their_own_identity_only(
    client: TestClient, make_user: MakeUser
) -> None:
    facilitator = make_user("fac", "facilitator")
    act_as(client, facilitator)
    other = _create(client, for_self=False)
    act_as(client, make_user("asha", "contributor"))
    own = _create(client, for_self=True)
    path = f"{SPEAKERS}/{own['id']}/identity"
    assert client.put(path, json={"full_name": "Synthetic Self"}).status_code == 200
    assert client.get(path).json()["full_name"] == "Synthetic Self"
    assert client.get(f"{SPEAKERS}/{other['id']}/identity").status_code in (403, 404)


def test_identity_put_replaces_all_fields(client: TestClient, make_user: MakeUser) -> None:
    _, speaker_id = _facilitator_with_speaker(client, make_user)
    path = f"{SPEAKERS}/{speaker_id}/identity"
    client.put(path, json={"full_name": "Synthetic Name", "notes": "prefers mornings"})
    client.put(path, json={"full_name": "Synthetic Name"})
    assert client.get(path).json()["notes"] is None
