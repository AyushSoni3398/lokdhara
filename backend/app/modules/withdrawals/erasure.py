"""The deletion routine, `withdrawal.erase` (docs/DATA_RETENTION_AND_DELETION.md §2.6 and
"Deletion mechanics").

Once an admin verifies a full or one-item withdrawal, this job deletes the speaker's files and
clears what they said, keeping only what is needed to show that the request was honoured:

- the original recording, its quarantine copy and every derived file, in every stored version;
- the text of every revision (the rows stay as tombstones, so release manifests stay readable);
- the title and collection notes of each submission, and the notes of reports about it;
- the `items.jsonl` kept for each frozen release that held an item, since its packages can no
  longer be built anyway;
- for a full withdrawal, the restricted identity details and demographics of the speaker, and
  the free-text notes of their consent records. The recording of an oral consent stays while
  `LKD_WITHDRAWAL_KEEP_CONSENT_EVIDENCE` is on (Q-G8).

The database part runs as `app_erasure` with `lkd.erasure` set, the only way past the
append-only triggers. Files are deleted before the database changes are committed, so a job
that fails half way simply runs again.
"""

import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, delete, func, select, text, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.audit import service as audit
from app.modules.consents.models import ConsentRecord, WithdrawalRequest
from app.modules.processing.queue import JobContext, JobResult, handler, utcnow
from app.modules.releases.freeze import stored_file_key
from app.modules.releases.models import DatasetReleaseItem
from app.modules.reports.models import Report
from app.modules.speakers import service as speakers
from app.modules.speakers.models import Speaker, SpeakerIdentity
from app.modules.submissions.models import (
    Recording,
    Rendition,
    Submission,
    TextLayer,
    TextRevision,
)
from app.object_store import Bucket, ObjectStore, get_object_store

# The scopes whose items are deleted; a narrowed consent deletes nothing.
ERASED_SCOPES = ("full", "specific_items")


@lru_cache
def _engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def erasure_engine(context: JobContext) -> Engine:
    url = get_settings().erasure_database_url
    return _engine_for(url) if url else context.db.get_bind().engine


def _submissions(db: Session, request: WithdrawalRequest) -> list[Submission]:
    """Only items that were actually withdrawn are ever erased."""
    query = select(Submission).where(Submission.status == "withdrawn")
    if request.requested_scope == "full":
        query = query.where(Submission.speaker_id == request.speaker_id)
    else:
        query = query.where(Submission.id == request.submission_id)
    return list(db.scalars(query.order_by(Submission.id).with_for_update()))


def _erase_files(
    store: ObjectStore,
    recordings: list[Recording],
    renditions: list[Rendition],
    release_ids: list[uuid.UUID],
    evidence_keys: list[str],
) -> int:
    files = [(Bucket.QUARANTINE, r.original_object_key) for r in recordings]
    files += [(Bucket.ORIGINALS, r.original_object_key) for r in recordings]
    files += [(Bucket.DERIVED, r.object_key) for r in renditions]
    files += [(Bucket.EXPORTS, stored_file_key(i, "items.jsonl")) for i in release_ids]
    files += [(Bucket.CONSENT_EVIDENCE, key) for key in evidence_keys]
    for bucket, key in files:
        store.erase(bucket, key)
    return len(files)


def _erase_speaker(db: Session, speaker: Speaker) -> None:
    db.execute(delete(SpeakerIdentity).where(SpeakerIdentity.speaker_id == speaker.id))
    speakers.set_demographics_consent(speaker, False)
    db.execute(
        update(ConsentRecord).where(ConsentRecord.speaker_id == speaker.id).values(notes=None)
    )


def erase(db: Session, store: ObjectStore, request_id: uuid.UUID) -> dict[str, Any] | None:
    """Erases what a verified request covers. `db` must be an erasure session; the caller
    commits. Returns what was done, or None when there is nothing (left) to do."""
    db.execute(text("SET LOCAL ROLE app_erasure"))
    db.execute(text("SET LOCAL lkd.erasure = 'on'"))
    request = db.scalar(
        select(WithdrawalRequest).where(WithdrawalRequest.id == request_id).with_for_update()
    )
    if (
        request is None
        or request.erased_at is not None
        or request.status != "verified"
        or request.requested_scope not in ERASED_SCOPES
    ):
        return None
    settings = get_settings()
    full = request.requested_scope == "full"
    speaker = db.scalar(select(Speaker).where(Speaker.id == request.speaker_id).with_for_update())
    if speaker is None:  # pragma: no cover - a foreign key guarantees it
        return None

    submission_ids = [s.id for s in _submissions(db, request)]
    recordings = list(
        db.scalars(
            select(Recording).where(Recording.submission_id.in_(submission_ids)).with_for_update()
        )
    )
    renditions = list(
        db.scalars(select(Rendition).where(Rendition.recording_id.in_([r.id for r in recordings])))
    )
    release_ids = list(
        db.scalars(
            select(DatasetReleaseItem.release_id)
            .where(DatasetReleaseItem.submission_id.in_(submission_ids))
            .distinct()
        )
    )
    evidence_keys: list[str] = []
    if full and not settings.withdrawal_keep_consent_evidence:
        evidence_keys = [
            key
            for key in db.scalars(
                select(ConsentRecord.evidence_object_key).where(
                    ConsentRecord.speaker_id == speaker.id
                )
            )
            if key
        ]

    files = _erase_files(store, recordings, renditions, release_ids, evidence_keys)
    for recording in recordings:
        recording.upload_status = "erased"
    layers = select(TextLayer.id).where(TextLayer.submission_id.in_(submission_ids))
    revisions = db.scalar(
        select(func.count()).select_from(TextRevision).where(TextRevision.layer_id.in_(layers))
    )
    db.execute(
        update(TextRevision)
        .where(TextRevision.layer_id.in_(layers))
        .values(
            content_original="",
            content_nfc="",
            content_normalized=None,
            normalization_policy_version=None,
            change_note=None,
        )
    )
    now = utcnow()
    db.execute(
        update(Submission)
        .where(Submission.id.in_(submission_ids))
        .values(title=None, collection_context={}, updated_at=now)
    )
    db.execute(update(Report).where(Report.submission_id.in_(submission_ids)).values(note=None))
    if full:
        _erase_speaker(db, speaker)

    done: dict[str, Any] = {
        "action": "erased",
        "at": now.isoformat(),
        "items": len(submission_ids),
        "recordings": len(recordings),
        "files": files,
        "text_revisions": revisions,
        "release_item_lists": len(release_ids),
        "identity_deleted": full,
        "consent_evidence": "deleted" if evidence_keys else "kept",
    }
    request.erased_at = now
    request.actions_taken = [*request.actions_taken, done]
    audit.record(
        db,
        action="withdrawal.erase",
        context=None,
        actor_user_id=None,
        actor_type="worker",
        target_type="withdrawal_request",
        target_id=request.id,
        details={k: v for k, v in done.items() if k not in ("action", "at")},
    )
    return done


@handler("withdrawal.erase")
def erase_withdrawn(context: JobContext) -> JobResult:
    request_id = context.target_id
    context.db.rollback()  # the job's own session holds nothing while the routine runs
    if request_id is None:
        return JobResult(output_summary={"skipped": "no_target"})
    with Session(erasure_engine(context)) as db, db.begin():
        done = erase(db, get_object_store(), request_id)
    if done is None:
        return JobResult(output_summary={"skipped": True})
    return JobResult(output_summary={k: v for k, v in done.items() if k not in ("action", "at")})
