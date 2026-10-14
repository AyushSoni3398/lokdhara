"""Submission drafts and submitting them for processing (docs/USER_FLOWS.md F1).

A draft exists on the device first; the server copy is created when the contributor uploads.
Consent is required before any audio reaches the server and again at submit, when the active
consent record is attached (the database refuses to let a submission leave draft without one).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.consents import service as consents
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.processing import queue
from app.modules.processing.models import Job
from app.modules.prompts import service as prompts
from app.modules.speakers import service as speakers
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import Recording, Submission, TextLayer, TextRevision
from app.modules.submissions.schemas import SubmissionCreateRequest, SubmissionUpdateRequest
from app.object_store import Bucket, ObjectStore
from app.text import scripts
from app.text.normalize import to_nfc

EDITABLE_STATUSES = ("draft", "changes_requested")
AUDIO_KINDS = ("audio", "audio_text")
TEXT_KINDS = ("text", "audio_text")
MAX_PAGE = 100


def _not_found() -> ApiError:
    # Same answer whether the submission does not exist or is not visible to this user.
    return ApiError(404, "submission_not_found", "Submission not found.")


def consent_required() -> ApiError:
    return ApiError(
        422, "consent_required", "The speaker's consent must be recorded before this step."
    )


# ------------------------------------------------------------------ access


def visible_to(user: AuthenticatedUser) -> ColumnElement[bool]:
    """Milestone 3 part of the data-level rule (docs/ACCESS_CONTROL.md §3): people see what
    they submitted, facilitators also see what was recorded of speakers they registered, and
    admins see everything. Reviewer and researcher access arrive with review and datasets."""
    if user.has_role("admin"):
        return true()
    own = Submission.submitted_by == user.id
    if user.has_role("facilitator"):
        own = or_(own, Submission.speaker_id.in_(speakers.created_by(user.id)))
    return and_(Submission.status != "withdrawn", own)


def get_visible(db: Session, user: AuthenticatedUser, submission_id: uuid.UUID) -> Submission:
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id, visible_to(user))
    )
    if submission is None:
        raise _not_found()
    return submission


def get_owned(
    db: Session, user: AuthenticatedUser, submission_id: uuid.UUID, *, for_update: bool = False
) -> Submission:
    """Only the person who created a submission edits, uploads to, or submits it."""
    query = select(Submission).where(Submission.id == submission_id, visible_to(user))
    if for_update:
        query = query.with_for_update()
    submission = db.scalar(query)
    if submission is None:
        raise _not_found()
    if submission.submitted_by != user.id:
        raise ApiError(403, "forbidden", "Only the person who created it can change this.")
    return submission


# ------------------------------------------------------------------ drafts


def _check_collection_method(user: AuthenticatedUser, speaker: Speaker, method: str) -> None:
    is_self = speaker.linked_user_id == user.id
    allowed = {
        "self_recorded": is_self,
        "facilitator_field": not is_self and user.has_role("facilitator", "admin"),
        "facilitator_remote": not is_self and user.has_role("facilitator", "admin"),
        "imported_archive": user.has_role("admin"),
    }
    if not allowed[method]:
        raise ApiError(
            422,
            "collection_method_not_allowed",
            "This collection method does not fit this speaker or your role.",
        )


def create_draft(
    db: Session, *, user: AuthenticatedUser, body: SubmissionCreateRequest
) -> Submission:
    existing = _by_client_id(db, body.client_submission_id)
    if existing is not None:
        return _replay(existing, user)
    speaker = speakers.get_for_action(db, user, body.speaker_id)
    _check_collection_method(user, speaker, body.collection_method)
    if body.prompt_id is not None and body.recording_mode is not None:
        prompts.get_for_recording(db, body.prompt_id, body.recording_mode)

    submission = Submission(
        **body.model_dump(exclude={"collection_context"}),
        collection_context=body.collection_context.model_dump(exclude_none=True),
        submitted_by=user.id,
    )
    db.add(submission)
    try:
        db.commit()
    except IntegrityError:
        # The same draft sent twice at once: the other request created it.
        db.rollback()
        existing = _by_client_id(db, body.client_submission_id)
        if existing is None:
            raise
        return _replay(existing, user)
    return submission


def _by_client_id(db: Session, client_submission_id: uuid.UUID) -> Submission | None:
    return db.scalar(
        select(Submission).where(Submission.client_submission_id == client_submission_id)
    )


def _replay(existing: Submission, user: AuthenticatedUser) -> Submission:
    if existing.submitted_by != user.id:
        raise ApiError(
            409, "client_submission_id_taken", "This draft ID is already used; make a new one."
        )
    return existing


def list_submissions(
    db: Session,
    user: AuthenticatedUser,
    *,
    mine: bool,
    status: str | None,
    limit: int,
    cursor: uuid.UUID | None,
) -> tuple[list[Submission], uuid.UUID | None]:
    """Newest first. IDs are UUIDv7, so ordering by ID is ordering by creation time."""
    query = select(Submission).where(visible_to(user)).order_by(Submission.id.desc())
    if mine:
        query = query.where(Submission.submitted_by == user.id)
    if status is not None:
        query = query.where(Submission.status == status)
    if cursor is not None:
        query = query.where(Submission.id < cursor)
    rows = list(db.scalars(query.limit(limit + 1)))
    if len(rows) > limit:
        return rows[:limit], rows[limit - 1].id
    return rows, None


def update_draft(
    db: Session, *, user: AuthenticatedUser, submission_id: uuid.UUID, body: SubmissionUpdateRequest
) -> Submission:
    submission = get_owned(db, user, submission_id, for_update=True)
    if submission.status not in EDITABLE_STATUSES:
        raise ApiError(409, "submission_not_editable", "This submission can no longer be edited.")
    changes = body.model_dump(exclude_unset=True, exclude={"collection_context"})
    for field, value in changes.items():
        setattr(submission, field, value)
    if body.collection_context is not None:
        submission.collection_context = body.collection_context.model_dump(exclude_none=True)
    submission.updated_at = utcnow()
    db.commit()
    return submission


def recordings_of(db: Session, submission_id: uuid.UUID) -> list[Recording]:
    return list(
        db.scalars(
            select(Recording)
            .where(Recording.submission_id == submission_id)
            .order_by(Recording.created_at)
        )
    )


@dataclass(frozen=True)
class LayerView:
    layer: TextLayer
    current: TextRevision | None
    source_changed: bool


def _source_changed(current: TextRevision | None, source_current: uuid.UUID | None) -> bool:
    """A translation is stale when its source got a revision after the one it translated."""
    return current is not None and current.source_revision_id not in (None, source_current)


def text_layers_of(db: Session, submission_id: uuid.UUID) -> list[LayerView]:
    rows = list(
        db.execute(
            select(TextLayer, TextRevision)
            .outerjoin(TextRevision, TextRevision.id == TextLayer.current_revision_id)
            .where(TextLayer.submission_id == submission_id)
            .order_by(TextLayer.created_at)
        )
    )
    # Translations always translate a layer of the same submission.
    current_of = {layer.id: layer.current_revision_id for layer, _ in rows}
    return [
        LayerView(
            layer,
            current,
            layer.source_layer_id is not None
            and _source_changed(current, current_of.get(layer.source_layer_id)),
        )
        for layer, current in rows
    ]


def layer_view(db: Session, layer: TextLayer) -> LayerView:
    current = None
    if layer.current_revision_id is not None:
        current = db.get(TextRevision, layer.current_revision_id)
    source_changed = False
    if layer.source_layer_id is not None:
        source_current = db.scalar(
            select(TextLayer.current_revision_id).where(TextLayer.id == layer.source_layer_id)
        )
        source_changed = _source_changed(current, source_current)
    return LayerView(layer, current, source_changed)


# ------------------------------------------------------------------ submit


def submit(
    db: Session, store: ObjectStore, *, user: AuthenticatedUser, submission_id: uuid.UUID
) -> Submission:
    """Draft → processing. Attaches the speaker's active consent and queues validation."""
    submission = get_owned(db, user, submission_id, for_update=True)
    if submission.status != "draft":
        raise ApiError(409, "submission_not_draft", "Only drafts can be submitted.")
    speaker = speakers.get_for_action(db, user, submission.speaker_id)
    consent = consents.active_consent(db, speaker.id)
    if consent is None:
        raise consent_required()

    recordings = recordings_of(db, submission.id)
    if submission.kind in AUDIO_KINDS and not recordings:
        raise ApiError(422, "recording_required", "Upload the recording before submitting.")
    for recording in recordings:
        if recording.upload_status == "expired":
            raise ApiError(
                409,
                "recording_expired",
                "The recording was removed after waiting too long. Upload it again.",
            )
        if store.head(Bucket.QUARANTINE, recording.original_object_key) is None:
            raise ApiError(
                409, "recording_missing", "The uploaded recording is no longer available."
            )
    has_text = any(view.current for view in text_layers_of(db, submission.id))
    if submission.kind in TEXT_KINDS and not has_text:
        raise ApiError(422, "text_required", "Add the text before submitting.")

    if submission.recording_mode == "read" and submission.prompt_id is not None:
        has_text = _add_prompt_text(db, submission, recordings[0]) or has_text

    submission.consent_record_id = consent.id
    submission.status = "processing"
    submission.submitted_at = submission.updated_at = utcnow()
    for recording in recordings:
        queue.enqueue(
            db,
            "audio.validate",
            target_type="recording",
            target_id=recording.id,
            dedupe_key=f"audio.validate:{recording.id}",
        )
    if has_text:
        queue.enqueue(
            db,
            "text.derive",
            target_type="submission",
            target_id=submission.id,
            dedupe_key=f"text.derive:{submission.id}",
        )
    db.commit()
    return submission


def _add_prompt_text(db: Session, submission: Submission, recording: Recording) -> bool:
    """Read speech: the sentence that was read becomes the first transcription, with origin
    `prompt_text` and unverified, because speakers do not always read exactly what is shown.
    Skipped when the contributor already typed a transcription of their own."""
    if submission.prompt_id is None:
        return False
    already = db.scalar(
        select(TextLayer.id)
        .where(TextLayer.recording_id == recording.id, TextLayer.layer_type == "transcription")
        .limit(1)
    )
    prompt = prompts.recorded_prompt(db, submission.prompt_id)
    if already is not None or prompt.text is None or prompt.script_code is None:
        return False
    layer = TextLayer(
        submission_id=submission.id,
        layer_type="transcription",
        recording_id=recording.id,
        language_tag=prompt.text_language_tag or submission.language_tag,
        script_code=prompt.script_code,
    )
    db.add(layer)
    db.flush()
    revision = TextRevision(
        layer_id=layer.id,
        revision_number=1,
        content_original=prompt.text,
        content_nfc=to_nfc(prompt.text),
        detected_scripts=scripts.detect(prompt.text),
        origin="prompt_text",
    )
    db.add(revision)
    db.flush()
    layer.current_revision_id = revision.id
    return True


# ------------------------------------------------------------------ processing status

# Housekeeping that does not change whether a submission can be accepted.
_HOUSEKEEPING = ("cleanup.quarantine",)


@queue.on_job_changed
def follow_processing(db: Session, job: Job) -> None:
    """Moves a submission on once its checks have settled (docs/DATA_LIFECYCLE.md stage 4):
    to `accepted` when every check succeeded (no human reviewer, ADR-021), to
    `processing_failed` when one failed for good, and back to `processing` when an admin
    queues the failed ones again."""
    if job.job_type in _HOUSEKEEPING or job.target_id is None:
        return
    if job.target_type == "recording":
        submission_id = db.scalar(
            select(Recording.submission_id).where(Recording.id == job.target_id)
        )
    elif job.target_type == "submission":
        submission_id = job.target_id
    else:
        return
    submission = db.scalar(
        select(Submission).where(Submission.id == submission_id).with_for_update()
    )
    # A rejected recording has already decided the submission (rejected_invalid).
    if submission is None or submission.status not in ("processing", "processing_failed"):
        return
    recording_ids = [recording.id for recording in recordings_of(db, submission.id)]
    # Only the latest job of each kind counts: a check that was run again replaces the old one.
    latest = (
        select(Job.status)
        .where(
            or_(
                and_(Job.target_type == "submission", Job.target_id == submission.id),
                and_(Job.target_type == "recording", Job.target_id.in_(recording_ids)),
            ),
            Job.job_type.not_in(_HOUSEKEEPING),
        )
        .ext(distinct_on(Job.job_type, Job.target_id))
        .order_by(Job.job_type, Job.target_id, Job.id.desc())
    )
    states = set(db.scalars(latest))
    if "failed" in states:
        status = "processing_failed"
    elif states & {"queued", "running"}:
        status = "processing"
    else:
        status = "accepted"
    if status != submission.status:
        submission.status = status
        submission.updated_at = utcnow()
