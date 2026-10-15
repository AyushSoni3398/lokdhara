"""The export jobs: `dataset.export` builds an approved request's package
(docs/DATASET_VERSIONING.md §4, §5) and `cleanup.expire_exports` deletes packages once they
expire.

The package is rebuilt from what the release stored when it was frozen (the text files and the
manifest) and the audio copies its items point to. Every file is checked against the manifest
while it is written, so a changed or missing file fails the job instead of producing a
different package. Rebuilding the same release gives a byte-identical ZIP.
"""

import hashlib
import json
import tempfile
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.processing.models import Job
from app.modules.processing.queue import (
    JobContext,
    JobError,
    JobResult,
    handler,
    on_job_changed,
    utcnow,
)
from app.modules.releases import package
from app.modules.releases.exports import has_withdrawn_items
from app.modules.releases.freeze import stored_file_key
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem, ExportRequest
from app.modules.submissions.models import Rendition
from app.object_store import Bucket, ObjectNotFound, ObjectStore, get_object_store

# Per run; anything left over is picked up by the next hourly run.
EXPIRY_BATCH_SIZE = 500


def export_key(request: ExportRequest, release: DatasetRelease) -> str:
    return f"exports/{request.id}/{release.slug}-{release.version}.zip"


def _read(store: ObjectStore, bucket: Bucket, key: str) -> bytes:
    try:
        return b"".join(store.open(bucket, key))
    except ObjectNotFound:
        raise JobError("package_file_missing", retryable=False) from None


def _checked(store: ObjectStore, bucket: Bucket, key: str, sha256: str) -> package.Chunks:
    """Reads a file for the ZIP and fails if it is not the file the manifest names."""

    def chunks() -> Iterator[bytes]:
        digest = hashlib.sha256()
        try:
            for chunk in store.open(bucket, key):
                digest.update(chunk)
                yield chunk
        except ObjectNotFound:
            raise JobError("package_file_missing", retryable=False) from None
        if digest.hexdigest() != sha256:
            raise JobError("package_file_changed", retryable=False)

    return chunks


def _audio_keys(db: Session, release: DatasetRelease) -> dict[str, str]:
    rows = db.execute(
        select(DatasetReleaseItem.submission_id, Rendition.object_key)
        .join(Rendition, Rendition.id == DatasetReleaseItem.rendition_id)
        .where(DatasetReleaseItem.release_id == release.id)
    ).all()
    return {package.audio_path(str(submission_id)): key for submission_id, key in rows}


def _files(
    db: Session, store: ObjectStore, release: DatasetRelease
) -> list[tuple[str, package.Chunks]]:
    manifest_bytes = _read(store, Bucket.EXPORTS, stored_file_key(release.id, "manifest.json"))
    if hashlib.sha256(manifest_bytes).hexdigest() != release.manifest_sha256:
        raise JobError("package_file_changed", "manifest.json", retryable=False)
    listed: list[dict[str, Any]] = json.loads(manifest_bytes)["files"]
    audio = _audio_keys(db, release)
    files: list[tuple[str, package.Chunks]] = []
    for file in listed:
        path = file["path"]
        if path.startswith("audio/"):
            if path not in audio:
                raise JobError("package_file_missing", retryable=False)
            files.append((path, _checked(store, Bucket.DERIVED, audio[path], file["sha256"])))
        else:
            key = stored_file_key(release.id, path)
            files.append((path, _checked(store, Bucket.EXPORTS, key, file["sha256"])))
    entries = [package.FileEntry(f["path"], f["sha256"], f["bytes"]) for f in listed]
    entries.append(package.entry("manifest.json", manifest_bytes))
    files.append(("manifest.json", lambda: iter((manifest_bytes,))))
    sums = package.checksums(entries)
    files.append(("checksums.sha256", lambda: iter((sums,))))
    return files


def _locked(db: Session, request_id: Any) -> ExportRequest | None:
    return db.scalar(
        select(ExportRequest)
        .where(ExportRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@handler("dataset.export")
def build_export(context: JobContext) -> JobResult:
    settings, store, db = get_settings(), get_object_store(), context.db
    request = _locked(db, context.target_id)
    if request is None or request.status not in ("approved", "building"):
        return JobResult(output_summary={"skipped": request.status if request else "missing"})
    release = db.get_one(DatasetRelease, request.release_id)
    if release.status != "frozen" or has_withdrawn_items(db, release.id):
        raise JobError("release_unavailable", retryable=False)
    # Shown while the package is built; a retraction meanwhile closes the request.
    request.status = "building"
    db.commit()

    key = export_key(request, release)
    with tempfile.TemporaryFile() as target:
        package.write_zip(target, f"{release.slug}-{release.version}", _files(db, store, release))
        target.seek(0)
        stored = store.put(Bucket.EXPORTS, key, target, content_type="application/zip")

    request = _locked(db, context.target_id)
    if request is None or request.status != "building":
        store.delete(Bucket.EXPORTS, key)
        return JobResult(output_summary={"skipped": request.status if request else "missing"})
    now = utcnow()
    request.status = "ready"
    request.object_key = key
    request.sha256 = stored.sha256
    request.size_bytes = stored.size_bytes
    request.ready_at = now
    request.expires_at = now + timedelta(days=settings.export_retention_days)
    return JobResult(
        output_summary={"bytes": stored.size_bytes, "sha256": stored.sha256},
        tool_versions={"export_format_version": package.EXPORT_FORMAT_VERSION},
        input_sha256=release.manifest_sha256,
    )


@handler("cleanup.expire_exports")
def expire_exports(context: JobContext) -> JobResult:
    """Deletes packages past their `expires_at`. The release, its manifest and the request
    stay, so the same package can be asked for and rebuilt later (§5)."""
    store, db = get_object_store(), context.db
    due = db.scalars(
        select(ExportRequest)
        .where(ExportRequest.status == "ready", ExportRequest.expires_at <= utcnow())
        .order_by(ExportRequest.expires_at)
        .limit(EXPIRY_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()
    for request in due:
        store.delete(Bucket.EXPORTS, request.object_key or "")
        request.status = "expired"
    return JobResult(output_summary={"expired": len(due)})


@on_job_changed
def follow_export_job(db: Session, job: Job) -> None:
    """A build that failed for good fails its request; an admin retrying it re-opens it."""
    if job.job_type != "dataset.export" or job.target_id is None:
        return
    request = _locked(db, job.target_id)
    if request is None:
        return
    if job.status == "failed" and request.status in ("approved", "building"):
        request.status = "failed"
    elif job.status == "queued" and request.status == "failed":
        request.status = "approved"
