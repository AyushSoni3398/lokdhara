"""Consent capture (docs/CONSENT_AND_DATA_GOVERNANCE.md §3, docs/USER_FLOWS.md F2)."""

import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.consents import service
from app.modules.consents.models import ConsentRecord
from app.modules.speakers.models import Speaker
from app.object_store import Bucket, ObjectStore
from tests.conftest import MakeUser, act_as, requires_postgres

pytestmark = requires_postgres

# The first bytes of a WebM file; enough for the format check. Never real audio.
FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


@pytest.fixture
def form_id(db: Session) -> str:
    service.ensure_dev_forms(db)
    db.commit()
    form = service.current_form(db, Settings(_env_file=None, env="test"), "hi")
    return str(form.id)


@pytest.fixture
def speaker_id(client: TestClient, make_user: MakeUser) -> str:
    act_as(client, make_user("asha", "contributor"))
    return str(client.post("/api/v1/speakers", json={"for_self": True}).json()["id"])


def _consent(
    client: TestClient,
    speaker_id: str,
    form_id: str,
    evidence: bytes | None = None,
    **fields: Any,
) -> Any:
    answers = {
        "consent_form_id": form_id,
        "method": "in_app",
        "allow_store_and_review": True,
        **fields,
    }
    files = {"evidence": ("consent.webm", evidence, "audio/webm")} if evidence else None
    return client.post(
        f"/api/v1/speakers/{speaker_id}/consents",
        data={"consent": json.dumps(answers)},
        files=files,
    )


def _evidence_files(tmp_path: Path) -> list[Path]:
    # The local store keeps each bucket in its own folder (see the object_store fixture).
    return [p for p in (tmp_path / "objects" / "test-consent-evidence").rglob("*") if p.is_file()]


# ------------------------------------------------------------------ forms


def test_current_form_is_the_test_form_with_its_hash(
    client: TestClient, make_user: MakeUser, form_id: str
) -> None:
    act_as(client, make_user("asha", "contributor"))
    response = client.get("/api/v1/consent-forms/current", params={"language": "hi"})
    assert response.status_code == 200
    form = response.json()
    assert form["id"] == form_id
    assert form["is_test_form"] is True
    assert form["text_sha256"] == hashlib.sha256(form["body_markdown"].encode()).hexdigest()
    missing = client.get("/api/v1/consent-forms/current", params={"language": "unr-Deva"})
    assert missing.json()["code"] == "consent_form_not_found"


def test_production_never_offers_test_forms(db: Session, form_id: str) -> None:
    production = Settings(
        _env_file=None,
        env="production",
        secret_key="x" * 40,
        identity_encryption_key=base64.b64encode(bytes(32)).decode(),
    )
    with pytest.raises(ApiError, match="consent_form_not_found"):
        service.current_form(db, production, "hi")


# ------------------------------------------------------------------ recording consent


def test_in_app_consent_defaults_every_permission_to_no(
    client: TestClient, speaker_id: str, form_id: str, db: Session
) -> None:
    response = _consent(client, speaker_id, form_id)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "active"
    assert record["allow_store_and_review"] is True
    for permission in ("allow_research", "allow_public_access", "allow_ai_training"):
        assert record[permission] is False
    assert record["allow_commercial_use"] is False
    assert record["demographics_consented"] is False
    assert record["attribution_preference"] == "pseudonymous"
    assert client.get(f"/api/v1/speakers/{speaker_id}").json()["has_active_consent"] is True

    event = db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at.desc())).first()
    assert event is not None and event.action == "consent.record"
    assert event.details["permissions"]["allow_research"] is False


def test_taking_part_requires_permission_to_store(
    client: TestClient, speaker_id: str, form_id: str
) -> None:
    response = _consent(client, speaker_id, form_id, allow_store_and_review=False)
    assert response.status_code == 422
    assert response.json()["code"] == "store_consent_required"


def test_a_change_supersedes_the_active_record(
    client: TestClient, speaker_id: str, form_id: str
) -> None:
    first = _consent(client, speaker_id, form_id, allow_research=True).json()
    second = _consent(client, speaker_id, form_id, allow_research=False).json()
    assert second["supersedes_id"] == first["id"]
    history = client.get(f"/api/v1/speakers/{speaker_id}/consents").json()["items"]
    assert [(r["id"], r["status"]) for r in history] == [
        (second["id"], "active"),
        (first["id"], "superseded"),
    ]


def test_withdrawing_the_demographics_answer_erases_demographics(
    client: TestClient, speaker_id: str, form_id: str, db: Session
) -> None:
    _consent(client, speaker_id, form_id, demographics_consented=True)
    path = f"/api/v1/speakers/{speaker_id}"
    assert client.patch(path, json={"age_band": "45-59", "region_coarse": "Khunti"}).is_success
    _consent(client, speaker_id, form_id, demographics_consented=False)
    speaker = client.get(path).json()
    assert speaker["demographics_consented"] is False
    assert (speaker["age_band"], speaker["region_coarse"]) == (None, None)


def test_guardian_consent_is_accepted_unless_minors_are_turned_off(
    client: TestClient, speaker_id: str, form_id: str, settings: Settings
) -> None:
    settings.allow_minors = False
    response = _consent(
        client, speaker_id, form_id, guardian_involved=True, guardian_relationship="mother"
    )
    assert response.json()["code"] == "minors_not_enabled"
    settings.allow_minors = True
    response = _consent(
        client, speaker_id, form_id, guardian_involved=True, guardian_relationship="mother"
    )
    assert response.status_code == 201, response.text


def test_paper_consent_needs_its_reference(
    client: TestClient, speaker_id: str, form_id: str, db: Session
) -> None:
    assert _consent(client, speaker_id, form_id, method="paper_reference").status_code == 422
    response = _consent(
        client, speaker_id, form_id, method="paper_reference", paper_reference="KH-2026/014"
    )
    assert response.status_code == 201, response.text
    assert "paper_reference" not in response.json()
    stored = db.get(ConsentRecord, uuid.UUID(response.json()["id"]))
    assert stored is not None and stored.paper_reference == "KH-2026/014"


# ------------------------------------------------------------------ oral consent evidence


def test_oral_consent_needs_an_audio_recording(
    client: TestClient, speaker_id: str, form_id: str
) -> None:
    assert (
        _consent(client, speaker_id, form_id, method="oral_recorded").json()["code"]
        == "evidence_required"
    )
    not_audio = _consent(
        client, speaker_id, form_id, method="oral_recorded", evidence=b"%PDF-1.7 not audio"
    )
    assert not_audio.json()["code"] == "evidence_not_audio"
    in_app_with_file = _consent(client, speaker_id, form_id, evidence=FAKE_WEBM)
    assert in_app_with_file.json()["code"] == "evidence_not_expected"


def test_oral_consent_evidence_goes_to_the_restricted_bucket(
    client: TestClient, speaker_id: str, form_id: str, db: Session, object_store: ObjectStore
) -> None:
    response = _consent(client, speaker_id, form_id, method="oral_recorded", evidence=FAKE_WEBM)
    assert response.status_code == 201, response.text
    assert response.json()["has_evidence"] is True
    record = db.get(ConsentRecord, uuid.UUID(response.json()["id"]))
    assert record is not None and record.evidence_object_key is not None
    assert record.evidence_object_key.startswith(f"consent/{speaker_id}/")
    assert record.evidence_object_key.endswith(".webm")
    assert object_store.head(Bucket.CONSENT_EVIDENCE, record.evidence_object_key) == len(FAKE_WEBM)


def test_oversized_evidence_is_refused_and_not_kept(
    client: TestClient,
    speaker_id: str,
    form_id: str,
    settings: Settings,
    tmp_path: Path,
) -> None:
    settings.consent_evidence_max_bytes = 32
    response = _consent(client, speaker_id, form_id, method="oral_recorded", evidence=FAKE_WEBM)
    assert response.status_code == 413
    assert _evidence_files(tmp_path) == []


def test_evidence_is_removed_when_the_record_cannot_be_saved(
    client: TestClient,
    speaker_id: str,
    form_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError):
        _consent(client, speaker_id, form_id, method="oral_recorded", evidence=FAKE_WEBM)
    assert _evidence_files(tmp_path) == []


# ------------------------------------------------------------------ who may capture consent


def test_only_people_acting_for_the_speaker_capture_consent(
    client: TestClient, make_user: MakeUser, form_id: str, db: Session
) -> None:
    act_as(client, make_user("ravi", "facilitator"))
    speaker = client.post("/api/v1/speakers", json={"for_self": False}).json()
    assert _consent(client, speaker["id"], form_id).status_code == 201

    act_as(client, make_user("sita", "facilitator"))
    assert _consent(client, speaker["id"], form_id).status_code == 404

    act_as(client, make_user("admin", "admin"))
    assert _consent(client, speaker["id"], form_id).status_code == 201


def test_withdrawn_speakers_cannot_be_given_new_consent(
    client: TestClient, speaker_id: str, form_id: str, db: Session
) -> None:
    speaker = db.get(Speaker, uuid.UUID(speaker_id))
    assert speaker is not None
    speaker.status = "withdrawn"
    db.commit()
    assert _consent(client, speaker_id, form_id).json()["code"] == "speaker_withdrawn"
