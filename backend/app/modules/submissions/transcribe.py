"""Listen and write (ADR-035): contributors hear someone else's recording and write what is
said in Devanagari, with optional Hindi and English translations.

A clip is handed out while it has no Devanagari transcription. It is accepted free or prompted
speech (read speech already has the sentence that was read), never the listener's own voice,
and only what the speaker allowed to be public (consents.access.transcription_filter).
The text is saved as a transcription layer of that recording, origin `human_contributor`,
author the listener, unverified, like any other contributed text.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.modules.consents.access import transcription_filter
from app.modules.identity.service import AuthenticatedUser
from app.modules.speakers.models import Speaker
from app.modules.submissions import service, text_layers
from app.modules.submissions.models import Recording, Rendition, Submission, TextLayer
from app.text import scripts

SCRIPT = "Deva"
LANGUAGE = "unr"
MODES = ("free", "prompted")
# Translations people may add, with the script each is written in.
TRANSLATIONS = {"hi": "Deva", "en": "Latn"}


@dataclass(frozen=True)
class Clip:
    recording: Recording
    submission: Submission
    files: list[tuple[Rendition, str]]


def _not_own(user: AuthenticatedUser) -> ColumnElement[bool]:
    own_speaker = exists().where(
        Speaker.id == Submission.speaker_id, Speaker.linked_user_id == user.id
    )
    return (Submission.submitted_by != user.id) & ~own_speaker


def _open(user: AuthenticatedUser) -> Select[Recording, Submission]:
    transcribed = exists().where(
        TextLayer.recording_id == Recording.id,
        TextLayer.layer_type == "transcription",
        TextLayer.script_code == SCRIPT,
    )
    playable = exists().where(
        Rendition.recording_id == Recording.id,
        Rendition.kind.in_([kind.name for kind in service.PLAYBACK_KINDS]),
    )
    return (
        select(Recording, Submission)
        .join(Submission, Submission.id == Recording.submission_id)
        .where(
            Recording.upload_status == "promoted",
            Submission.kind.in_(service.AUDIO_KINDS),
            Submission.recording_mode.in_(MODES),
            transcription_filter(),
            _not_own(user),
            ~transcribed,
            playable,
        )
    )


def _files(db: Session, recording: Recording) -> list[tuple[Rendition, str]]:
    files = []
    for kind in service.PLAYBACK_KINDS:
        rendition = db.scalar(
            select(Rendition)
            .where(Rendition.recording_id == recording.id, Rendition.kind == kind.name)
            .order_by(Rendition.created_at.desc())
            .limit(1)
        )
        if rendition is not None:
            files.append((rendition, kind.content_type))
    return files


def next_clip(db: Session, user: AuthenticatedUser, exclude: Sequence[uuid.UUID] = ()) -> Clip:
    """A random clip that still needs writing down, skipping the ones in `exclude`."""
    query = _open(user)
    if exclude:
        query = query.where(Recording.id.not_in(list(exclude)))
    row = db.execute(query.order_by(func.random()).limit(1)).first()
    if row is None:
        raise ApiError(404, "no_clip_available", "There is nothing to write down right now.")
    recording, submission = row
    return Clip(recording, submission, _files(db, recording))


def _script_checked(content: str, script: str, code: str) -> None:
    detected = scripts.detect(content)
    if not detected or scripts.mismatch(script, detected):
        raise ApiError(422, code, f"This text must be written in {script}.")


def save(
    db: Session,
    *,
    user: AuthenticatedUser,
    recording_id: uuid.UUID,
    transcription: str,
    translations: dict[str, str],
) -> TextLayer:
    """Saves what the listener wrote. 409 `already_transcribed` when someone else was faster."""
    recording = db.get(Recording, recording_id)
    if recording is None:
        raise ApiError(404, "clip_not_found", "This recording cannot be written down.")
    # The submission's lock makes the "no transcription yet" check hold until commit.
    db.execute(
        select(Submission.id).where(Submission.id == recording.submission_id).with_for_update()
    )
    if db.execute(_open(user).where(Recording.id == recording_id)).first() is None:
        transcribed = db.scalar(
            select(TextLayer.id).where(
                TextLayer.recording_id == recording_id,
                TextLayer.layer_type == "transcription",
                TextLayer.script_code == SCRIPT,
            )
        )
        if transcribed is not None:
            raise ApiError(409, "already_transcribed", "Someone has just written this one down.")
        raise ApiError(404, "clip_not_found", "This recording cannot be written down.")
    _script_checked(transcription, SCRIPT, "not_devanagari")
    for language, text in translations.items():
        _script_checked(text, TRANSLATIONS[language], f"translation_{language}_script")

    submission = db.get_one(Submission, recording.submission_id)
    layer = text_layers.add_layer(
        db,
        submission,
        user=user,
        layer_type="transcription",
        recording_id=recording.id,
        language_tag=LANGUAGE,
        script_code=SCRIPT,
        content=transcription,
    )
    for language, text in sorted(translations.items()):
        text_layers.add_layer(
            db,
            submission,
            user=user,
            layer_type="translation",
            source_layer_id=layer.id,
            language_tag=language,
            script_code=TRANSLATIONS[language],
            content=text,
        )
    db.commit()
    return layer
