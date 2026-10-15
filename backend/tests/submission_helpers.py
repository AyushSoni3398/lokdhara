"""Shared steps for the submission and upload tests. All data is synthetic."""

import json
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.consents import service as consents
from app.modules.processing import (
    handlers,  # noqa: F401 - registers text.derive
    queue,
)

SUBMISSIONS = "/api/v1/submissions"
# The first bytes of a WebM file; enough for the format check. Never real audio.
FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def own_speaker(client: TestClient) -> str:
    response = client.post("/api/v1/speakers", json={"for_self": True})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def give_consent(client: TestClient, db: Session, speaker_id: str, **uses: bool) -> None:
    """Records consent for the signed-in user's speaker; `uses` are extra yes/no answers such
    as allow_research=True."""
    consents.ensure_dev_forms(db)
    db.commit()
    form = consents.current_form(db, Settings(_env_file=None, env="test"), "hi")
    answers = {
        "consent_form_id": str(form.id),
        "method": "in_app",
        "allow_store_and_review": True,
        **uses,
    }
    response = client.post(
        f"/api/v1/speakers/{speaker_id}/consents", data={"consent": json.dumps(answers)}
    )
    assert response.status_code == 201, response.text


def draft_body(speaker_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "client_submission_id": str(uuid.uuid4()),
        "speaker_id": speaker_id,
        "kind": "audio",
        "content_type": "story",
        "collection_method": "self_recorded",
        "recording_mode": "free",
        **fields,
    }


def create_draft(client: TestClient, speaker_id: str, **fields: Any) -> dict[str, Any]:
    response = client.post(SUBMISSIONS, json=draft_body(speaker_id, **fields))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def upload(
    client: TestClient,
    submission_id: str,
    content: bytes = FAKE_WEBM,
    key: str | None = None,
    filename: str = "recording.webm",
) -> Any:
    return client.post(
        f"{SUBMISSIONS}/{submission_id}/recordings",
        files={"file": (filename, content, "audio/webm")},
        data={"source": "browser_recorder"},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


def accepted_text_item(
    client: TestClient, engine: Engine, speaker_id: str, content: str, **fields: Any
) -> str:
    """Sends a text-only item and runs the checks until it is accepted. Returns its ID."""
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
