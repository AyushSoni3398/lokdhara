"""Text layers and their revisions (docs/TEXT_PROCESSING_PIPELINE.md, ADR-010, ADR-011).

Every save is a new revision; nothing is edited in place. `content_original` is exactly what
was sent once it passes the safety checks; `content_nfc` and the detected scripts are derived next
to it, because a saved revision never changes. Duplicate checks run later in `text.derive`.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.processing import queue
from app.modules.submissions import service
from app.modules.submissions.models import Recording, Submission, TextLayer, TextRevision
from app.modules.submissions.schemas import RevisionCreateRequest, TextLayerCreateRequest
from app.text import diff, markup, normalize, safety, scripts

# Which layer types each submission kind takes.
_LAYERS_FOR_KIND = {
    "audio": ("transcription", "translation"),
    "text": ("standalone", "translation"),
    "audio_text": ("standalone", "transcription", "translation"),
}


def _not_found() -> ApiError:
    return ApiError(404, "text_layer_not_found", "Text not found.")


def _invalid_link() -> ApiError:
    return ApiError(
        422, "layer_link_invalid", "The linked recording or text is not part of this submission."
    )


def _checked(content: str, entry_type: str | None) -> str:
    try:
        return safety.check(content, entry_type)
    except safety.TextRejected as exc:
        raise ApiError(422, exc.code, "This text cannot be saved.") from exc


def _check_editable(submission: Submission) -> None:
    if submission.status not in service.TEXT_EDITABLE_STATUSES:
        raise ApiError(409, "submission_not_editable", "This submission can no longer be edited.")


def _text_changed(db: Session, submission: Submission) -> None:
    submission.updated_at = utcnow()
    if submission.status == "accepted":
        # Check the changed text again (scripts, duplicates); the submission stays accepted.
        queue.enqueue(
            db,
            "text.derive",
            target_type="submission",
            target_id=submission.id,
            dedupe_key=f"text.derive:{submission.id}",
        )


def _new_revision(
    db: Session,
    layer: TextLayer,
    *,
    number: int,
    content: str,
    author: uuid.UUID,
    based_on: uuid.UUID | None = None,
    change_note: str | None = None,
) -> TextRevision:
    source_revision = None
    if layer.source_layer_id is not None:
        # Remember which version of the source this translation was made from.
        source_revision = db.scalar(
            select(TextLayer.current_revision_id).where(TextLayer.id == layer.source_layer_id)
        )
    revision = TextRevision(
        layer_id=layer.id,
        revision_number=number,
        based_on_revision_id=based_on,
        source_revision_id=source_revision,
        content_original=content,
        content_nfc=normalize.to_nfc(content),
        detected_scripts=scripts.detect(content),
        uncertainty_markup=markup.has_uncertainty(content),
        origin="human_contributor",
        author_user_id=author,
        change_note=change_note,
    )
    db.add(revision)
    db.flush()
    layer.current_revision_id = revision.id
    return revision


def _check_links(db: Session, submission: Submission, body: TextLayerCreateRequest) -> None:
    if body.layer_type not in _LAYERS_FOR_KIND[submission.kind]:
        raise ApiError(422, "layer_not_allowed", "This kind of text does not fit this submission.")
    if body.recording_id is not None:
        recording = db.get(Recording, body.recording_id)
        if recording is None or recording.submission_id != submission.id:
            raise _invalid_link()
        duplicate = select(TextLayer.id).where(
            TextLayer.recording_id == body.recording_id,
            TextLayer.layer_type == "transcription",
            TextLayer.script_code == body.script_code,
        )
    elif body.source_layer_id is not None:
        source = db.get(TextLayer, body.source_layer_id)
        if (
            source is None
            or source.submission_id != submission.id
            or source.layer_type == "translation"
            or source.current_revision_id is None
        ):
            raise _invalid_link()
        if source.language_tag == body.language_tag:
            raise ApiError(422, "same_language", "A translation must be in a different language.")
        duplicate = select(TextLayer.id).where(
            TextLayer.source_layer_id == body.source_layer_id,
            TextLayer.language_tag == body.language_tag,
        )
    else:
        return
    # One transcription per recording and script, one translation per source and language:
    # a retried request must not create a second copy. Later changes are new revisions.
    if db.scalar(duplicate.limit(1)) is not None:
        raise ApiError(409, "layer_exists", "This text already exists; add a revision instead.")


def create_layer(
    db: Session,
    *,
    user: AuthenticatedUser,
    submission_id: uuid.UUID,
    body: TextLayerCreateRequest,
) -> service.LayerView:
    # The lock serialises layer creation for one submission, so duplicate checks hold.
    submission = service.get_owned(db, user, submission_id, for_update=True)
    layer = add_layer(db, submission, user=user, **body.model_dump())
    db.commit()
    return service.layer_view(db, layer)


def add_layer(
    db: Session,
    submission: Submission,
    *,
    user: AuthenticatedUser,
    layer_type: str,
    language_tag: str,
    script_code: str,
    content: str,
    recording_id: uuid.UUID | None = None,
    source_layer_id: uuid.UUID | None = None,
    entry_type: str | None = None,
) -> TextLayer:
    """A new layer and its first revision by `user`, without committing. The caller has
    checked that the user may write on this submission and holds its lock."""
    body = TextLayerCreateRequest(
        layer_type=layer_type,
        recording_id=recording_id,
        source_layer_id=source_layer_id,
        entry_type=entry_type,
        language_tag=language_tag,
        script_code=script_code,
        content=content,
    )
    _check_editable(submission)
    checked = _checked(body.content, body.entry_type)
    _check_links(db, submission, body)
    layer = TextLayer(
        submission_id=submission.id,
        layer_type=body.layer_type,
        recording_id=body.recording_id,
        source_layer_id=body.source_layer_id,
        entry_type=body.entry_type,
        language_tag=body.language_tag,
        script_code=body.script_code,
    )
    db.add(layer)
    db.flush()
    _new_revision(db, layer, number=1, content=checked, author=user.id)
    _text_changed(db, submission)
    return layer


def _visible_layer(
    db: Session, user: AuthenticatedUser, layer_id: uuid.UUID, *, for_update: bool = False
) -> TextLayer:
    query = select(TextLayer).where(TextLayer.id == layer_id)
    if for_update:
        query = query.with_for_update()
    layer = db.scalar(query)
    if layer is None:
        raise _not_found()
    try:
        service.get_visible(db, user, layer.submission_id)
    except ApiError as exc:
        raise _not_found() from exc
    return layer


def get_layer(db: Session, user: AuthenticatedUser, layer_id: uuid.UUID) -> service.LayerView:
    return service.layer_view(db, _visible_layer(db, user, layer_id))


def history(db: Session, user: AuthenticatedUser, layer_id: uuid.UUID) -> list[TextRevision]:
    layer = _visible_layer(db, user, layer_id)
    return list(
        db.scalars(
            select(TextRevision)
            .where(TextRevision.layer_id == layer.id)
            .order_by(TextRevision.revision_number.desc())
        )
    )


def add_revision(
    db: Session,
    *,
    user: AuthenticatedUser,
    layer_id: uuid.UUID,
    body: RevisionCreateRequest,
) -> service.LayerView:
    """Contributors revise their own text while it is a draft and after it is accepted."""
    layer = _visible_layer(db, user, layer_id, for_update=True)
    submission = service.get_owned(db, user, layer.submission_id)
    _check_editable(submission)
    if body.base_revision_id != layer.current_revision_id:
        raise ApiError(
            409, "revision_conflict", "Someone saved a newer version; reload and try again."
        )
    content = _checked(body.content, layer.entry_type)
    latest = db.scalar(
        select(func.max(TextRevision.revision_number)).where(TextRevision.layer_id == layer.id)
    )
    _new_revision(
        db,
        layer,
        number=(latest or 0) + 1,
        content=content,
        author=user.id,
        based_on=body.base_revision_id,
        change_note=body.change_note,
    )
    _text_changed(db, submission)
    db.commit()
    return service.layer_view(db, layer)


def _visible_revision(db: Session, user: AuthenticatedUser, revision_id: uuid.UUID) -> TextRevision:
    revision = db.get(TextRevision, revision_id)
    if revision is None:
        raise ApiError(404, "text_revision_not_found", "Text version not found.")
    try:
        _visible_layer(db, user, revision.layer_id)
    except ApiError as exc:
        raise ApiError(404, "text_revision_not_found", "Text version not found.") from exc
    return revision


def compare(
    db: Session, user: AuthenticatedUser, from_id: uuid.UUID, to_id: uuid.UUID
) -> list[tuple[diff.Op, str]]:
    """What changed from one version of a text to another (either order)."""
    old, new = _visible_revision(db, user, from_id), _visible_revision(db, user, to_id)
    if old.layer_id != new.layer_id:
        raise ApiError(422, "different_layers", "Only versions of the same text can be compared.")
    return diff.diff(old.content_original, new.content_original)
