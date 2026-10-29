"""The topic list (ADR-030): offered to everyone signed in, extended and retired by admins."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from tests.conftest import MakeUser, act_as, requires_postgres

pytestmark = requires_postgres

ADMIN = "/api/v1/admin/topics"


def _keys(client: TestClient) -> list[str]:
    response = client.get("/api/v1/topics")
    assert response.status_code == 200, response.text
    return [t["key"] for t in response.json()["items"]]


def test_the_starting_list_is_offered_in_order(client: TestClient, make_user: MakeUser) -> None:
    act_as(client, make_user("asha", "contributor"))
    keys = _keys(client)
    assert keys[:2] == ["agriculture", "forest_and_nature"]
    assert {"health_and_medicine", "governance", "education", "other"} <= set(keys)
    first = client.get("/api/v1/topics").json()["items"][0]
    assert first == {
        "key": "agriculture",
        "label_en": "Agriculture and farming",
        "label_hi": "खेती-बाड़ी",
    }


def test_admins_add_rename_and_retire_topics(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    act_as(client, make_user("root", "admin"))
    body = {"key": "fishing", "label_en": "Fishing", "label_hi": "मछली पकड़ना", "sort_order": 5}
    created = client.post(ADMIN, json=body)
    assert created.status_code == 201, created.text
    assert client.post(ADMIN, json=body).json()["code"] == "topic_exists"
    assert client.post(ADMIN, json=body | {"key": "Bad Key"}).status_code == 422
    assert _keys(client)[1] == "fishing"  # sorted by sort_order

    renamed = client.patch(f"{ADMIN}/fishing", json={"label_en": "Fishing and rivers"})
    assert renamed.json()["label_en"] == "Fishing and rivers"
    retired = client.patch(f"{ADMIN}/fishing", json={"retired": True})
    assert retired.json()["retired_at"] is not None
    assert "fishing" not in _keys(client)
    assert "fishing" in [t["key"] for t in client.get(ADMIN).json()["items"]]
    assert client.patch(f"{ADMIN}/fishing", json={"retired": False}).json()["retired_at"] is None
    assert client.patch(f"{ADMIN}/nothing", json={}).json()["code"] == "topic_not_found"

    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.target_type == "topic"))
    assert sorted(actions) == ["topic.create", "topic.update", "topic.update", "topic.update"]


def test_only_admins_change_the_list(client: TestClient, make_user: MakeUser) -> None:
    act_as(client, make_user("kiran", "researcher"))
    body = {"key": "fishing", "label_en": "Fishing", "label_hi": "मछली पकड़ना"}
    assert client.post(ADMIN, json=body).status_code == 403
    assert client.get(ADMIN).status_code == 403
