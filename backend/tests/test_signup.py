"""Public sign-up (ADR-028, docs/API_SPECIFICATION.md §2)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.identity.models import UserRole
from tests.conftest import MakeUser, requires_postgres

pytestmark = requires_postgres

SIGNUP = "/api/v1/auth/signup"


def _signup(client: TestClient, username: str = "asha", **changes: str) -> dict[str, object]:
    body = {
        "username": username,
        "display_name": "Asha",
        "password": "a long passphrase",
        **changes,
    }
    response = client.post(SIGNUP, json=body)
    return {"status": response.status_code, **response.json()}


def test_signup_makes_a_signed_in_contributor(client: TestClient, db: Session) -> None:
    result = _signup(client, "Asha")
    assert result["status"] == 201
    assert result["roles"] == [{"role": "contributor", "scope": None}]
    assert result["user"]["username"] == "asha"  # type: ignore[index]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert db.scalars(select(UserRole.role)).all() == ["contributor"]
    actions = db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)).all()
    assert actions == ["auth.signup", "auth.login"]


def test_new_account_can_sign_in_again(client: TestClient) -> None:
    _signup(client)
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login", json={"username": "asha", "password": "a long passphrase"}
    )
    assert response.status_code == 200


def test_signup_rejects_a_taken_username(client: TestClient, make_user: MakeUser) -> None:
    make_user("asha", "contributor")
    result = _signup(client, "ASHA")
    assert (result["status"], result["code"]) == (409, "username_taken")


def test_signup_applies_the_password_policy(client: TestClient) -> None:
    short = _signup(client, password="short")
    assert (short["status"], short["code"]) == (422, "weak_password")
    with_name = _signup(client, password="asha-is-my-password")
    assert (with_name["status"], with_name["code"]) == (422, "weak_password")


def test_signup_cannot_choose_a_role(client: TestClient, db: Session) -> None:
    assert _signup(client, role="admin")["status"] == 201
    assert db.scalars(select(UserRole.role)).all() == ["contributor"]


def test_signup_is_limited_per_network(client: TestClient, settings: Settings) -> None:
    settings.signup_max_per_ip = 2
    assert _signup(client, "first1")["status"] == 201
    assert _signup(client, "second")["status"] == 201
    blocked = _signup(client, "third3")
    assert (blocked["status"], blocked["code"]) == (429, "signup_limited")


def test_signup_can_be_closed(client: TestClient, settings: Settings) -> None:
    settings.open_signup = False
    result = _signup(client)
    assert (result["status"], result["code"]) == (404, "signup_closed")
