"""Every API path is checked for who may call it, including paths added later (security review).

The list of paths comes from the app itself, so a new endpoint that forgets its sign-in or
role check fails here rather than in production.
"""

import re
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import MakeUser, act_as, requires_postgres

# Open to anyone: health checks, and the forms used before someone has a session.
PUBLIC = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/invitations/accept"),
    ("POST", "/api/v1/auth/password-reset"),
}


def _operations() -> Iterator[tuple[str, str]]:
    for path, operations in create_app().openapi()["paths"].items():
        for method in operations:
            yield method.upper(), path


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


OPERATIONS = sorted(_operations())
ADMIN_ONLY = [(method, path) for method, path in OPERATIONS if path.startswith("/api/v1/admin/")]


def test_the_public_list_names_real_paths() -> None:
    assert set(OPERATIONS) >= PUBLIC


@requires_postgres
@pytest.mark.parametrize(("method", "path"), [op for op in OPERATIONS if op not in PUBLIC])
def test_signed_out_callers_are_refused(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, _concrete(path))
    assert response.status_code == 401, response.text


@requires_postgres
@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
def test_contributors_cannot_use_admin_paths(
    client: TestClient, make_user: MakeUser, method: str, path: str
) -> None:
    act_as(client, make_user("asha", "contributor"))
    response = client.request(method, _concrete(path), json={})
    assert response.status_code == 403, response.text
