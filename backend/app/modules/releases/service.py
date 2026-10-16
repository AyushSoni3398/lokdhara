"""Draft releases and their preview (docs/DATASET_VERSIONING.md §1, §2, §3).

A PATCH draft replaces a frozen release: it can only take items of that release, so items
withdrawn since, or whose consent no longer allows the purpose, are left out by the release rule
and nothing new comes in.
"""

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
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem
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


def withdrawn_counts(db: Session, release_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many items of each frozen release were withdrawn after it was frozen."""
    if not release_ids:
        return {}
    rows = db.execute(
        select(DatasetReleaseItem.release_id, func.count())
        .where(
            DatasetReleaseItem.release_id.in_(release_ids),
            DatasetReleaseItem.withdrawn_after_release_at.is_not(None),
        )
        .group_by(DatasetReleaseItem.release_id)
    ).all()
    return {release_id: count for release_id, count in rows}


def _version(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def next_patch_version(db: Session, release: DatasetRelease) -> str | None:
    """For a PATCH draft: the replaced release's MAJOR.MINOR with the next free PATCH."""
    if release.replaces_id is None or release.status != "draft":
        return None
    replaced = get_release(db, release.replaces_id)
    major, minor, _ = _version(replaced.version or "0.0.0")
    patches = [
        _version(v)[2]
        for v in db.scalars(
            select(DatasetRelease.version).where(
                DatasetRelease.slug == release.slug, DatasetRelease.version.is_not(None)
            )
        )
        if v and _version(v)[:2] == (major, minor)
    ]
    return f"{major}.{minor}.{max(patches, default=-1) + 1}"


def check_patch_version(db: Session, release: DatasetRelease, version: str) -> None:
    """A PATCH draft is frozen as a later PATCH of the release it replaces."""
    if release.replaces_id is None:
        return
    replaced = get_release(db, release.replaces_id)
    old, new = _version(replaced.version or "0.0.0"), _version(version)
    if new[:2] != old[:2] or new[2] <= old[2]:
        raise ApiError(
            422,
            "version_not_patch",
            f"Freeze this as a later patch of {replaced.version}, such as "
            f"{next_patch_version(db, release)}.",
        )


def _patch_notice(replaced: DatasetRelease, withdrawn: int) -> str:
    return (
        f"This release replaces {replaced.slug} {replaced.version}. "
        f"{withdrawn} items of that release were taken out because their speakers withdrew "
        "them or no longer allow this use."
    )


def start_patch(
    db: Session, *, user: AuthenticatedUser, release_id: uuid.UUID, context: RequestContext
) -> DatasetRelease:
    """Starts the PATCH draft that replaces a frozen release, or returns the one already
    started (docs/DATASET_VERSIONING.md §2)."""
    replaced = get_release(db, release_id, for_update=True)
    if replaced.status == "draft":
        raise ApiError(409, "release_not_frozen", "Only a frozen release can be replaced.")
    if replaced.status == "retracted":
        raise ApiError(409, "release_retracted", "This release was retracted.")
    existing = db.scalar(
        select(DatasetRelease).where(
            DatasetRelease.replaces_id == replaced.id, DatasetRelease.status == "draft"
        )
    )
    if existing is not None:
        return existing
    withdrawn = withdrawn_counts(db, [replaced.id]).get(replaced.id, 0)
    card = "\n\n".join(
        p for p in (_patch_notice(replaced, withdrawn), replaced.data_card_markdown) if p
    )
    release = DatasetRelease(
        slug=replaced.slug,
        purpose=replaced.purpose,
        selection_criteria=replaced.selection_criteria,
        licence=replaced.licence,
        data_card_markdown=card[:50000],
        created_by=user.id,
        replaces_id=replaced.id,
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
        details={"slug": release.slug, "purpose": release.purpose, "replaces": str(replaced.id)},
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
    if (
        release.replaces_id is not None
        and changes.get("purpose", release.purpose) != release.purpose
    ):
        raise ApiError(
            409, "patch_purpose_fixed", "A patch keeps the purpose of the release it replaces."
        )
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


def _in_replaced(release: DatasetRelease) -> ColumnElement[bool]:
    """A PATCH draft only takes items of the release it replaces."""
    if release.replaces_id is None:
        return true()
    return Submission.id.in_(
        select(DatasetReleaseItem.submission_id).where(
            DatasetReleaseItem.release_id == release.replaces_id
        )
    )


def selection(release: DatasetRelease) -> Select[Submission]:
    """The items freezing this release now would take, oldest first."""
    criteria = SelectionCriteria.model_validate(release.selection_criteria)
    return (
        select(Submission)
        .where(release_filter(release.purpose), matches_criteria(criteria), _in_replaced(release))
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
        .where(release_filter(release.purpose), matches_criteria(criteria), _in_replaced(release))
        .subquery()
    )
    item_count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(chosen.c.duration_ms), 0)).select_from(chosen)
    ).one()
    candidates = db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(
            Submission.status.in_(CATALOGUE_STATUSES),
            matches_criteria(criteria),
            _in_replaced(release),
        )
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
