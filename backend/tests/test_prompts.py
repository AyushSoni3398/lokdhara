"""The prompt library (ADR-018, docs/RECORDING_MODES.md, docs/API_SPECIFICATION.md §4a)."""

import json
import struct
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.image_formats import sniff_image
from app.modules.audit.models import AuditEvent
from app.modules.prompts import service
from app.modules.prompts.dev_images import SCENES, draw_png
from app.modules.prompts.models import Prompt
from app.object_store import Bucket, ObjectStore
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres

pytestmark = requires_postgres

ADMIN = "/api/v1/admin/prompts"
# First bytes of each format: enough for the format check. Generated, never real media.
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
FAKE_OGG = b"OggS\x00\x02" + b"\x00" * 64


def _situation(key: str = "farm-morning", **extra: Any) -> dict[str, Any]:
    return {
        "prompt_key": key,
        "prompt_type": "situation",
        "text": "Describe a morning in the fields.",
        "text_language_tag": "en",
        "source_and_licence": "written by the team, CC BY 4.0",
        "topic_tags": ["farming"],
        **extra,
    }


def _create(
    client: TestClient,
    body: dict[str, Any],
    image: bytes | None = None,
    audio: bytes | None = None,
) -> Any:
    files = {}
    if image is not None:
        files["image"] = ("picture.png", image, "image/png")
    if audio is not None:
        files["audio"] = ("spoken.ogg", audio, "audio/ogg")
    return client.post(ADMIN, data={"prompt": json.dumps(body)}, files=files or None)


@pytest.fixture
def admin(client: TestClient, make_user: MakeUser) -> TestUser:
    user = make_user("admin", "admin")
    act_as(client, user)
    return user


def _approved(client: TestClient, body: dict[str, Any], **files: bytes) -> dict[str, Any]:
    created = _create(client, body, **files)
    assert created.status_code == 201, created.text
    approved = client.post(f"{ADMIN}/{created.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    result: dict[str, Any] = approved.json()
    return result


def _media_files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "objects" / "test-derived").rglob("*") if p.is_file()]


# ------------------------------------------------------------------ library management


def test_new_prompts_are_drafts_and_creation_is_audited(
    client: TestClient, admin: TestUser, db: Session
) -> None:
    response = _create(client, _situation())
    assert response.status_code == 201, response.text
    prompt = response.json()
    assert (prompt["status"], prompt["version"], prompt["has_image"]) == ("draft", 1, False)
    assert db.scalar(select(AuditEvent.action).order_by(AuditEvent.occurred_at.desc())) == (
        "prompt.create"
    )
    again = _create(client, _situation())
    assert again.json()["code"] == "prompt_key_taken"


def test_each_prompt_type_needs_its_content(client: TestClient, admin: TestUser) -> None:
    assert _create(client, _situation(text=None)).status_code == 422
    read = _situation("read-one", prompt_type="read_sentence", script_code=None)
    assert _create(client, read).status_code == 422
    image = _situation("img-one", prompt_type="image", text=None)
    assert _create(client, image).json()["code"] == "image_mismatch"
    assert _create(client, _situation("sit-two"), image=FAKE_PNG).json()["code"] == (
        "image_mismatch"
    )
    created = _create(client, image, image=FAKE_PNG)
    assert created.status_code == 201, created.text
    assert created.json()["has_image"] is True


def test_media_must_be_a_supported_format(
    client: TestClient, admin: TestUser, tmp_path: Path
) -> None:
    image = _situation("img-svg", prompt_type="image", text=None)
    svg = _create(client, image, image=b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    assert svg.json()["code"] == "image_unsupported"
    bad_audio = _create(client, _situation(), audio=b"not audio at all")
    assert bad_audio.json()["code"] == "audio_unsupported"
    assert _media_files(tmp_path) == []


def test_oversized_media_is_refused_and_not_kept(
    client: TestClient, admin: TestUser, tmp_path: Path, settings: Any
) -> None:
    settings.prompt_image_max_bytes = 16
    image = _situation("img-big", prompt_type="image", text=None)
    assert _create(client, image, image=FAKE_PNG).status_code == 413
    assert _media_files(tmp_path) == []


def test_only_staff_manage_the_library_and_only_admins_approve(
    client: TestClient, make_user: MakeUser
) -> None:
    act_as(client, make_user("asha", "contributor"))
    assert _create(client, _situation()).status_code == 403
    assert client.get(ADMIN).status_code == 403

    act_as(client, make_user("rita", "reviewer"))
    draft = _create(client, _situation())
    assert draft.status_code == 201
    assert client.post(f"{ADMIN}/{draft.json()['id']}/approve").status_code == 403
    assert [p["prompt_key"] for p in client.get(ADMIN).json()["items"]] == ["farm-morning"]


def test_editing_creates_a_new_draft_version(
    client: TestClient, admin: TestUser, db: Session
) -> None:
    first = _approved(client, _situation())
    edited = client.post(
        f"{ADMIN}/{first['id']}/versions",
        data={"prompt": json.dumps({"text": "Describe an evening in the fields."})},
    )
    assert edited.status_code == 201, edited.text
    second = edited.json()
    assert (second["version"], second["status"]) == (2, "draft")
    assert second["topic_tags"] == ["farming"]  # copied from version 1
    original = db.get(Prompt, uuid.UUID(first["id"]))
    assert original is not None and original.text == "Describe a morning in the fields."

    approved = client.post(f"{ADMIN}/{second['id']}/approve").json()
    assert approved["status"] == "approved"
    statuses = client.get(ADMIN, params={"status": "retired"}).json()["items"]
    assert [p["id"] for p in statuses] == [first["id"]]


def test_a_version_cannot_drop_required_content(client: TestClient, admin: TestUser) -> None:
    read = _approved(
        client, _situation("read-one", prompt_type="read_sentence", script_code="Latn")
    )
    response = client.post(
        f"{ADMIN}/{read['id']}/versions", data={"prompt": json.dumps({"script_code": None})}
    )
    assert response.json()["code"] == "prompt_invalid"


def test_approval_and_retirement_rules(client: TestClient, admin: TestUser) -> None:
    prompt = _approved(client, _situation())
    assert client.post(f"{ADMIN}/{prompt['id']}/approve").json()["code"] == "prompt_not_draft"
    assert client.post(f"{ADMIN}/{prompt['id']}/retire").json()["status"] == "retired"
    assert client.post(f"{ADMIN}/{prompt['id']}/retire").json()["code"] == "prompt_retired"
    draft = _create(client, _situation("other-key")).json()
    assert client.post(f"{ADMIN}/{draft['id']}/retire").json()["status"] == "retired"


# ------------------------------------------------------------------ what contributors see


def test_contributors_get_approved_prompts_only(
    client: TestClient, admin: TestUser, make_user: MakeUser
) -> None:
    draft = _create(client, _situation("draft-one")).json()
    approved = _approved(client, _situation("approved-one"))

    act_as(client, make_user("asha", "contributor"))
    shown = client.get("/api/v1/prompts/next", params={"type": "situation"})
    assert shown.status_code == 200, shown.text
    assert shown.json()["id"] == approved["id"]
    assert client.get(f"/api/v1/prompts/{draft['id']}").status_code == 404
    none_left = client.get(
        "/api/v1/prompts/next", params={"type": "situation", "exclude": [approved["id"]]}
    )
    assert none_left.json()["code"] == "no_prompt_available"


def test_researchers_are_not_shown_prompts(
    client: TestClient, admin: TestUser, make_user: MakeUser
) -> None:
    _approved(client, _situation())
    act_as(client, make_user("meera", "researcher"))
    assert client.get("/api/v1/prompts/next", params={"type": "situation"}).status_code == 403


def test_read_prompts_filter_by_script(
    client: TestClient, admin: TestUser, make_user: MakeUser
) -> None:
    latin = _approved(
        client, _situation("read-latn", prompt_type="read_sentence", script_code="Latn")
    )
    _approved(client, _situation("read-deva", prompt_type="read_sentence", script_code="Deva"))
    act_as(client, make_user("asha", "contributor"))
    for _ in range(5):
        shown = client.get(
            "/api/v1/prompts/next", params={"type": "read_sentence", "script": "Latn"}
        )
        assert shown.json()["id"] == latin["id"]


def test_media_is_served_through_short_lived_urls(
    client: TestClient, admin: TestUser, make_user: MakeUser
) -> None:
    image = _situation("img-one", prompt_type="image", text=None)
    prompt = _approved(client, image, image=FAKE_PNG, audio=FAKE_OGG)
    act_as(client, make_user("asha", "contributor"))
    shown = client.get(f"/api/v1/prompts/{prompt['id']}").json()
    assert "expires=" in shown["image_url"]
    assert "expires=" in shown["audio_url"]


def test_topics_are_balanced(db: Session, make_user: MakeUser) -> None:
    author = make_user("admin", "admin")
    for index in range(9):  # one crowded topic
        db.add(_row(f"crowded-{index}", ["farming"], author.id))
    db.add(_row("lonely-one", ["festival"], author.id))
    db.commit()
    picks = Counter(
        service.next_prompt(db, prompt_type="situation", script_code=None, exclude=[]).topic_tags[0]
        for _ in range(200)
    )
    # Each topic is picked about half the time, not 90% / 10%.
    assert picks["festival"] > 60


def _row(key: str, topics: list[str], author: uuid.UUID) -> Prompt:
    return Prompt(
        prompt_key=key,
        version=1,
        prompt_type="situation",
        text="Describe something.",
        source_and_licence="test",
        topic_tags=topics,
        status="approved",
        approved_by=author,
        created_by=author,
    )


def test_dev_prompts_are_seeded_once(
    db: Session, make_user: MakeUser, object_store: ObjectStore, settings: Settings
) -> None:
    author = make_user("dev-admin", "admin")
    assert service.ensure_dev_prompts(db, object_store, settings, author.id) == 12
    db.commit()
    assert service.ensure_dev_prompts(db, object_store, settings, author.id) == 0
    prompts = list(db.scalars(select(Prompt)))
    assert all(prompt.prompt_key.startswith("test-") for prompt in prompts)
    # Every reading script has a sentence, and every picture prompt a stored PNG.
    scripts = {p.script_code for p in prompts if p.prompt_type == "read_sentence"}
    assert scripts == {"Deva", "Latn", "Nagm"}
    images = [p.image_object_key for p in prompts if p.prompt_type == "image"]
    assert len(images) == 3
    for key in images:
        assert key is not None
        assert b"".join(object_store.open(Bucket.DERIVED, key)).startswith(b"\x89PNG")


def test_dev_pictures_are_valid_pngs() -> None:
    for name in SCENES:
        png = draw_png(name)
        assert sniff_image(png[:16]) == "png"
        width, height = struct.unpack(">II", png[16:24])
        assert (width, height) == (480, 320)
