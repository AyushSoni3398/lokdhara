"""Dataset releases (docs/DATASET_VERSIONING.md, ROADMAP M7). Synthetic data only."""

import hashlib
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.processing.models import Job
from app.modules.releases import freeze as freeze_module
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem
from app.object_store import Bucket, ObjectStore
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import accepted_text_item, give_consent, own_speaker

pytestmark = requires_postgres

DATASETS = "/api/v1/datasets"


@pytest.fixture
def researcher(make_user: MakeUser) -> TestUser:
    return make_user("kiran", "researcher")


@pytest.fixture
def items(client: TestClient, engine: Engine, db: Session, make_user: MakeUser) -> list[str]:
    """Two research items by asha (a story and a song), and one by ravi without research
    consent."""
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    story = accepted_text_item(client, engine, speaker, "नदी के किनारे", dialect_label="Hasada")
    song = accepted_text_item(client, engine, speaker, "एक गीत", content_type="song")
    act_as(client, make_user("ravi", "contributor"))
    private = own_speaker(client)
    give_consent(client, db, private)
    accepted_text_item(client, engine, private, "निजी वाक्य")
    return [story, song]


def _draft(client: TestClient, **fields: Any) -> dict[str, Any]:
    body = {"slug": "mundari-text-pilot", "purpose": "internal_research", **fields}
    response = client.post(DATASETS, json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_researchers_start_drafts_and_preview_what_consent_allows(
    client: TestClient, items: list[str], researcher: TestUser
) -> None:
    act_as(client, researcher)
    draft = _draft(client)
    assert (draft["status"], draft["version"]) == ("draft", None)
    assert draft["selection_criteria"]["kinds"] == []

    preview = client.get(f"{DATASETS}/{draft['id']}/preview").json()
    assert preview["item_count"] == 2
    assert preview["left_out_count"] == 1  # ravi did not allow research
    assert preview["by_content_type"] == {"song": 1, "story": 1}
    assert preview["by_dialect_label"] == {"(none)": 1, "Hasada": 1}
    assert sorted(s["id"] for s in preview["sample"]) == sorted(items)

    narrowed = client.patch(
        f"{DATASETS}/{draft['id']}", json={"selection_criteria": {"content_types": ["song"]}}
    )
    assert narrowed.json()["selection_criteria"]["content_types"] == ["song"]
    preview = client.get(f"{DATASETS}/{draft['id']}/preview").json()
    assert [s["id"] for s in preview["sample"]] == [items[1]]

    # Public use needs public consent, which nobody gave.
    client.patch(f"{DATASETS}/{draft['id']}", json={"purpose": "public"})
    assert client.get(f"{DATASETS}/{draft['id']}/preview").json()["item_count"] == 0
    assert [r["slug"] for r in client.get(DATASETS).json()["items"]] == ["mundari-text-pilot"]


def test_criteria_and_slugs_are_checked(client: TestClient, researcher: TestUser) -> None:
    act_as(client, researcher)
    bad = [
        {"slug": "Mundari Pilot", "purpose": "internal_research"},
        {"slug": "pilot", "purpose": "marketing"},
        {"slug": "pilot", "purpose": "public", "selection_criteria": {"colour": "red"}},
        {"slug": "pilot", "purpose": "public", "selection_criteria": {"kinds": ["video"]}},
    ]
    for body in bad:
        assert client.post(DATASETS, json=body).status_code == 422, body


def test_only_project_data_users_see_releases_and_only_the_starter_or_an_admin_edits(
    client: TestClient, researcher: TestUser, make_user: MakeUser
) -> None:
    act_as(client, researcher)
    draft = _draft(client)
    act_as(client, make_user("sita", "researcher"))
    assert client.get(f"{DATASETS}/{draft['id']}").status_code == 200
    change = client.patch(f"{DATASETS}/{draft['id']}", json={"licence": "CC-BY-4.0"})
    assert change.json()["code"] == "forbidden"
    act_as(client, make_user("meera", "admin"))
    assert (
        client.patch(f"{DATASETS}/{draft['id']}", json={"licence": "CC-BY-4.0"}).json()["licence"]
        == "CC-BY-4.0"
    )
    act_as(client, make_user("asha", "contributor"))
    assert client.get(DATASETS).json()["code"] == "forbidden"


# ------------------------------------------------------------------ checks and freezing


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


def _checks(client: TestClient, release_id: str) -> dict[str, Any]:
    response = client.post(f"{DATASETS}/{release_id}/checks")
    assert response.status_code == 200, response.text
    return {c["code"]: c for c in response.json()["checks"]} | {"passed": response.json()["passed"]}


def test_admins_freeze_a_checked_release_with_its_files_and_items(
    client: TestClient,
    items: list[str],
    researcher: TestUser,
    admin: TestUser,
    db: Session,
    object_store: ObjectStore,
) -> None:
    act_as(client, researcher)
    draft = _draft(client, data_card_markdown="Synthetic test release.")
    checks = _checks(client, draft["id"])
    assert checks["passed"] is True
    assert checks["D1"]["message"].startswith("2 accepted items")
    assert checks["D5"]["message"] == "2 of 2 texts are marked unverified."
    freeze = f"{DATASETS}/{draft['id']}/freeze"
    assert client.post(freeze, json={"version": "0.1.0"}).json()["code"] == "forbidden"

    act_as(client, admin)
    assert client.post(freeze, json={"version": "1.0"}).status_code == 422
    frozen = client.post(freeze, json={"version": "0.1.0"})
    assert frozen.status_code == 200, frozen.text
    release = frozen.json()
    assert (release["status"], release["version"]) == ("frozen", "0.1.0")
    assert client.post(freeze, json={"version": "0.2.0"}).json()["code"] == "release_frozen"
    edit = client.patch(f"{DATASETS}/{draft['id']}", json={"licence": "CC-BY-4.0"})
    assert edit.json()["code"] == "release_frozen"

    rows = db.scalars(select(DatasetReleaseItem)).all()
    assert sorted(str(r.submission_id) for r in rows) == sorted(items)
    assert all(r.consent_snapshot["research"] is True for r in rows)
    assert all(len(r.text_revision_ids) == 1 for r in rows)

    stored = db.get_one(DatasetRelease, uuid.UUID(draft["id"]))
    manifest_bytes = b"".join(object_store.open(Bucket.EXPORTS, stored.manifest_object_key or ""))
    assert hashlib.sha256(manifest_bytes).hexdigest() == release["manifest_sha256"]
    manifest = json.loads(manifest_bytes)
    assert manifest["item_count"] == 2
    readme = b"".join(
        object_store.open(Bucket.EXPORTS, freeze_module.stored_file_key(stored.id, "README.md"))
    ).decode()
    assert "Synthetic test release." in readme
    assert "**not checked by anyone**" in readme

    # The same slug and version cannot be frozen twice.
    again = _draft(client)
    response = client.post(f"{DATASETS}/{again['id']}/freeze", json={"version": "0.1.0"})
    assert response.json()["code"] == "version_exists"
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "release.freeze"))
    assert event is not None
    assert event.details["item_count"] == 2


def test_an_empty_release_is_not_frozen(
    client: TestClient, items: list[str], admin: TestUser
) -> None:
    act_as(client, admin)
    draft = _draft(client, selection_criteria={"content_types": ["vocabulary"]})
    response = client.post(f"{DATASETS}/{draft['id']}/freeze", json={"version": "0.1.0"})
    assert response.json()["code"] == "prefreeze_checks_failed"
    assert "D1" in response.json()["detail"]


def test_releases_beyond_internal_research_wait_for_governance(
    client: TestClient, items: list[str], admin: TestUser, settings: Settings
) -> None:
    act_as(client, admin)
    draft = _draft(client, purpose="external_research")
    d7 = _checks(client, draft["id"])["D7"]
    assert d7["passed"] is False
    assert "governance approval is not recorded yet" in d7["message"]
    assert "a licence is needed" in d7["message"]

    settings.external_releases_enabled = True
    client.patch(
        f"{DATASETS}/{draft['id']}",
        json={"licence": "Data-use agreement DUA-TEST", "data_card_markdown": "Test."},
    )
    assert _checks(client, draft["id"])["passed"] is True


def _frozen(client: TestClient, admin: TestUser, version: str = "0.1.0") -> dict[str, Any]:
    act_as(client, admin)
    draft = _draft(client)
    response = client.post(f"{DATASETS}/{draft['id']}/freeze", json={"version": version})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_admins_retract_a_frozen_release_with_a_note(
    client: TestClient, items: list[str], admin: TestUser, researcher: TestUser, db: Session
) -> None:
    act_as(client, researcher)
    draft = _draft(client)
    retract = f"{DATASETS}/{draft['id']}/retract"
    note = {"note": "A speaker raised a consent concern."}
    assert client.post(retract, json=note).json()["code"] == "forbidden"
    act_as(client, admin)
    assert client.post(retract, json=note).json()["code"] == "release_not_frozen"

    release = _frozen(client, admin, "0.2.0")
    retract = f"{DATASETS}/{release['id']}/retract"
    assert client.post(retract, json={"note": ""}).status_code == 422
    retracted = client.post(retract, json=note).json()
    assert (retracted["status"], retracted["retraction_note"]) == ("retracted", note["note"])
    assert retracted["version"] == "0.2.0"  # the record stays for audit
    assert client.post(retract, json=note).json()["code"] == "release_retracted"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "release.retract"))


# ------------------------------------------------------------------ export requests

PURPOSE = {"purpose_statement": "Train a student's keyword-spotting baseline."}


def test_researchers_request_exports_and_another_admin_decides(
    client: TestClient,
    items: list[str],
    researcher: TestUser,
    admin: TestUser,
    make_user: MakeUser,
    db: Session,
) -> None:
    act_as(client, researcher)
    draft = _draft(client)
    exports_url = f"{DATASETS}/{draft['id']}/exports"
    assert client.post(exports_url, json=PURPOSE).json()["code"] == "release_not_frozen"
    release = _frozen(client, admin)
    exports_url = f"{DATASETS}/{release['id']}/exports"

    act_as(client, researcher)
    assert client.post(exports_url, json={"purpose_statement": ""}).status_code == 422
    first = client.post(exports_url, json=PURPOSE)
    assert first.status_code == 201, first.text
    request = first.json()
    assert (request["status"], request["mine"], request["requested_by_name"]) == (
        "requested",
        True,
        "kiran",
    )
    second = client.post(exports_url, json=PURPOSE).json()
    approve = f"/api/v1/admin/exports/{request['id']}/approve"
    assert client.post(approve, json={}).json()["code"] == "forbidden"

    # Other researchers neither see nor open someone else's request.
    act_as(client, make_user("sita", "researcher"))
    assert client.get("/api/v1/exports").json()["items"] == []
    assert client.get(f"/api/v1/exports/{request['id']}").json()["code"] == "export_not_found"

    act_as(client, admin)
    assert len(client.get("/api/v1/exports").json()["items"]) == 2
    approved = client.post(
        f"/api/v1/admin/exports/{request['id']}/approve", json={"note": "Fits the agreement."}
    ).json()
    assert (approved["status"], approved["decision_note"], approved["mine"]) == (
        "approved",
        "Fits the agreement.",
        False,
    )
    again = client.post(f"/api/v1/admin/exports/{request['id']}/approve", json={})
    assert again.json()["code"] == "export_decided"
    reject = f"/api/v1/admin/exports/{second['id']}/reject"
    assert client.post(reject, json={"note": ""}).status_code == 422
    assert client.post(reject, json={"note": "Duplicate."}).json()["status"] == "rejected"
    job = db.scalar(select(Job).where(Job.job_type == "dataset.export"))
    assert job is not None
    assert str(job.target_id) == request["id"]

    # One approval is enough, even for an admin's own request (ADR-027).
    own = client.post(exports_url, json=PURPOSE).json()
    response = client.post(f"/api/v1/admin/exports/{own['id']}/approve", json={})
    assert response.json()["status"] == "approved"
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("export.%"))))
    assert actions == {"export.request", "export.approve", "export.reject"}


def test_retracting_a_release_closes_its_export_requests(
    client: TestClient, items: list[str], researcher: TestUser, admin: TestUser
) -> None:
    release = _frozen(client, admin)
    act_as(client, researcher)
    request = client.post(f"{DATASETS}/{release['id']}/exports", json=PURPOSE).json()
    act_as(client, admin)
    note = {"note": "A speaker raised a consent concern."}
    client.post(f"{DATASETS}/{release['id']}/retract", json=note)
    closed = client.get(f"/api/v1/exports/{request['id']}").json()
    assert (closed["status"], closed["decision_note"]) == (
        "rejected",
        "The release was retracted.",
    )
    act_as(client, researcher)
    response = client.post(f"{DATASETS}/{release['id']}/exports", json=PURPOSE)
    assert response.json()["code"] == "release_retracted"


def test_speaker_details_follow_demographics_consent_and_the_release_purpose(
    client: TestClient,
    engine: Engine,
    db: Session,
    make_user: MakeUser,
    settings: Settings,
    object_store: ObjectStore,
) -> None:
    act_as(client, make_user("asha", "contributor"))
    shared = own_speaker(client)
    give_consent(client, db, shared, allow_research=True, demographics_consented=True)
    details = {
        "age_band": "30-44",
        "gender_self_described": "woman",
        "first_language": "unr",
        "other_languages": ["hi"],
        "region_coarse": "Khunti",
    }
    assert client.patch(f"/api/v1/speakers/{shared}", json=details).status_code == 200
    with_details = accepted_text_item(client, engine, shared, "नदी", region_coarse="Khunti")
    act_as(client, make_user("ravi", "contributor"))
    private = own_speaker(client)
    give_consent(client, db, private, allow_research=True)
    without = accepted_text_item(client, engine, private, "गीत", region_coarse="Ranchi")

    def records(purpose: str) -> dict[str, dict[str, Any]]:
        release = DatasetRelease(
            slug=f"test-{purpose.replace('_', '-')}",
            purpose=purpose,
            created_by=uuid.uuid4(),
            selection_criteria={},
            data_card_markdown="",
        )
        run = freeze_module.run_checks(db, object_store, settings, release)
        return {str(i.submission.id): i.record for i in run.items}

    internal = records("internal_research")
    assert internal[with_details]["speaker"] == {
        "age_band": "30-44",
        "gender": "woman",
        "first_language": "unr",
        "other_languages": ["hi"],
        "region": "Khunti",
    }
    assert internal[with_details]["area"] == "Khunti"
    # No demographics consent: nothing about the speaker, not even the recording's area.
    assert (internal[without]["speaker"], internal[without]["area"]) == ({}, None)
    # Wider purposes keep only the age band until governance decides (ADR-029).
    external = records("external_research")
    assert external[with_details]["speaker"] == {"age_band": "30-44"}
    assert external[with_details]["area"] is None


def test_releases_can_take_only_items_on_some_topics(
    client: TestClient,
    engine: Engine,
    db: Session,
    make_user: MakeUser,
    settings: Settings,
    object_store: ObjectStore,
) -> None:
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    farming = accepted_text_item(client, engine, speaker, "खेत", topics=["agriculture"])
    accepted_text_item(client, engine, speaker, "दवा", topics=["health_and_medicine"])
    accepted_text_item(client, engine, speaker, "कुछ")
    release = DatasetRelease(
        slug="farming",
        purpose="internal_research",
        created_by=uuid.uuid4(),
        selection_criteria={"topics": ["agriculture", "governance"]},
        data_card_markdown="",
    )
    run = freeze_module.run_checks(db, object_store, settings, release)
    assert [str(i.submission.id) for i in run.items] == [farming]
    assert run.items[0].record["topics"] == ["agriculture"]
