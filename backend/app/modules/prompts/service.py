"""The prompt library for prompted and read speech (ADR-018, docs/RECORDING_MODES.md).

Prompts are versioned: editing creates a new draft version, and recordings keep pointing at the
exact version they used. Only approved prompts are shown to contributors. Images and spoken
prompts are team-made media in the derived bucket, served through short-lived signed URLs.
"""

import io
import secrets
import uuid
from collections.abc import Callable
from typing import BinaryIO

from sqlalchemy import any_, func, select, update
from sqlalchemy.orm import Session

from app.audio_formats import CONTENT_TYPES as AUDIO_TYPES
from app.audio_formats import sniff_audio_container
from app.config import Settings
from app.errors import ApiError
from app.image_formats import CONTENT_TYPES as IMAGE_TYPES
from app.image_formats import sniff_image
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser
from app.modules.prompts.dev_images import draw_png
from app.modules.prompts.dev_prompts import DEV_PROMPTS, SOURCE
from app.modules.prompts.models import Prompt
from app.modules.prompts.schemas import PromptCreateRequest, PromptVersionRequest
from app.object_store import Bucket, ObjectStore, ObjectTooLarge, new_key

STAFF_ROLES = ("reviewer", "admin")
_SNIFF_BYTES = 16
_MAX_EXCLUDED = 100


def _not_found() -> ApiError:
    return ApiError(404, "prompt_not_found", "Prompt not found.")


# ------------------------------------------------------------------ media


def media_content_type(key: str) -> str:
    extension = key.rsplit(".", 1)[-1]
    return IMAGE_TYPES.get(extension) or AUDIO_TYPES[extension]


def _store_media(
    store: ObjectStore,
    stream: BinaryIO,
    *,
    sniff: Callable[[bytes], str | None],
    content_types: dict[str, str],
    max_bytes: int,
    code: str,
) -> str:
    extension = sniff(stream.read(_SNIFF_BYTES))
    if extension is None:
        raise ApiError(422, f"{code}_unsupported", f"The {code} file type is not supported.")
    stream.seek(0)
    key = new_key("prompts", uuid.uuid4(), suffix=f".{extension}")
    try:
        store.put(
            Bucket.DERIVED,
            key,
            stream,
            content_type=content_types[extension],
            max_bytes=max_bytes,
        )
    except ObjectTooLarge as exc:
        raise ApiError(413, f"{code}_too_large", f"The {code} file is too large.") from exc
    return key


class _Media:
    """Uploads media for one request and removes it again if the request fails."""

    def __init__(self, store: ObjectStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings
        self.stored: list[str] = []

    def image(self, stream: BinaryIO) -> str:
        key = _store_media(
            self._store,
            stream,
            sniff=sniff_image,
            content_types=IMAGE_TYPES,
            max_bytes=self._settings.prompt_image_max_bytes,
            code="image",
        )
        self.stored.append(key)
        return key

    def audio(self, stream: BinaryIO) -> str:
        key = _store_media(
            self._store,
            stream,
            sniff=sniff_audio_container,
            content_types=AUDIO_TYPES,
            max_bytes=self._settings.prompt_audio_max_bytes,
            code="audio",
        )
        self.stored.append(key)
        return key

    def discard(self) -> None:
        for key in self.stored:
            self._store.delete(Bucket.DERIVED, key)


# ------------------------------------------------------------------ library (staff)


def create_prompt(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    actor: AuthenticatedUser,
    body: PromptCreateRequest,
    image: BinaryIO | None,
    audio: BinaryIO | None,
    context: RequestContext,
) -> Prompt:
    if (body.prompt_type == "image") != (image is not None):
        raise ApiError(
            422, "image_mismatch", "Image prompts need an image, and only they take one."
        )
    if db.scalar(select(Prompt.id).where(Prompt.prompt_key == body.prompt_key).limit(1)):
        raise ApiError(409, "prompt_key_taken", "A prompt with this key already exists.")

    media = _Media(store, settings)
    try:
        prompt = Prompt(
            **body.model_dump(),
            version=1,
            image_object_key=media.image(image) if image else None,
            prompt_audio_object_key=media.audio(audio) if audio else None,
            created_by=actor.id,
        )
        db.add(prompt)
        db.flush()
        _audit(db, "prompt.create", actor, prompt, context)
        db.commit()
    except BaseException:
        db.rollback()
        media.discard()
        raise
    return prompt


def new_version(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    actor: AuthenticatedUser,
    prompt_id: uuid.UUID,
    body: PromptVersionRequest,
    image: BinaryIO | None,
    audio: BinaryIO | None,
    context: RequestContext,
) -> Prompt:
    base = db.get(Prompt, prompt_id)
    if base is None:
        raise _not_found()
    if image is not None and base.prompt_type != "image":
        raise ApiError(
            422, "image_mismatch", "Image prompts need an image, and only they take one."
        )
    # Serialise version numbering for this prompt key.
    db.execute(select(Prompt.id).where(Prompt.prompt_key == base.prompt_key).with_for_update())
    latest = db.scalar(select(func.max(Prompt.version)).where(Prompt.prompt_key == base.prompt_key))
    changes = body.model_dump(exclude_unset=True)
    fields = {
        name: changes.get(name, getattr(base, name))
        for name in ("text", "text_language_tag", "script_code", "source_and_licence", "topic_tags")
    }
    try:
        checked = PromptCreateRequest(
            prompt_key=base.prompt_key, prompt_type=base.prompt_type, **fields
        )
    except ValueError as exc:
        raise ApiError(422, "prompt_invalid", "This version is missing required fields.") from exc

    media = _Media(store, settings)
    try:
        prompt = Prompt(
            **checked.model_dump(),
            version=(latest or 0) + 1,
            image_object_key=media.image(image) if image else base.image_object_key,
            prompt_audio_object_key=(media.audio(audio) if audio else base.prompt_audio_object_key),
            created_by=actor.id,
        )
        db.add(prompt)
        db.flush()
        _audit(db, "prompt.new_version", actor, prompt, context, based_on=str(base.id))
        db.commit()
    except BaseException:
        db.rollback()
        media.discard()
        raise
    return prompt


def approve(
    db: Session, *, actor: AuthenticatedUser, prompt_id: uuid.UUID, context: RequestContext
) -> Prompt:
    prompt = db.scalar(select(Prompt).where(Prompt.id == prompt_id).with_for_update())
    if prompt is None:
        raise _not_found()
    if prompt.status != "draft":
        raise ApiError(409, "prompt_not_draft", "Only draft prompts can be approved.")
    # One approved version per prompt key: approving a new version retires the old one.
    db.execute(
        update(Prompt)
        .where(Prompt.prompt_key == prompt.prompt_key, Prompt.status == "approved")
        .values(status="retired")
    )
    prompt.status = "approved"
    prompt.approved_by = actor.id
    _audit(db, "prompt.approve", actor, prompt, context)
    db.commit()
    return prompt


def retire(
    db: Session, *, actor: AuthenticatedUser, prompt_id: uuid.UUID, context: RequestContext
) -> Prompt:
    prompt = db.scalar(select(Prompt).where(Prompt.id == prompt_id).with_for_update())
    if prompt is None:
        raise _not_found()
    if prompt.status == "retired":
        raise ApiError(409, "prompt_retired", "This prompt is already retired.")
    if prompt.approved_by is None:
        prompt.approved_by = actor.id  # the database requires a decision-maker for non-drafts
    prompt.status = "retired"
    _audit(db, "prompt.retire", actor, prompt, context)
    db.commit()
    return prompt


def list_prompts(
    db: Session, *, status: str | None, prompt_type: str | None, limit: int
) -> list[Prompt]:
    query = select(Prompt).order_by(Prompt.prompt_key, Prompt.version.desc()).limit(limit)
    if status:
        query = query.where(Prompt.status == status)
    if prompt_type:
        query = query.where(Prompt.prompt_type == prompt_type)
    return list(db.scalars(query))


def _audit(
    db: Session,
    action: str,
    actor: AuthenticatedUser,
    prompt: Prompt,
    context: RequestContext,
    **extra: str,
) -> None:
    audit.record(
        db,
        action=action,
        context=context,
        actor_user_id=actor.id,
        target_type="prompt",
        target_id=prompt.id,
        details={"prompt_key": prompt.prompt_key, "version": prompt.version, **extra},
    )


def ensure_dev_prompts(
    db: Session, store: ObjectStore, settings: Settings, admin_id: uuid.UUID
) -> int:
    """Adds missing approved test prompts; returns how many. Caller commits."""
    added = 0
    for dev in DEV_PROMPTS:
        if db.scalar(select(Prompt.id).where(Prompt.prompt_key == dev.prompt_key).limit(1)):
            continue
        image_key = (
            _Media(store, settings).image(io.BytesIO(draw_png(dev.image))) if dev.image else None
        )
        db.add(
            Prompt(
                prompt_key=dev.prompt_key,
                version=1,
                prompt_type=dev.prompt_type,
                text=dev.text,
                text_language_tag="hi",
                script_code=dev.script_code,
                source_and_licence=SOURCE,
                topic_tags=list(dev.topic_tags),
                image_object_key=image_key,
                status="approved",
                approved_by=admin_id,
                created_by=admin_id,
            )
        )
        added += 1
    return added


# ------------------------------------------------------------------ recording (contributors)


# Which prompt types each recording mode answers (docs/RECORDING_MODES.md).
_MODE_TYPES = {"prompted": ("image", "situation"), "read": ("read_sentence",)}


def get_for_recording(db: Session, prompt_id: uuid.UUID, recording_mode: str) -> Prompt:
    """The prompt a new recording answers: approved, and of a type that fits the mode."""
    prompt = db.get(Prompt, prompt_id)
    if prompt is None or prompt.status == "draft":
        raise _not_found()
    if prompt.status == "retired":
        raise ApiError(409, "prompt_retired", "This prompt is no longer used.")
    if prompt.prompt_type not in _MODE_TYPES.get(recording_mode, ()):
        raise ApiError(422, "prompt_mismatch", "This prompt does not fit the recording mode.")
    return prompt


def recorded_prompt(db: Session, prompt_id: uuid.UUID) -> Prompt:
    """The exact version a submission used, whatever its status is now."""
    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise _not_found()
    return prompt


def get_prompt(db: Session, user: AuthenticatedUser, prompt_id: uuid.UUID) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None or (prompt.status != "approved" and not user.has_role(*STAFF_ROLES)):
        raise _not_found()
    return prompt


def next_prompt(
    db: Session, *, prompt_type: str, script_code: str | None, exclude: list[uuid.UUID]
) -> Prompt:
    """A random approved prompt, balanced by topic: first a topic, then a prompt within it, so
    a topic with many prompts does not crowd out the others."""
    if len(exclude) > _MAX_EXCLUDED:
        exclude = exclude[-_MAX_EXCLUDED:]
    conditions = [Prompt.status == "approved", Prompt.prompt_type == prompt_type]
    if script_code is not None:
        conditions.append(Prompt.script_code == script_code)
    if exclude:
        conditions.append(Prompt.id.not_in(exclude))

    topics = sorted(
        db.scalars(select(func.unnest(Prompt.topic_tags)).where(*conditions).distinct()).all()
    )
    untagged = db.scalar(
        select(Prompt.id).where(*conditions, func.cardinality(Prompt.topic_tags) == 0).limit(1)
    )
    buckets: list[str | None] = [*topics, *([None] if untagged else [])]
    if not buckets:
        raise ApiError(404, "no_prompt_available", "There are no more prompts of this kind.")
    topic = secrets.choice(buckets)
    if topic is None:
        conditions.append(func.cardinality(Prompt.topic_tags) == 0)
    else:
        conditions.append(any_(Prompt.topic_tags) == topic)
    candidates = list(db.scalars(select(Prompt.id).where(*conditions)))
    chosen = db.get(Prompt, secrets.choice(candidates))
    assert chosen is not None  # noqa: S101 - just selected under the same conditions
    return chosen


def signed_media_url(store: ObjectStore, settings: Settings, key: str | None) -> str | None:
    if key is None:
        return None
    return store.signed_url(
        Bucket.DERIVED,
        key,
        ttl_seconds=settings.signed_url_ttl_seconds,
        content_type=media_content_type(key),
    )
