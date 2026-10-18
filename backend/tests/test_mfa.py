"""Two-step sign-in for admins (docs/ACCESS_CONTROL.md §4, ADR-025)."""

import base64
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.identity import mfa
from app.modules.identity.models import UserMfa
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres

RFC_SECRET = b"12345678901234567890"  # RFC 6238 appendix B, SHA-1


@pytest.mark.parametrize(
    ("unix_time", "code"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_codes_match_the_rfc_test_vectors(unix_time: int, code: str) -> None:
    assert mfa.code_for(RFC_SECRET, mfa.step_at(datetime.fromtimestamp(unix_time, UTC))) == code


def test_a_code_is_accepted_one_step_either_side_and_only_once() -> None:
    now = datetime.fromtimestamp(1111111109, UTC)
    step = mfa.step_at(now)
    for offset in (-1, 0, 1):
        code = mfa.code_for(RFC_SECRET, step + offset)
        assert mfa.matching_step(RFC_SECRET, code, now, 0) == step + offset
        assert mfa.matching_step(RFC_SECRET, code, now, step + offset) is None  # used
    assert mfa.matching_step(RFC_SECRET, mfa.code_for(RFC_SECRET, step + 2), now, 0) is None
    assert mfa.matching_step(RFC_SECRET, "081 804", now, 0) == step
    assert mfa.matching_step(RFC_SECRET, "08180", now, 0) is None
    assert mfa.matching_step(RFC_SECRET, "abcdef", now, 0) is None


def test_secrets_are_bound_to_their_user(settings: Settings) -> None:
    cipher, user = mfa.MfaCipher(settings), uuid.uuid4()
    sealed = cipher.encrypt(user, RFC_SECRET)
    assert cipher.decrypt(user, sealed) == RFC_SECRET
    with pytest.raises(mfa.MfaSecretError):
        cipher.decrypt(uuid.uuid4(), sealed)


def test_recovery_codes_are_readable_and_distinct() -> None:
    codes = mfa.new_recovery_codes()
    assert len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    assert not set("".join(codes)) & set("01OIL")


def test_the_provisioning_link_and_qr_code() -> None:
    uri = mfa.provisioning_uri(RFC_SECRET, "asha")
    assert uri.startswith("otpauth://totp/Lokdhara%3Aasha?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert mfa.qr_svg(uri).startswith("<svg")


# ------------------------------------------------------------------ the sign-in flow

ME, STATUS = "/api/v1/auth/me", "/api/v1/admin/status"


@pytest.fixture
def required(settings: Settings) -> Settings:
    settings.require_admin_mfa = True
    return settings


def _secret(text: str) -> bytes:
    return base64.b32decode(text + "=" * (-len(text) % 8))


def _code(secret: bytes, offset: int = 0) -> str:
    return mfa.code_for(secret, mfa.step_at(datetime.now(UTC)) + offset)


def _set_up(client: TestClient, admin: TestUser) -> tuple[bytes, list[str], str]:
    """Returns the secret, the recovery codes, and the code used to confirm."""
    act_as(client, admin)
    started = client.post("/api/v1/auth/mfa/setup").json()
    secret = _secret(started["secret"])
    first = _code(secret)
    confirmed = client.post("/api/v1/auth/mfa/confirm", json={"code": first})
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"], first


def _login(client: TestClient, user: TestUser, code: str | None = None) -> dict[str, object]:
    client.cookies.clear()
    body = {"username": user.username, "password": user.password, "code": code}
    response = client.post("/api/v1/auth/login", json=body)
    result: dict[str, object] = response.json()
    if response.status_code == 200:
        client.headers["X-CSRF-Token"] = str(result["csrf_token"])
    return result


@requires_postgres
def test_an_admin_without_two_step_sign_in_is_not_an_admin_yet(
    client: TestClient, make_user: MakeUser, required: Settings
) -> None:
    act_as(client, make_user("asha", "admin", "researcher"))
    me = client.get(ME).json()
    assert (me["mfa_enabled"], me["mfa_setup_required"]) == (False, True)
    assert [r["role"] for r in me["roles"]] == ["researcher"]
    assert client.get(STATUS).status_code == 403


@requires_postgres
def test_others_need_nothing_and_admins_need_nothing_in_development(
    client: TestClient, make_user: MakeUser, settings: Settings
) -> None:
    act_as(client, make_user("ravi", "contributor"))
    assert client.get(ME).json()["mfa_setup_required"] is False
    act_as(client, make_user("asha", "admin"))
    assert client.get(STATUS).status_code == 200


@requires_postgres
def test_setting_it_up_gives_the_admin_role_back(
    client: TestClient, db: Session, make_user: MakeUser, required: Settings
) -> None:
    admin = make_user("asha", "admin")
    act_as(client, admin)
    started = client.post("/api/v1/auth/mfa/setup").json()
    assert started["qr_svg"].startswith("<svg") and "otpauth://totp/" in started["uri"]
    wrong = client.post("/api/v1/auth/mfa/confirm", json={"code": "000000"})
    assert wrong.json()["code"] == "invalid_mfa_code"

    secret = _secret(started["secret"])
    codes = client.post("/api/v1/auth/mfa/confirm", json={"code": _code(secret)}).json()
    assert len(codes["recovery_codes"]) == 10
    assert client.get(ME).json()["mfa_enabled"] is True
    assert client.get(STATUS).status_code == 200
    again = client.post("/api/v1/auth/mfa/setup").json()
    assert again["code"] == "mfa_already_enabled"
    stored = db.scalar(select(UserMfa))
    assert stored is not None and _secret(started["secret"]) not in stored.secret_enc
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.mfa_enabled"))


@requires_postgres
def test_confirming_signs_out_the_other_sessions(
    client: TestClient, make_user: MakeUser, required: Settings
) -> None:
    admin = make_user("asha", "admin")
    act_as(client, admin)
    other_cookie = client.cookies.get("lkd_session")
    _set_up(client, admin)
    assert client.get(ME).status_code == 200
    client.cookies.set("lkd_session", str(other_cookie))
    assert client.get(ME).status_code == 401


@requires_postgres
def test_signing_in_needs_a_fresh_code(
    client: TestClient, db: Session, make_user: MakeUser, required: Settings
) -> None:
    admin = make_user("asha", "admin")
    secret, _, first = _set_up(client, admin)
    assert _login(client, admin)["code"] == "mfa_required"
    assert _login(client, admin, first)["code"] == "invalid_mfa_code"  # already used
    signed_in = _login(client, admin, _code(secret, 1))
    assert "admin" in [r["role"] for r in signed_in["roles"]]  # type: ignore[attr-defined]
    assert client.get(STATUS).status_code == 200
    failed = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed")).all()
    assert [e.details for e in failed] == [{"step": "mfa"}]


@requires_postgres
def test_wrong_codes_count_towards_the_lockout(
    client: TestClient, make_user: MakeUser, required: Settings
) -> None:
    admin = make_user("asha", "admin")
    secret, _, _ = _set_up(client, admin)
    for _ in range(required.login_max_failures):
        assert _login(client, admin, "000000")["code"] == "invalid_mfa_code"
    assert _login(client, admin, _code(secret, 1))["code"] == "login_locked"


@requires_postgres
def test_a_recovery_code_works_once(
    client: TestClient, db: Session, make_user: MakeUser, required: Settings
) -> None:
    admin = make_user("asha", "admin")
    _, codes, _ = _set_up(client, admin)
    assert "csrf_token" in _login(client, admin, codes[0].lower())
    assert _login(client, admin, codes[0])["code"] == "invalid_mfa_code"
    used = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.mfa_recovery_code_used"))
    assert used is not None and used.details == {"codes_left": 9}


@requires_postgres
def test_the_server_command_resets_a_lost_phone(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    db: Session,
    make_user: MakeUser,
    required: Settings,
) -> None:
    admin = make_user("asha", "admin")
    _set_up(client, admin)
    monkeypatch.setattr(cli, "get_engine", lambda: db.get_bind())
    assert cli.main(["reset-mfa", "--username", "asha"]) == 0
    assert client.get(ME).status_code == 401  # signed out everywhere
    assert _login(client, admin)["mfa_setup_required"] is True
    assert cli.main(["reset-mfa", "--username", "nobody"]) == 1
