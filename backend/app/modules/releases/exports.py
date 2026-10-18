"""Export requests for frozen releases (docs/DATASET_VERSIONING.md, docs/API_SPECIFICATION.md §8).

A researcher asks for a release's package and says what it is for; another admin approves or
rejects the request. Approval queues the `dataset.export` job, which builds the package in the
`exports` bucket. A package can be downloaded until it expires; every download is recorded.
Nothing is exported from a retracted release, or from one an item was withdrawn from after it
was frozen.
"""

import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.processing import queue
from app.modules.releases import service
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem, ExportRequest
from app.object_store import Bucket, ObjectStore

# Requests that still lead to a package; retraction closes them.
OPEN_STATUSES = ("requested", "approved", "building")


def not_found() -> ApiError:
    return ApiError(404, "export_not_found", "Export request not found.")


def has_withdrawn_items(db: Session, release_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    DatasetReleaseItem.release_id == release_id,
                    DatasetReleaseItem.withdrawn_after_release_at.is_not(None),
                )
            )
        )
    )


def exportable(db: Session, release: DatasetRelease) -> None:
    """Raises unless packages may be built from this release now."""
    if release.status == "draft":
        raise ApiError(409, "release_not_frozen", "Only a frozen release can be exported.")
    if release.status == "retracted":
        raise ApiError(409, "release_retracted", "This release was retracted.")
    if has_withdrawn_items(db, release.id):
        raise ApiError(
            409,
            "release_has_withdrawn_items",
            "An item of this release was withdrawn; export the next release instead.",
        )


def request_export(
    db: Session,
    *,
    user: AuthenticatedUser,
    release_id: uuid.UUID,
    purpose_statement: str,
    context: RequestContext,
) -> ExportRequest:
    release = service.get_release(db, release_id)
    exportable(db, release)
    request = ExportRequest(
        release_id=release.id, requested_by=user.id, purpose_statement=purpose_statement
    )
    db.add(request)
    db.flush()
    audit.record(
        db,
        action="export.request",
        context=context,
        actor_user_id=user.id,
        target_type="export_request",
        target_id=request.id,
        details={"release_id": str(release.id)},
    )
    db.commit()
    return request


def visible_exports(db: Session, user: AuthenticatedUser) -> list[ExportRequest]:
    """Admins see every request; researchers see their own."""
    query = select(ExportRequest).order_by(ExportRequest.created_at.desc())
    if not user.has_role("admin"):
        query = query.where(ExportRequest.requested_by == user.id)
    return list(db.scalars(query))


def get_export(
    db: Session, user: AuthenticatedUser, export_id: uuid.UUID, *, for_update: bool = False
) -> ExportRequest:
    query = select(ExportRequest).where(ExportRequest.id == export_id)
    request = db.scalar(query.with_for_update() if for_update else query)
    if request is None or not (request.requested_by == user.id or user.has_role("admin")):
        raise not_found()
    return request


def _to_decide(db: Session, admin: AuthenticatedUser, export_id: uuid.UUID) -> ExportRequest:
    request = get_export(db, admin, export_id, for_update=True)
    if request.status != "requested":
        raise ApiError(409, "export_decided", "This request has already been decided.")
    if request.requested_by == admin.id:
        raise ApiError(403, "own_request", "Another admin must decide on your own request.")
    return request


def _decide(
    db: Session,
    request: ExportRequest,
    admin: AuthenticatedUser,
    status: str,
    note: str | None,
    context: RequestContext,
) -> None:
    request.status = status
    request.decided_by = admin.id
    request.decided_at = utcnow()
    request.decision_note = note
    audit.record(
        db,
        action=f"export.{'approve' if status == 'approved' else 'reject'}",
        context=context,
        actor_user_id=admin.id,
        target_type="export_request",
        target_id=request.id,
        details={"release_id": str(request.release_id)},
    )


def approve(
    db: Session,
    *,
    admin: AuthenticatedUser,
    export_id: uuid.UUID,
    note: str | None,
    context: RequestContext,
) -> ExportRequest:
    request = _to_decide(db, admin, export_id)
    exportable(db, service.get_release(db, request.release_id, for_update=True))
    _decide(db, request, admin, "approved", note, context)
    queue.enqueue(
        db,
        "dataset.export",
        target_type="export_request",
        target_id=request.id,
        dedupe_key=f"dataset.export:{request.id}",
    )
    db.commit()
    return request


def reject(
    db: Session,
    *,
    admin: AuthenticatedUser,
    export_id: uuid.UUID,
    note: str,
    context: RequestContext,
) -> ExportRequest:
    request = _to_decide(db, admin, export_id)
    _decide(db, request, admin, "rejected", note, context)
    db.commit()
    return request


def retract(
    db: Session,
    store: ObjectStore,
    *,
    admin: AuthenticatedUser,
    release_id: uuid.UUID,
    note: str,
    context: RequestContext,
) -> DatasetRelease:
    """Marks a frozen release as no longer to be used (DATASET_VERSIONING §1). The release,
    its items and its manifest stay for audit; nothing can be exported from it again."""
    release = service.get_release(db, release_id, for_update=True)
    if release.status == "draft":
        raise ApiError(409, "release_not_frozen", "Only a frozen release can be retracted.")
    if release.status == "retracted":
        raise ApiError(409, "release_retracted", "This release is already retracted.")
    now = utcnow()
    release.status = "retracted"
    release.retracted_at = now
    release.retraction_note = note
    release.updated_at = now
    closed = close_exports(
        db,
        store,
        actor_id=admin.id,
        release_id=release.id,
        now=now,
        note="The release was retracted.",
    )
    audit.record(
        db,
        action="release.retract",
        context=context,
        actor_user_id=admin.id,
        target_type="dataset_release",
        target_id=release.id,
        details={"slug": release.slug, "version": release.version, "exports_closed": closed},
    )
    db.commit()
    return release


def close_exports(
    db: Session,
    store: ObjectStore,
    *,
    actor_id: uuid.UUID,
    release_id: uuid.UUID,
    now: datetime,
    note: str,
) -> int:
    """Called in the transaction that retracts a release or marks one of its items withdrawn:
    open requests are rejected with `note` and built packages deleted, so nothing of the
    release can still be downloaded."""
    requests = db.scalars(
        select(ExportRequest)
        .where(
            ExportRequest.release_id == release_id,
            ExportRequest.status.in_((*OPEN_STATUSES, "ready")),
        )
        .with_for_update()
    ).all()
    for request in requests:
        if request.status == "ready" and request.object_key:
            store.delete(Bucket.EXPORTS, request.object_key)
            request.status = "expired"
            continue
        request.status = "rejected"
        request.decided_by = actor_id
        request.decided_at = now
        request.decision_note = note
    return len(requests)


def download(
    db: Session,
    store: ObjectStore,
    *,
    user: AuthenticatedUser,
    export_id: uuid.UUID,
    ttl_seconds: int,
    context: RequestContext,
) -> tuple[ExportRequest, str]:
    """A short-lived link to the package, for the person who asked for it. Every download is
    recorded with the request and in the audit log."""
    request = get_export(db, user, export_id, for_update=True)
    if request.requested_by != user.id:
        raise ApiError(403, "forbidden", "Only the person who asked for it can download it.")
    now = utcnow()
    if request.status == "expired" or (
        request.status == "ready" and request.expires_at and request.expires_at <= now
    ):
        raise ApiError(409, "export_expired", "This package has expired; ask for a new one.")
    if request.status != "ready" or request.object_key is None:
        raise ApiError(409, "export_not_ready", "This package is not ready.")
    exportable(db, service.get_release(db, request.release_id))
    request.downloaded_at = [*request.downloaded_at, now]
    audit.record(
        db,
        action="export.download",
        context=context,
        actor_user_id=user.id,
        target_type="export_request",
        target_id=request.id,
        details={"release_id": str(request.release_id), "sha256": request.sha256},
    )
    url = store.signed_url(
        Bucket.EXPORTS,
        request.object_key,
        ttl_seconds=ttl_seconds,
        content_type="application/zip",
        download_name=request.object_key.rsplit("/", 1)[-1],
    )
    db.commit()
    return request, url
