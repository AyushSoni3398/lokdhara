from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.db import DbSession
from app.modules.identity.deps import AdminUser, Context
from app.modules.ops import archive, status
from app.modules.ops.schemas import StatusOut
from app.modules.processing.queue import utcnow
from app.modules.speakers.router import Cipher
from app.object_store import ObjectStore, get_object_store
from app.object_store.base import attachment_header

Store = Annotated[ObjectStore, Depends(get_object_store)]
Reason = Annotated[str, Query(min_length=archive.MIN_REASON_LENGTH, max_length=500)]

router = APIRouter(tags=["ops"])


@router.get("/admin/status")
def get_status(_admin: AdminUser, db: DbSession) -> StatusOut:
    """Whether backups, jobs and the disk are healthy, and what is waiting for an admin."""
    current = status.collect(db, utcnow(), status.disk_used_share())
    return StatusOut.model_validate(
        asdict(current) | {"backups": [asdict(b) for b in current.backups.values()]}
    )


@router.get("/admin/archive.zip")
def download_archive(
    admin: AdminUser, reason: Reason, db: DbSession, cipher: Cipher, store: Store, context: Context
) -> StreamingResponse:
    """Everything the app holds, unfiltered, as one zip (ADR-027). Plain GET, so an ordinary
    link starts the download; the reason is recorded in the audit log first."""
    made_at = utcnow()
    contents = archive.collect(
        db, cipher, admin=admin, reason=reason, made_at=made_at, context=context
    )
    name = f"lokdhara-archive-{made_at:%Y-%m-%dT%H%M%SZ}.zip"
    return StreamingResponse(
        archive.zip_chunks(store, contents),
        media_type="application/zip",
        headers={"Content-Disposition": attachment_header(name), "Cache-Control": "no-store"},
    )
