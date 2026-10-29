"""Building export packages for frozen releases (docs/DATASET_VERSIONING.md §4, §5).

Synthetic data only: one text item and one recording of a tone made by FFmpeg.
"""

import hashlib
import io
import json
import shutil
import subprocess
import uuid
import zipfile
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.processing import queue
from app.modules.processing.models import Job
from app.modules.releases import export_job, freeze, package
from app.modules.releases.models import ExportRequest
from app.modules.submissions import processing
from app.modules.submissions.models import Rendition
from app.object_store import Bucket, ObjectStore
from tests.audio_fixtures import make_audio, requires_ffmpeg
from tests.conftest import MakeUser, TestUser, act_as, requires_postgres
from tests.submission_helpers import (
    SUBMISSIONS,
    accepted_text_item,
    create_draft,
    give_consent,
    own_speaker,
    upload,
)

pytestmark = [requires_postgres, requires_ffmpeg]

DATASETS = "/api/v1/datasets"
PURPOSE = {"purpose_statement": "Train a student's keyword-spotting baseline."}


@pytest.fixture(autouse=True)
def worker_uses_test_storage(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, object_store: ObjectStore
) -> Iterator[None]:
    for module in (processing, export_job):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "get_object_store", lambda: object_store)
    yield


def run_jobs(engine: Engine) -> None:
    while queue.process_one(engine, "test-worker", 60):
        pass


@pytest.fixture
def researcher(make_user: MakeUser) -> TestUser:
    return make_user("kiran", "researcher")


@pytest.fixture
def admin(make_user: MakeUser) -> TestUser:
    return make_user("meera", "admin")


@pytest.fixture
def release(
    client: TestClient,
    engine: Engine,
    db: Session,
    make_user: MakeUser,
    admin: TestUser,
    tmp_path: Path,
) -> dict[str, Any]:
    """A frozen release with a recording and a text item."""
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    context = {"setting": "outdoor", "equipment": "phone_builtin_mic", "notes": "at Somra's"}
    draft = create_draft(client, speaker, collection_context=context)
    assert upload(client, draft["id"], make_audio(tmp_path / "a", seconds=2)).status_code == 202
    assert client.post(f"{SUBMISSIONS}/{draft['id']}/submit").status_code == 200
    accepted_text_item(client, engine, speaker, "नदी के किनारे")
    assert client.get(f"{SUBMISSIONS}/{draft['id']}").json()["status"] == "accepted"

    act_as(client, admin)
    made = client.post(DATASETS, json={"slug": "mundari-pilot", "purpose": "internal_research"})
    frozen = client.post(f"{DATASETS}/{made.json()['id']}/freeze", json={"version": "0.1.0"})
    assert frozen.status_code == 200, frozen.text
    result: dict[str, Any] = frozen.json()
    return result


def _approved(
    client: TestClient, release: dict[str, Any], researcher: TestUser, admin: TestUser
) -> str:
    act_as(client, researcher)
    request = client.post(f"{DATASETS}/{release['id']}/exports", json=PURPOSE).json()
    act_as(client, admin)
    approve = client.post(f"/api/v1/admin/exports/{request['id']}/approve", json={})
    assert approve.status_code == 200, approve.text
    return str(request["id"])


def _package(object_store: ObjectStore, db: Session, export_id: str) -> bytes:
    request = db.get_one(ExportRequest, uuid.UUID(export_id), populate_existing=True)
    return b"".join(object_store.open(Bucket.EXPORTS, request.object_key or ""))


def test_approved_exports_are_built_from_the_frozen_files(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
) -> None:
    export_id = _approved(client, release, researcher, admin)
    run_jobs(engine)

    act_as(client, researcher)
    ready = client.get(f"/api/v1/exports/{export_id}").json()
    assert ready["status"] == "ready"
    assert ready["expires_at"] is not None
    content = _package(object_store, db, export_id)
    assert hashlib.sha256(content).hexdigest() == ready["sha256"]
    assert len(content) == ready["size_bytes"]

    archive = zipfile.ZipFile(io.BytesIO(content))
    names = archive.namelist()
    assert names == sorted(names)
    assert all(name.startswith("mundari-pilot-0.1.0/") for name in names)
    files = {name.split("/", 1)[1]: archive.read(name) for name in names}
    assert {"README.md", "LICENSE.txt", "items.jsonl", "manifest.json"} <= files.keys()
    assert sum(1 for name in files if name.startswith("audio/")) == 1
    # checksums.sha256 matches every other file, as `sha256sum -c` would check it.
    for line in files["checksums.sha256"].decode().splitlines():
        digest, path = line.split("  ")
        assert hashlib.sha256(files[path]).hexdigest() == digest
    assert hashlib.sha256(files["manifest.json"]).hexdigest() == release["manifest_sha256"]

    # A second package of the same release is byte-identical.
    second = _approved(client, release, researcher, admin)
    run_jobs(engine)
    assert _package(object_store, db, second) == content


def _files(content: bytes) -> dict[str, bytes]:
    archive = zipfile.ZipFile(io.BytesIO(content))
    return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


def test_audio_files_carry_their_items_tags(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
    tmp_path: Path,
) -> None:
    export_id = _approved(client, release, researcher, admin)
    run_jobs(engine)
    files = _files(_package(object_store, db, export_id))

    records = [json.loads(line) for line in files["items.jsonl"].decode().splitlines()]
    recording = next(r for r in records if r["audio"])
    flac = files[recording["audio"]["path"]]
    # items.jsonl describes the file in the package, tags included.
    assert hashlib.sha256(flac).hexdigest() == recording["audio"]["sha256"]
    assert len(flac) == recording["audio"]["bytes"]
    assert recording["collection_context"] == {
        "setting": "outdoor",
        "equipment": "phone_builtin_mic",
    }
    assert recording["audio"]["original"]["source"] == "browser_recorder"
    assert recording["audio"]["original"]["codec"] == "opus"
    assert recording["audio"]["quality"]["peak_dbfs"] is not None

    path = tmp_path / "item.flac"
    path.write_bytes(flac)
    probed = subprocess.run(  # noqa: S603 - test helper, fixed program
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-of", "json", "-show_format", path],
        check=True,
        capture_output=True,
        timeout=60,
    )
    tags = {k.upper(): v for k, v in json.loads(probed.stdout)["format"]["tags"].items()}
    assert tags["LOKDHARA_ITEM_ID"] == recording["item_id"]
    assert tags["SPEAKER_CODE"] == recording["speaker_code"]
    assert tags["ALBUM"] == "mundari-pilot 0.1.0"
    assert tags["CONSENT"] == "research"
    assert "Internal research use only" in tags["LICENSE"]
    assert "Somra" not in json.dumps(tags) + files["items.jsonl"].decode()

    sheet = files["metadata.csv"].decode("utf-8-sig").splitlines()
    assert len(sheet) == 3 and sheet[0].startswith("item_id,audio_path,")


def test_releases_frozen_before_tags_are_rebuilt_without_them(
    client: TestClient,
    engine: Engine,
    db: Session,
    make_user: MakeUser,
    object_store: ObjectStore,
    researcher: TestUser,
    admin: TestUser,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A format 1 release: its manifest lists the audio copies as stored, untagged."""
    act_as(client, make_user("asha", "contributor"))
    speaker = own_speaker(client)
    give_consent(client, db, speaker, allow_research=True)
    draft = create_draft(client, speaker)
    assert upload(client, draft["id"], make_audio(tmp_path / "a", seconds=2)).status_code == 202
    assert client.post(f"{SUBMISSIONS}/{draft['id']}/submit").status_code == 200
    run_jobs(engine)

    act_as(client, admin)
    made = client.post(DATASETS, json={"slug": "old-pilot", "purpose": "internal_research"})
    with monkeypatch.context() as patch:
        patch.setattr(package, "EXPORT_FORMAT_VERSION", "1")
        patch.setattr(
            freeze,
            "_tagged_entry",
            lambda _store, path, rendition, _comments: package.FileEntry(
                path, rendition.sha256, rendition.size_bytes
            ),
        )
        frozen = client.post(f"{DATASETS}/{made.json()['id']}/freeze", json={"version": "0.1.0"})
    assert frozen.status_code == 200, frozen.text

    export_id = _approved(client, frozen.json(), researcher, admin)
    run_jobs(engine)
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "ready"
    files = _files(_package(object_store, db, export_id))
    flac = next(content for name, content in files.items() if name.startswith("audio/"))
    rendition = db.scalar(select(Rendition).where(Rendition.kind == "analysis_flac_16k_mono"))
    assert rendition is not None
    assert hashlib.sha256(flac).hexdigest() == rendition.sha256


def test_a_changed_file_fails_the_build_and_a_retry_reopens_it(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
) -> None:
    key = freeze.stored_file_key(uuid.UUID(release["id"]), "items.jsonl")
    original = b"".join(object_store.open(Bucket.EXPORTS, key))
    object_store.put(Bucket.EXPORTS, key, io.BytesIO(original + b"{}\n"))
    export_id = _approved(client, release, researcher, admin)
    run_jobs(engine)

    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "failed"
    job = db.scalar(select(Job).where(Job.job_type == "dataset.export"))
    assert job is not None
    assert (job.status, job.last_error_code) == ("failed", "package_file_changed")

    object_store.put(Bucket.EXPORTS, key, io.BytesIO(original))
    assert client.post(f"/api/v1/admin/jobs/{job.id}/retry").status_code == 200
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "approved"
    run_jobs(engine)
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "ready"


def test_a_package_of_a_retracted_release_is_deleted(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
) -> None:
    export_id = _approved(client, release, researcher, admin)
    run_jobs(engine)
    key = db.get_one(ExportRequest, uuid.UUID(export_id)).object_key or ""
    assert object_store.head(Bucket.EXPORTS, key) is not None
    note = {"note": "A speaker raised a consent concern."}
    assert client.post(f"{DATASETS}/{release['id']}/retract", json=note).status_code == 200
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "expired"
    assert object_store.head(Bucket.EXPORTS, key) is None


def test_only_the_requester_downloads_and_every_download_is_recorded(
    client: TestClient,
    engine: Engine,
    db: Session,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
) -> None:
    export_id = _approved(client, release, researcher, admin)
    download = f"/api/v1/exports/{export_id}/download"
    act_as(client, researcher)
    assert client.post(download).json()["code"] == "export_not_ready"
    run_jobs(engine)

    first = client.post(download)
    assert first.status_code == 200, first.text
    link = first.json()
    assert link["file_name"] == "mundari-pilot-0.1.0.zip"
    fetched = client.get(link["download_url"])
    assert hashlib.sha256(fetched.content).hexdigest() == link["sha256"]
    client.post(download)
    assert client.get(f"/api/v1/exports/{export_id}").json()["download_count"] == 2
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "export.download")).all()
    assert len(events) == 2

    act_as(client, admin)
    assert client.post(download).json()["code"] == "forbidden"


def test_packages_are_deleted_when_they_expire(
    client: TestClient,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    release: dict[str, Any],
    researcher: TestUser,
    admin: TestUser,
) -> None:
    export_id = _approved(client, release, researcher, admin)
    run_jobs(engine)
    key = db.get_one(ExportRequest, uuid.UUID(export_id)).object_key or ""
    queue.enqueue(db, "cleanup.expire_exports")
    db.commit()
    run_jobs(engine)
    assert object_store.head(Bucket.EXPORTS, key) is not None  # not due yet

    db.execute(
        update(ExportRequest)
        .where(ExportRequest.id == uuid.UUID(export_id))
        .values(expires_at=queue.utcnow() - timedelta(minutes=1))
    )
    queue.enqueue(db, "cleanup.expire_exports")
    db.commit()
    act_as(client, researcher)
    download = f"/api/v1/exports/{export_id}/download"
    assert client.post(download).json()["code"] == "export_expired"
    run_jobs(engine)
    assert object_store.head(Bucket.EXPORTS, key) is None
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "expired"
    assert client.post(download).json()["code"] == "export_expired"
