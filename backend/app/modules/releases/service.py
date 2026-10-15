"""Draft releases and their preview (docs/DATASET_VERSIONING.md §1, §3)."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, exists, func, select, true
from sqlalchemy.orm import Session

from app.audio import renditions
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.consents.access import CATALOGUE_STATUSES, release_filter
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.releases.models import DatasetRelease
from app.modules.releases.schemas import (
    ReleaseCreateRequest,
    ReleaseUpdateRequest,
    SelectionCriteria,
)
from app.modules.submissions.models import Recording, Rendition, Submission, TextLayer

SAMPLE_SIZE = 5
NO_DIALECT = "(none)"


def not_found() -> ApiError:
    return ApiError(404, "release_not_found", "Release not found.")


def get_release(db: Session, release_id: uuid.UUID, *, for_update: bool = False) -> DatasetRelease:
    query = select(DatasetRelease).where(DatasetRelease.id == release_id)
    release = db.scalar(query.with_for_update() if for_update else query)
    if release is None:
        raise not_found()
    return release


def list_releases(db: Session) -> list[DatasetRelease]:
    return list(db.scalars(select(DatasetRelease).order_by(DatasetRelease.created_at.desc())))


def _draft_for_change(
    db: Session, user: AuthenticatedUser, release_id: uuid.UUID
) -> DatasetRelease:
    release = get_release(db, release_id, for_update=True)
    if release.status != "draft":
        raise ApiError(409, "release_frozen", "A frozen release cannot change.")
    if release.created_by != user.id and not user.has_role("admin"):
        raise ApiError(
            403, "forbidden", "Only the person who started it or an admin can change it."
        )
    return release


def create_draft(
    db: Session, *, user: AuthenticatedUser, body: ReleaseCreateRequest, context: RequestContext
) -> DatasetRelease:
    release = DatasetRelease(
        slug=body.slug,
        purpose=body.purpose,
        selection_criteria=body.selection_criteria.model_dump(),
        licence=body.licence,
        data_card_markdown=body.data_card_markdown or "",
        created_by=user.id,
    )
    db.add(release)
    db.flush()
    audit.record(
        db,
        action="release.create",
        context=context,
        actor_user_id=user.id,
        target_type="dataset_release",
        target_id=release.id,
        details={"slug": body.slug, "purpose": body.purpose},
    )
    db.commit()
    return release


def update_draft(
    db: Session,
    *,
    user: AuthenticatedUser,
    release_id: uuid.UUID,
    body: ReleaseUpdateRequest,
) -> DatasetRelease:
    release = _draft_for_change(db, user, release_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("purpose") is None:
        changes.pop("purpose", None)
    if "selection_criteria" in changes:
        changes["selection_criteria"] = (
            body.selection_criteria or SelectionCriteria()
        ).model_dump()
    if "data_card_markdown" in changes:
        changes["data_card_markdown"] = changes["data_card_markdown"] or ""
    for field, value in changes.items():
        setattr(release, field, value)
    release.updated_at = utcnow()
    db.commit()
    return release


# ------------------------------------------------------------------ selection


def _has_analysis_copy() -> ColumnElement[bool]:
    return exists().where(
        Recording.submission_id == Submission.id,
        Recording.upload_status == "promoted",
        exists().where(
            Rendition.recording_id == Recording.id,
            Rendition.kind == renditions.ANALYSIS.name,
        ),
    )


def _has_main_text() -> ColumnElement[bool]:
    return exists().where(
        TextLayer.submission_id == Submission.id,
        TextLayer.layer_type != "translation",
        TextLayer.current_revision_id.is_not(None),
    )


def matches_criteria(criteria: SelectionCriteria) -> ColumnElement[bool]:
    conditions: list[ColumnElement[bool]] = []
    for column, values in (
        (Submission.kind, criteria.kinds),
        (Submission.content_type, criteria.content_types),
        (Submission.recording_mode, criteria.recording_modes),
        (Submission.dialect_label, criteria.dialect_labels),
    ):
        if values:
            conditions.append(column.in_(values))
    if criteria.needs_audio:
        conditions.append(_has_analysis_copy())
    if criteria.needs_transcription:
        conditions.append(_has_main_text())
    return and_(true(), *conditions)


def selection(release: DatasetRelease) -> Select[Submission]:
    """The items freezing this release now would take, oldest first."""
    criteria = SelectionCriteria.model_validate(release.selection_criteria)
    return (
        select(Submission)
        .where(release_filter(release.purpose), matches_criteria(criteria))
        .order_by(Submission.id)
    )


def _duration() -> Any:
    return (
        select(func.coalesce(func.max(Recording.duration_ms), 0))
        .where(Recording.submission_id == Submission.id, Recording.upload_status == "promoted")
        .correlate(Submission)
        .scalar_subquery()
    )


@dataclass(frozen=True)
class Preview:
    item_count: int
    total_duration_ms: int
    left_out_count: int
    by_content_type: dict[str, int]
    by_dialect_label: dict[str, int]
    by_kind: dict[str, int]
    sample: list[tuple[Submission, int | None]]


def _counts(db: Session, chosen: Any, column: Any) -> dict[str, int]:
    rows = db.execute(
        select(column, func.count()).select_from(chosen).group_by(column).order_by(column)
    ).all()
    return {(key if key is not None else NO_DIALECT): count for key, count in rows}


def preview(db: Session, release: DatasetRelease) -> Preview:
    criteria = SelectionCriteria.model_validate(release.selection_criteria)
    chosen = (
        select(
            Submission.id,
            Submission.content_type,
            Submission.dialect_label,
            Submission.kind,
            _duration().label("duration_ms"),
        )
        .where(release_filter(release.purpose), matches_criteria(criteria))
        .subquery()
    )
    item_count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(chosen.c.duration_ms), 0)).select_from(chosen)
    ).one()
    candidates = db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(Submission.status.in_(CATALOGUE_STATUSES), matches_criteria(criteria))
    )
    sample_rows = db.execute(
        select(Submission, _duration()).where(
            Submission.id.in_(select(chosen.c.id).order_by(chosen.c.id).limit(SAMPLE_SIZE))
        )
    ).all()
    return Preview(
        item_count=item_count,
        total_duration_ms=int(total),
        left_out_count=(candidates or 0) - item_count,
        by_content_type=_counts(db, chosen, chosen.c.content_type),
        by_dialect_label=_counts(db, chosen, chosen.c.dialect_label),
        by_kind=_counts(db, chosen, chosen.c.kind),
        sample=[(row[0], row[1] or None) for row in sample_rows],
    )
