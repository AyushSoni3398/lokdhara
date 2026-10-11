"""Sign-in, sessions, CSRF, throttling (docs/ACCESS_CONTROL.md §4)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.identity.models import User, UserSession
from tests.conftest import MakeUser, login, requires_postgres

pytestmark = requires_postgres

LOGIN = "/api/v1/auth/login"


def _actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


def test_login_sets_http_only_session_cookie(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("asha", "contributor")
    response = client.post(LOGIN, json={"username": "Asha", "password": user.password})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "asha"
    assert body["roles"] == [{"role": "contributor", "scope": None}]
    assert body["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert "lkd_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "password_hash" not in response.text


def test_me_requires_a_session(client: TestClient, make_user: MakeUser) -> None:
    assert client.get("/api/v1/auth/me").json()["code"] == "not_authenticated"
    user = make_user("asha", "reviewer")
    login(client, user)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["roles"] == [{"role": "reviewer", "scope": None}]


def test_wrong_password_and_unknown_user_look_the_same(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    make_user("asha", "contributor")
    wrong = client.post(LOGIN, json={"username": "asha", "password": "not the password"})
    unknown = client.post(LOGIN, json={"username": "nobody", "password": "not the password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.headers["content-type"] == "application/problem+json"
    assert _actions(db) == ["auth.login_failed", "auth.login_failed"]


def test_suspended_user_cannot_sign_in(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    user = make_user("asha", "contributor")
    db.execute(update(User).where(User.id == user.id).values(status="suspended"))
    db.commit()
    response = client.post(LOGIN, json={"username": "asha", "password": user.password})
    assert response.status_code == 401


def test_repeated_failures_lock_the_account(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("asha", "contributor")
    for _ in range(5):
        client.post(LOGIN, json={"username": "asha", "password": "wrong password"})
    locked = client.post(LOGIN, json={"username": "asha", "password": user.password})
    assert locked.status_code == 429
    assert locked.json()["code"] == "login_locked"
    assert int(locked.headers["retry-after"]) > 0


def test_success_resets_the_failure_count(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("asha", "contributor")
    for _ in range(4):
        client.post(LOGIN, json={"username": "asha", "password": "wrong password"})
    login(client, user)
    for _ in range(4):
        client.post(LOGIN, json={"username": "asha", "password": "wrong password"})
    assert client.post(LOGIN, json={"username": "asha", "password": user.password}).is_success


def test_unsafe_requests_need_the_csrf_token(client: TestClient, make_user: MakeUser) -> None:
    login(client, make_user("asha", "contributor"))
    missing = client.post("/api/v1/auth/logout")
    forged = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "0" * 64})
    assert missing.status_code == forged.status_code == 403
    assert missing.json()["code"] == "csrf_failed"


def test_logout_revokes_the_session(client: TestClient, make_user: MakeUser, db: Session) -> None:
    csrf = login(client, make_user("asha", "contributor"))
    old_cookie = client.cookies["lkd_session"]
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    client.cookies.set("lkd_session", old_cookie)  # replaying the old cookie must not work
    assert client.get("/api/v1/auth/me").status_code == 401
    assert db.scalar(select(UserSession.revoked_at)) is not None
    assert _actions(db) == ["auth.login", "auth.logout"]


def _age_session(db: Session, hours: float) -> None:
    db.execute(
        update(UserSession).values(last_seen_at=UserSession.last_seen_at - timedelta(hours=hours))
    )
    db.commit()


def test_staff_sessions_expire_after_12_idle_hours(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    login(client, make_user("ravi", "reviewer"))
    _age_session(db, 13)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_contributor_sessions_survive_a_day_idle(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    login(client, make_user("asha", "contributor"))
    _age_session(db, 24)
    assert client.get("/api/v1/auth/me").status_code == 200


def test_session_token_is_stored_hashed(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    login(client, make_user("asha", "contributor"))
    stored = db.scalar(select(UserSession.token_hash))
    assert stored is not None
    assert stored != client.cookies["lkd_session"]


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    response = client.post(LOGIN, json={"username": "", "password": "secret-value-123"})
    assert response.status_code == 422
    assert "secret-value-123" not in response.text
    assert response.json()["code"] == "validation_failed"


def test_many_failures_from_one_network_lock_that_network(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user("asha", "contributor")
    for attempt in range(20):
        client.post(LOGIN, json={"username": f"guess{attempt}", "password": "wrong password"})
    locked = client.post(LOGIN, json={"username": "asha", "password": user.password})
    assert locked.status_code == 429
