"""Reporting an item and the admin's answer (ADR-021, docs/ROADMAP.md M6). Synthetic data only."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.identity.models import UserRole
from app.modules.identity.service import utcnow
from app.modules.processing import (
    handlers,  # noqa: F401 - registers text.derive
    queue,
)
from app.modules.reports.models import Report
from app.modules.review.models import ReviewEvent
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, give_consent, own_speaker

pytestmark = requires_postgres


@pytest.fixture
def asha(make_user: MakeUser) -> TestUser:
    return make_user("asha", "contributor")


@pytest.fixture
def item(client: TestClient, asha: TestUser, db: Session, engine: Engine) -> str:
    """An accepted text submission by asha."""
    act_as(client, asha)
    speaker = own_speaker(client)
    give_consent(client, db, speaker)
    submission_id = str(create_draft(client, speaker, kind="text", recording_mode=None)["id"])
    layer = {
        "layer_type": "standalone",
        "entry_type": "sentence",
        "language_tag": "unr",
        "script_code": "Deva",
        "content": "यह एक परीक्षण वाक्य है।",
    }
    assert client.post(f"{SUBMISSIONS}/{submission_id}/text-layers", json=layer).status_code == 201
    assert client.post(f"{SUBMISSIONS}/{submission_id}/submit").status_code == 200
    while queue.process_one(engine, "test-worker", 60):
        pass
    assert client.get(f"{SUBMISSIONS}/{submission_id}").json()["status"] == "accepted"
    return submission_id


def _report(client: TestClient, submission_id: str, **fields: Any) -> Any:
    body = {"reason": "personal_information", "note": "A phone number is read out.", **fields}
    return client.post(f"{SUBMISSIONS}/{submission_id}/reports", json=body)


def test_people_report_what_they_can_see_once_until_it_is_decided(
    client: TestClient, item: str, db: Session
) -> None:
    response = _report(client, item)
    assert response.status_code == 201, response.text
    assert response.json()["reason"] == "personal_information"
    assert _report(client, item, reason="wrong_content").json()["code"] == "already_reported"
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "report.create"))
    assert event is not None
    assert event.details == {"reason": "personal_information"}  # never the note


def test_reports_need_a_known_reason_and_clean_text(client: TestClient, item: str) -> None:
    assert _report(client, item, reason="boring").status_code == 422
    assert _report(client, item, note="x" * 1001).status_code == 422
    assert _report(client, item, note="bad‮text").status_code == 422
    assert _report(client, item, note=None).status_code == 201


def test_items_others_cannot_see_cannot_be_reported(
    client: TestClient, item: str, make_user: MakeUser, db: Session
) -> None:
    act_as(client, make_user("ravi", "contributor"))
    assert _report(client, item).json()["code"] == "submission_not_found"
    assert _report(client, str(uuid.uuid4())).json()["code"] == "submission_not_found"
    assert db.scalar(select(Report)) is None


def test_drafts_cannot_be_reported(client: TestClient, asha: TestUser, db: Session) -> None:
    act_as(client, asha)
    speaker = own_speaker(client)
    give_consent(client, db, speaker)
    draft = create_draft(client, speaker)
    assert _report(client, draft["id"]).json()["code"] == "not_reportable"


# ------------------------------------------------------------------ admin decisions

ADMIN = "/api/v1/admin"


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


def _hide(client: TestClient, submission_id: str, restriction: str = "contains_pii") -> Any:
    return client.post(
        f"{ADMIN}/submissions/{submission_id}/hide",
        json={"restriction": restriction, "note": "The number is clearly audible."},
    )


def test_admins_see_open_reports_grouped_by_item(
    client: TestClient, item: str, admin: TestUser, make_user: MakeUser
) -> None:
    assert _report(client, item).status_code == 201
    act_as(client, make_user("ravi", "admin"))
    assert _report(client, item, reason="wrong_content", note=None).status_code == 201
    act_as(client, admin)
    items = client.get(f"{ADMIN}/reports").json()["items"]
    assert len(items) == 1
    assert items[0]["submission"]["id"] == item
    assert [r["reason"] for r in items[0]["reports"]] == ["personal_information", "wrong_content"]


def test_hiding_flags_the_item_closes_its_reports_and_is_recorded(
    client: TestClient, item: str, admin: TestUser, db: Session
) -> None:
    assert _report(client, item).status_code == 201
    act_as(client, admin)
    response = _hide(client, item)
    assert response.status_code == 200, response.text
    assert response.json()["restriction_flags"] == ["contains_pii"]
    assert client.get(f"{ADMIN}/reports").json()["items"] == []

    decided = db.scalars(select(Report)).one()
    assert (decided.decision, decided.decided_by) == ("hidden", admin.id)
    assert decided.decision_note == "The number is clearly audible."
    events = db.scalars(select(ReviewEvent).where(ReviewEvent.submission_id == uuid.UUID(item)))
    assert [(e.action, e.restriction) for e in events] == [("add_restriction", "contains_pii")]
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "report.hide"))
    assert audit is not None
    assert audit.details == {"restriction": "contains_pii", "reports_closed": 1}

    # Hiding again with the same flag changes nothing; un-hiding removes the flag.
    assert _hide(client, item).json()["restriction_flags"] == ["contains_pii"]
    unhidden = client.post(
        f"{ADMIN}/submissions/{item}/unhide",
        json={"restriction": "contains_pii", "note": "The number was a made-up example."},
    )
    assert unhidden.json()["restriction_flags"] == []
    again = client.post(
        f"{ADMIN}/submissions/{item}/unhide",
        json={"restriction": "contains_pii", "note": "Twice."},
    )
    assert again.json()["code"] == "not_restricted"


def test_dismissing_closes_reports_and_leaves_the_item_alone(
    client: TestClient, item: str, admin: TestUser, db: Session
) -> None:
    assert _report(client, item, reason="wrong_content").status_code == 201
    act_as(client, admin)
    dismiss = f"{ADMIN}/submissions/{item}/dismiss-reports"
    response = client.post(dismiss, json={"note": "This is Mundari."})
    assert response.json()["restriction_flags"] == []
    assert db.scalars(select(Report.decision)).all() == ["dismissed"]
    assert client.post(dismiss, json={"note": "Again."}).json()["code"] == "no_open_reports"


def test_decisions_need_a_reason_an_admin_and_someone_else_s_item(
    client: TestClient, item: str, asha: TestUser, make_user: MakeUser, db: Session
) -> None:
    # asha reports her own item; she cannot decide on it even as an admin.
    assert _report(client, item).status_code == 201
    assert _hide(client, item).json()["code"] == "forbidden"
    db.add(UserRole(user_id=asha.id, role="admin", granted_at=utcnow()))
    db.commit()
    act_as(client, asha)
    assert _hide(client, item).json()["code"] == "own_submission"

    act_as(client, make_user("meera", "admin"))
    no_reason = client.post(f"{ADMIN}/submissions/{item}/hide", json={"restriction": "minor"})
    assert no_reason.status_code == 422
    assert _hide(client, item, restriction="secret").status_code == 422
    assert _hide(client, str(uuid.uuid4())).json()["code"] == "submission_not_found"
