"""Dataset releases (docs/API_SPECIFICATION.md §8)."""

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, status

from app.db import DbSession
from app.modules.identity.deps import AdminUser, Context, SettingsDep, require_roles
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.releases import exports, freeze, service
from app.modules.releases.models import DatasetRelease, ExportRequest
from app.modules.releases.schemas import (
    ApproveRequest,
    CheckListOut,
    CheckOut,
    ExportCreateRequest,
    ExportListOut,
    ExportOut,
    ExportStatus,
    FreezeRequest,
    PreviewOut,
    RejectRequest,
    ReleaseCreateRequest,
    ReleaseListOut,
    ReleaseOut,
    ReleaseUpdateRequest,
    RetractRequest,
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


@router.post("/datasets/{release_id}/retract")
def retract_release(
    release_id: uuid.UUID,
    body: RetractRequest,
    admin: AdminUser,
    db: DbSession,
    store: Store,
    context: Context,
) -> ReleaseOut:
    release = exports.retract(
        db, store, admin=admin, release_id=release_id, note=body.note, context=context
    )
    return release_out(release)


# ------------------------------------------------------------------ exports


def export_out(db: DbSession, user: AuthenticatedUser, request: ExportRequest) -> ExportOut:
    release = db.get_one(DatasetRelease, request.release_id)
    requester = db.get_one(User, request.requested_by)
    return ExportOut(
        id=request.id,
        release_id=release.id,
        release_slug=release.slug,
        release_version=release.version,
        requested_by_name=requester.display_name,
        mine=request.requested_by == user.id,
        purpose_statement=request.purpose_statement,
        status=cast(ExportStatus, request.status),
        decision_note=request.decision_note,
        decided_at=request.decided_at,
        created_at=request.created_at,
        ready_at=request.ready_at,
        expires_at=request.expires_at,
        sha256=request.sha256,
        size_bytes=request.size_bytes,
        download_count=len(request.downloaded_at),
    )


@router.post("/datasets/{release_id}/exports", status_code=status.HTTP_201_CREATED)
def request_export(
    release_id: uuid.UUID,
    body: ExportCreateRequest,
    user: DataUser,
    db: DbSession,
    context: Context,
) -> ExportOut:
    request = exports.request_export(
        db,
        user=user,
        release_id=release_id,
        purpose_statement=body.purpose_statement,
        context=context,
    )
    return export_out(db, user, request)


@router.get("/exports")
def list_exports(user: DataUser, db: DbSession) -> ExportListOut:
    """Admins see every request; researchers see their own."""
    return ExportListOut(items=[export_out(db, user, r) for r in exports.visible_exports(db, user)])


@router.get("/exports/{export_id}")
def get_export(export_id: uuid.UUID, user: DataUser, db: DbSession) -> ExportOut:
    return export_out(db, user, exports.get_export(db, user, export_id))


@router.post("/admin/exports/{export_id}/approve")
def approve_export(
    export_id: uuid.UUID, body: ApproveRequest, admin: AdminUser, db: DbSession, context: Context
) -> ExportOut:
    request = exports.approve(db, admin=admin, export_id=export_id, note=body.note, context=context)
    return export_out(db, admin, request)


@router.post("/admin/exports/{export_id}/reject")
def reject_export(
    export_id: uuid.UUID, body: RejectRequest, admin: AdminUser, db: DbSession, context: Context
) -> ExportOut:
    request = exports.reject(db, admin=admin, export_id=export_id, note=body.note, context=context)
    return export_out(db, admin, request)
