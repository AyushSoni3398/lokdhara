from dataclasses import asdict

from fastapi import APIRouter

from app.db import DbSession
from app.modules.identity.deps import AdminUser
from app.modules.ops import status
from app.modules.ops.schemas import StatusOut
from app.modules.processing.queue import utcnow

router = APIRouter(tags=["ops"])


@router.get("/admin/status")
def get_status(_admin: AdminUser, db: DbSession) -> StatusOut:
    """Whether backups, jobs and the disk are healthy, and what is waiting for an admin."""
    current = status.collect(db, utcnow(), status.disk_used_share())
    return StatusOut.model_validate(
        asdict(current) | {"backups": [asdict(b) for b in current.backups.values()]}
    )
