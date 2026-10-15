"""The researcher catalogue (docs/ROADMAP.md M6, docs/ACCESS_CONTROL.md §3). Synthetic data only.

Which consent and flag combinations are listed is covered case by case in
test_effective_access.py; these tests check the search on top of it.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.consents import service as consents
from app.modules.identity.models import UserRole
from app.modules.identity.service import utcnow
from app.modules.processing import (
    handlers,  # noqa: F401 - registers text.derive
    queue,
)
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import SUBMISSIONS, create_draft, own_speaker

pytestmark = requires_postgres

CATALOGUE = "/api/v1/catalogue"


@pytest.fixture
def asha(make_user: MakeUser) -> TestUser:
    return make_user("asha", "contributor")


@pytest.fixture
def researcher(make_user: MakeUser) -> TestUser:
    return make_user("kiran", "researcher")


def _consent(client: TestClient, db: Session, speaker_id: str, research: bool) -> None:
    consents.ensure_dev_forms(db)
    db.commit()
    form = consents.current_form(db, Settings(_env_file=None, env="test"), "hi")
    answers = {
        "consent_form_id": str(form.id),
        "method": "in_app",
        "allow_store_and_review": True,
        "allow_research": research,
    }
    response = client.post(
        f"/api/v1/speakers/{speaker_id}/consents", data={"consent": json.dumps(answers)}
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def speaker(client: TestClient, asha: TestUser, db: Session) -> str:
    act_as(client, asha)
    speaker_id = own_speaker(client)
    _consent(client, db, speaker_id, research=True)
    return speaker_id


def _accepted(
    client: TestClient, engine: Engine, speaker_id: str, content: str, **fields: Any
) -> str:
    draft = create_draft(client, speaker_id, kind="text", recording_mode=None, **fields)
    layer = {
        "layer_type": "standalone",
        "entry_type": "sentence",
        "language_tag": "unr",
        "script_code": "Deva",
        "content": content,
    }
    url = f"{SUBMISSIONS}/{draft['id']}"
    assert client.post(f"{url}/text-layers", json=layer).status_code == 201
    assert client.post(f"{url}/submit").status_code == 200
    while queue.process_one(engine, "test-worker", 60):
        pass
    assert client.get(url).json()["status"] == "accepted"
    return str(draft["id"])


def _ids(client: TestClient, **params: Any) -> list[str]:
    response = client.get(CATALOGUE, params=params)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_researchers_find_accepted_items_marked_unverified(
    client: TestClient, engine: Engine, speaker: str, asha: TestUser, researcher: TestUser
) -> None:
    item = _accepted(client, engine, speaker, "यह एक परीक्षण वाक्य है।", title="Test story")
    assert client.get(CATALOGUE).json()["code"] == "forbidden"  # contributors have none

    act_as(client, researcher)
    [listed] = client.get(CATALOGUE).json()["items"]
    assert listed["id"] == item
    assert listed["text_preview"] == "यह एक परीक्षण वाक्य है।"
    assert listed["text_script"] == "Deva"
    assert listed["text_status"] == "unverified"
    assert listed["kind"] == "text"
    assert "speaker_id" not in listed


def test_items_without_research_consent_or_hidden_are_not_listed(
    client: TestClient,
    engine: Engine,
    db: Session,
    speaker: str,
    researcher: TestUser,
    make_user: MakeUser,
) -> None:
    listed = _accepted(client, engine, speaker, "पहला वाक्य")
    hidden = _accepted(client, engine, speaker, "दूसरा वाक्य")
    act_as(client, make_user("ravi", "contributor"))
    no_research = own_speaker(client)
    _consent(client, db, no_research, research=False)
    private = _accepted(client, engine, no_research, "तीसरा वाक्य")

    act_as(client, make_user("meera", "admin"))
    client.post(
        f"/api/v1/admin/submissions/{hidden}/hide",
        json={"restriction": "contains_pii", "note": "A name is read out."},
    )
    act_as(client, researcher)
    assert _ids(client) == [listed]
    assert hidden not in _ids(client, q="दूसरा")
    assert private not in _ids(client, q="तीसरा")


def test_a_later_no_to_research_takes_items_out(
    client: TestClient,
    engine: Engine,
    db: Session,
    speaker: str,
    asha: TestUser,
    researcher: TestUser,
) -> None:
    item = _accepted(client, engine, speaker, "एक वाक्य")
    act_as(client, researcher)
    assert _ids(client) == [item]
    act_as(client, asha)
    _consent(client, db, speaker, research=False)
    act_as(client, researcher)
    assert _ids(client) == []


def test_search_matches_titles_and_current_text_and_filters(
    client: TestClient, engine: Engine, speaker: str, researcher: TestUser
) -> None:
    story = _accepted(client, engine, speaker, "नदी के किनारे", title="River story")
    song = _accepted(client, engine, speaker, "50% गीत", content_type="song")
    act_as(client, researcher)
    assert _ids(client, q="नदी") == [story]
    assert _ids(client, q="river") == [story]
    assert _ids(client, q="50%") == [song]
    assert _ids(client, q="%") == [song]  # a literal percent sign, not "anything"
    assert _ids(client, content_type="song") == [song]
    assert _ids(client, kind="audio") == []
    assert client.get(CATALOGUE, params={"content_type": "poem"}).status_code == 422


def test_pages_follow_a_cursor(
    client: TestClient, engine: Engine, speaker: str, researcher: TestUser
) -> None:
    items = [_accepted(client, engine, speaker, f"वाक्य {n}") for n in range(3)]
    act_as(client, researcher)
    first = client.get(CATALOGUE, params={"limit": 2}).json()
    assert [i["id"] for i in first["items"]] == items[::-1][:2]
    rest = client.get(CATALOGUE, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["id"] for i in rest["items"]] == items[:1]
    assert rest["next_cursor"] is None


def test_culturally_restricted_items_need_the_scope(
    client: TestClient,
    engine: Engine,
    db: Session,
    speaker: str,
    researcher: TestUser,
    make_user: MakeUser,
) -> None:
    item = _accepted(client, engine, speaker, "एक गीत")
    act_as(client, make_user("meera", "admin"))
    client.post(
        f"/api/v1/admin/submissions/{item}/hide",
        json={"restriction": "culturally_restricted", "note": "A ritual song."},
    )
    assert _ids(client) == [item]  # admins
    act_as(client, researcher)
    assert _ids(client) == []
    steward = make_user("sita", "researcher")
    db.add(
        UserRole(
            user_id=steward.id,
            role="researcher",
            scope="culturally_restricted",
            granted_at=utcnow(),
        )
    )
    db.commit()
    act_as(client, steward)
    [listed] = client.get(CATALOGUE).json()["items"]
    assert listed["restriction_flags"] == ["culturally_restricted"]


def test_researchers_open_listed_items_read_only_and_can_report_them(
    client: TestClient, engine: Engine, speaker: str, researcher: TestUser
) -> None:
    item = _accepted(client, engine, speaker, "यह एक परीक्षण वाक्य है।")
    act_as(client, researcher)
    detail = client.get(f"{SUBMISSIONS}/{item}")
    assert detail.status_code == 200, detail.text
    layer = detail.json()["text_layers"][0]
    revisions = client.get(f"/api/v1/text-layers/{layer['id']}/revisions")
    assert revisions.status_code == 200
    edit = client.post(
        f"/api/v1/text-layers/{layer['id']}/revisions",
        json={"base_revision_id": layer["current_revision"]["id"], "content": "बदला हुआ"},
    )
    assert edit.json()["code"] in ("forbidden", "text_layer_not_found")
    assert client.patch(f"{SUBMISSIONS}/{item}", json={"title": "Mine now"}).status_code == 403
    report = client.post(f"{SUBMISSIONS}/{item}/reports", json={"reason": "wrong_content"})
    assert report.status_code == 201
    # Their own list stays their own.
    assert client.get(SUBMISSIONS).json()["items"] == []
