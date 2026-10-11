"""Invitations, role administration, password resets (docs/API_SPECIFICATION.md §2)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.identity.models import Invitation, UserRole
from tests.conftest import MakeUser, TestUser, login, requires_postgres

pytestmark = requires_postgres


def _admin_session(client: TestClient, make_user: MakeUser) -> tuple[TestUser, dict[str, str]]:
    admin = make_user("admin1", "admin")
    return admin, {"X-CSRF-Token": login(client, admin)}


def _invite(client: TestClient, headers: dict[str, str], role: str = "contributor") -> str:
    response = client.post("/api/v1/auth/invitations", json={"role": role}, headers=headers)
    assert response.status_code == 201, response.text
    url = response.json()["invite_url"]
    assert "#" in url  # token in the fragment, never sent to servers in a path
    return str(url.split("#", 1)[1])


def _accept(client: TestClient, token: str, username: str = "asha") -> int:
    return client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": token,
            "username": username,
            "display_name": "Asha",
            "password": "a long passphrase",
        },
    ).status_code


def test_invitation_creates_an_account_with_the_invited_role(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    _, headers = _admin_session(client, make_user)
    token = _invite(client, headers, role="facilitator")
    client.cookies.clear()
    assert _accept(client, token) == 201
    roles = db.scalars(select(UserRole.role).where(UserRole.role == "facilitator")).all()
    assert roles == ["facilitator"]
    signed_in = client.post(
        "/api/v1/auth/login", json={"username": "asha", "password": "a long passphrase"}
    )
    assert signed_in.status_code == 200
    details = " ".join(str(d) for d in db.scalars(select(AuditEvent.details)))
    assert token not in details


def test_invitation_works_once(client: TestClient, make_user: MakeUser) -> None:
    _, headers = _admin_session(client, make_user)
    token = _invite(client, headers)
    assert _accept(client, token, "asha") == 201
    assert _accept(client, token, "birsa") == 404


def test_expired_invitation_is_rejected(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    _, headers = _admin_session(client, make_user)
    token = _invite(client, headers)
    db.execute(update(Invitation).values(expires_at=Invitation.created_at - timedelta(seconds=1)))
    db.commit()
    assert _accept(client, token) == 404


def test_taken_username_and_weak_password_are_rejected(
    client: TestClient, make_user: MakeUser
) -> None:
    _, headers = _admin_session(client, make_user)
    assert _accept(client, _invite(client, headers), username="admin1") == 409
    weak = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": _invite(client, headers),
            "username": "asha",
            "display_name": "Asha",
            "password": "short",
        },
    )
    assert weak.json()["code"] == "weak_password"


def test_only_admins_invite(client: TestClient, make_user: MakeUser) -> None:
    reviewer = make_user("ravi", "reviewer")
    headers = {"X-CSRF-Token": login(client, reviewer)}
    response = client.post("/api/v1/auth/invitations", json={"role": "admin"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_grant_and_revoke_roles_are_audited(
    client: TestClient, make_user: MakeUser, db: Session
) -> None:
    _, headers = _admin_session(client, make_user)
    user = make_user("asha", "contributor")
    base = f"/api/v1/admin/users/{user.id}/roles"
    granted = client.post(
        base, json={"role": "reviewer", "scope": "culturally_restricted"}, headers=headers
    )
    assert granted.status_code == 204
    duplicate = client.post(
        base, json={"role": "reviewer", "scope": "culturally_restricted"}, headers=headers
    )
    assert duplicate.status_code == 409
    assert client.delete(f"{base}/reviewer", headers=headers).status_code == 204
    assert client.delete(f"{base}/reviewer", headers=headers).status_code == 404
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"role.grant", "role.revoke"} <= actions


def test_last_admin_cannot_be_removed(client: TestClient, make_user: MakeUser) -> None:
    admin, headers = _admin_session(client, make_user)
    response = client.delete(f"/api/v1/admin/users/{admin.id}/roles/admin", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "last_admin"
    second = make_user("admin2", "admin")
    assert (
        client.delete(f"/api/v1/admin/users/{second.id}/roles/admin", headers=headers).status_code
        == 204
    )


def test_revoking_sessions_signs_the_user_out(client: TestClient, make_user: MakeUser) -> None:
    user = make_user("asha", "contributor")
    login(client, user)
    user_cookie = client.cookies["lkd_session"]
    client.cookies.clear()
    _, headers = _admin_session(client, make_user)
    revoked = client.post(f"/api/v1/admin/users/{user.id}/sessions/revoke", headers=headers)
    assert revoked.json() == {"revoked": 1}
    client.cookies.clear()
    client.cookies.set("lkd_session", user_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_changes_password_once_and_signs_out(
    client: TestClient, make_user: MakeUser
) -> None:
    user = make_user("asha", "contributor")
    login(client, user)
    user_cookie = client.cookies["lkd_session"]
    client.cookies.clear()
    _, headers = _admin_session(client, make_user)
    created = client.post(f"/api/v1/admin/users/{user.id}/password-reset", headers=headers)
    token = created.json()["reset_url"].split("#", 1)[1]
    client.cookies.clear()
    body = {"token": token, "password": "a brand new passphrase"}
    assert client.post("/api/v1/auth/password-reset", json=body).status_code == 204
    assert client.post("/api/v1/auth/password-reset", json=body).status_code == 404
    client.cookies.set("lkd_session", user_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    new_login = client.post(
        "/api/v1/auth/login", json={"username": "asha", "password": "a brand new passphrase"}
    )
    assert new_login.status_code == 200
