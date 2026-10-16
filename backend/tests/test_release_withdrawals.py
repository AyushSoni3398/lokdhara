"""What withdrawals and narrower consent do to frozen releases (docs/DATASET_VERSIONING.md §2,
docs/DATA_RETENTION_AND_DELETION.md §2.4 and §3). Synthetic data only."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.identity.service import utcnow
from app.modules.releases import withdrawals
from app.modules.releases.models import DatasetReleaseItem
from app.object_store import ObjectStore
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import accepted_text_item, give_consent, own_speaker

pytestmark = requires_postgres

DATASETS = "/api/v1/datasets"
PURPOSE = {"purpose_statement": "Compare spellings across villages."}


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


@pytest.fixture
def researcher(make_user: MakeUser) -> TestUser:
    return make_user("kiran", "researcher")


@pytest.fixture
def items(client: TestClient, engine: Engine, db: Session, make_user: MakeUser) -> dict[str, str]:
    """Two research items by asha, one by ravi."""
    act_as(client, make_user("asha", "contributor"))
    asha = own_speaker(client)
    give_consent(client, db, asha, allow_research=True)
    story = accepted_text_item(client, engine, asha, "नदी के किनारे")
    song = accepted_text_item(client, engine, asha, "एक गीत", content_type="song")
    act_as(client, make_user("ravi", "contributor"))
    ravi = own_speaker(client)
    give_consent(client, db, ravi, allow_research=True)
    other = accepted_text_item(client, engine, ravi, "दूसरा वाक्य")
    return {"asha": asha, "story": story, "song": song, "other": other}


def frozen_release(client: TestClient, admin: TestUser, slug: str = "mundari-pilot") -> Any:
    act_as(client, admin)
    draft = client.post(DATASETS, json={"slug": slug, "purpose": "internal_research"}).json()
    response = client.post(f"{DATASETS}/{draft['id']}/freeze", json={"version": "0.1.0"})
    assert response.status_code == 200, response.text
    return response.json()


def marked(db: Session, release_id: str) -> set[str]:
    db.expire_all()
    return {
        str(item.submission_id)
        for item in db.scalars(
            select(DatasetReleaseItem).where(
                DatasetReleaseItem.release_id == uuid.UUID(release_id),
                DatasetReleaseItem.withdrawn_after_release_at.is_not(None),
            )
        )
    }


def test_a_withdrawn_item_is_marked_and_its_release_no_longer_exported(
    client: TestClient,
    db: Session,
    object_store: ObjectStore,
    items: dict[str, str],
    admin: TestUser,
    researcher: TestUser,
) -> None:
    release = frozen_release(client, admin)
    act_as(client, researcher)
    request = client.post(f"{DATASETS}/{release['id']}/exports", json=PURPOSE).json()

    affected = withdrawals.mark_withdrawn(
        db,
        object_store,
        submission_ids=[uuid.UUID(items["story"])],
        actor_id=admin.id,
        now=utcnow(),
        context=None,
    )
    db.commit()
    assert affected == 1
    assert marked(db, release["id"]) == {items["story"]}

    closed = client.get(f"/api/v1/exports/{request['id']}").json()
    assert (closed["status"], closed["decision_note"]) == ("rejected", withdrawals.EXPORT_NOTE)
    again = client.post(f"{DATASETS}/{release['id']}/exports", json=PURPOSE)
    assert again.json()["code"] == "release_has_withdrawn_items"
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "release.items_withdrawn"))
    assert event is not None
    assert event.details == {"items": 1, "reason": "withdrawn", "exports_closed": 1}

    # Marking again changes nothing.
    assert (
        withdrawals.mark_withdrawn(
            db,
            object_store,
            submission_ids=[uuid.UUID(items["story"])],
            actor_id=admin.id,
            now=utcnow(),
            context=None,
        )
        == 0
    )
