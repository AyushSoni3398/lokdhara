"""Dataset releases (docs/API_SPECIFICATION.md §8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.db import DbSession
from app.modules.identity.deps import AdminUser, Context, SettingsDep, require_roles
from app.modules.identity.service import AuthenticatedUser
from app.modules.releases import freeze, service
from app.modules.releases.models import DatasetRelease
from app.modules.releases.schemas import (
    CheckListOut,
    CheckOut,
    FreezeRequest,
    PreviewOut,
    ReleaseCreateRequest,
    ReleaseListOut,
    ReleaseOut,
    ReleaseUpdateRequest,
    SampleItem,
    SelectionCriteria,
)
from app.object_store import ObjectStore, get_object_store

router = APIRouter(tags=["releases"])
Store = Annotated[ObjectStore, Depends(get_object_store)]

# Project members who work with the data; contributors never see releases.
DataUser = Annotated[AuthenticatedUser, Depends(require_roles("researcher", "admin"))]


def release_out(release: DatasetRelease) -> ReleaseOut:
    computed = {"selection_criteria"}
    fields = {f: getattr(release, f) for f in ReleaseOut.model_fields if f not in computed}
    return ReleaseOut(
        **fields,
        selection_criteria=SelectionCriteria.model_validate(release.selection_criteria),
    )


@router.post("/datasets", status_code=status.HTTP_201_CREATED)
def create_release(
    body: ReleaseCreateRequest, user: DataUser, db: DbSession, context: Context
) -> ReleaseOut:
    return release_out(service.create_draft(db, user=user, body=body, context=context))


@router.get("/datasets")
def list_releases(_user: DataUser, db: DbSession) -> ReleaseListOut:
    return ReleaseListOut(items=[release_out(r) for r in service.list_releases(db)])


@router.get("/datasets/{release_id}")
def get_release(release_id: uuid.UUID, _user: DataUser, db: DbSession) -> ReleaseOut:
    return release_out(service.get_release(db, release_id))


@router.patch("/datasets/{release_id}")
def update_release(
    release_id: uuid.UUID, body: ReleaseUpdateRequest, user: DataUser, db: DbSession
) -> ReleaseOut:
    return release_out(service.update_draft(db, user=user, release_id=release_id, body=body))


@router.get("/datasets/{release_id}/preview")
def preview_release(release_id: uuid.UUID, _user: DataUser, db: DbSession) -> PreviewOut:
    result = service.preview(db, service.get_release(db, release_id))
    return PreviewOut(
        item_count=result.item_count,
        total_duration_ms=result.total_duration_ms,
        left_out_count=result.left_out_count,
        by_content_type=result.by_content_type,
        by_dialect_label=result.by_dialect_label,
        by_kind=result.by_kind,
        sample=[
            SampleItem(
                id=submission.id,
                title=submission.title,
                content_type=submission.content_type,
                duration_ms=duration,
            )
            for submission, duration in result.sample
        ],
    )


@router.post("/datasets/{release_id}/checks")
def check_release(
    release_id: uuid.UUID, _user: DataUser, db: DbSession, store: Store, settings: SettingsDep
) -> CheckListOut:
    """Runs the pre-freeze checks D1 to D9 without freezing."""
    run = freeze.run_checks(db, store, settings, service.get_release(db, release_id))
    return CheckListOut(
        passed=run.passed,
        checks=[
            CheckOut(code=c.code, passed=c.passed, blocking=c.blocking, message=c.message)
            for c in run.checks
        ],
    )


@router.post("/datasets/{release_id}/freeze")
def freeze_release(
    release_id: uuid.UUID,
    body: FreezeRequest,
    admin: AdminUser,
    db: DbSession,
    store: Store,
    settings: SettingsDep,
    context: Context,
) -> ReleaseOut:
    release = freeze.freeze(
        db,
        store,
        settings,
        admin=admin,
        release_id=release_id,
        version=body.version,
        context=context,
    )
    return release_out(release)
