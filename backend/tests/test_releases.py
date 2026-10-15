"""Dataset releases (docs/DATASET_VERSIONING.md, ROADMAP M7). Synthetic data only."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

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
