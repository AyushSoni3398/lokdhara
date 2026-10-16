"""What a withdrawal or a narrower consent does to frozen releases (docs/DATASET_VERSIONING.md
§2, docs/DATA_RETENTION_AND_DELETION.md §2.4 and §3).

A frozen release never changes, so the affected items are marked `withdrawn_after_release_at`.
From then on no package of that release is built or downloaded: ready packages are deleted and
open requests rejected in the same transaction. The next PATCH release leaves the items out.
"""

import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.orm import Session

from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.consents.access import consent_allows
from app.modules.releases.exports import close_exports
from app.modules.releases.models import PURPOSES, DatasetRelease, DatasetReleaseItem
from app.modules.submissions.models import Submission
from app.object_store import ObjectStore

EXPORT_NOTE = "An item of this release was withdrawn; ask for the next release instead."


def _mark(
    db: Session,
    store: ObjectStore,
    *,
    submission_ids: Collection[uuid.UUID],
    refused: ColumnElement[bool] | None,
    purposes: Collection[str],
    reason: str,
    actor_id: uuid.UUID,
    now: datetime,
    context: RequestContext | None,
) -> int:
    if not submission_ids:
        return 0
    query = (
        select(DatasetReleaseItem, DatasetRelease)
        .join(DatasetRelease, DatasetRelease.id == DatasetReleaseItem.release_id)
        .join(Submission, Submission.id == DatasetReleaseItem.submission_id)
        .where(
            DatasetReleaseItem.submission_id.in_(submission_ids),
            DatasetReleaseItem.withdrawn_after_release_at.is_(None),
            DatasetRelease.purpose.in_(purposes),
            refused if refused is not None else true(),
        )
        .order_by(DatasetRelease.id)
        .with_for_update(of=DatasetReleaseItem)
    )
    marked: dict[uuid.UUID, int] = {}
    for item, release in db.execute(query).all():
        item.withdrawn_after_release_at = now
        marked[release.id] = marked.get(release.id, 0) + 1
    for release_id, count in marked.items():
        closed = close_exports(
            db, store, actor_id=actor_id, release_id=release_id, now=now, note=EXPORT_NOTE
        )
        audit.record(
            db,
            action="release.items_withdrawn",
            context=context,
            actor_user_id=actor_id,
            target_type="dataset_release",
            target_id=release_id,
            details={"items": count, "reason": reason, "exports_closed": closed},
        )
    return len(marked)


def mark_withdrawn(
    db: Session,
    store: ObjectStore,
    *,
    submission_ids: Collection[uuid.UUID],
    actor_id: uuid.UUID,
    now: datetime,
    context: RequestContext | None,
) -> int:
    """The items were withdrawn: every frozen release holding them is marked. Returns how many
    releases were affected."""
    return _mark(
        db,
        store,
        submission_ids=submission_ids,
        refused=None,
        purposes=PURPOSES,
        reason="withdrawn",
        actor_id=actor_id,
        now=now,
        context=context,
    )


def mark_consent_narrowed(
    db: Session,
    store: ObjectStore,
    *,
    speaker_id: uuid.UUID,
    actor_id: uuid.UUID,
    now: datetime,
    context: RequestContext | None,
) -> int:
    """The speaker's consent changed: a frozen release is marked only for the items whose
    consent no longer allows that release's purpose (§3). Call after the new consent record is
    flushed. Returns how many releases were affected."""
    submission_ids = list(
        db.scalars(select(Submission.id).where(Submission.speaker_id == speaker_id))
    )
    return sum(
        _mark(
            db,
            store,
            submission_ids=submission_ids,
            refused=~consent_allows(purpose),
            purposes=(purpose,),
            reason="consent_narrowed",
            actor_id=actor_id,
            now=now,
            context=context,
        )
        for purpose in PURPOSES
    )
