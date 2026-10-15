"""Reporting an item and the admin's answer (ADR-021, docs/ROADMAP.md M6). Synthetic data only."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.processing import (
    handlers,  # noqa: F401 - registers text.derive
    queue,
)
from app.modules.reports.models import Report
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
