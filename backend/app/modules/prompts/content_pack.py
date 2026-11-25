"""The prompt library's starting content, kept as files instead of in the code (ADR-036).

`backend/content/prompts/prompts.json` lists read-speech texts, pictures, and situations;
pictures sit next to it in `images/`. `load-prompts` copies them into the database: each prompt
becomes a row in `prompts`, and each picture goes to object storage with its key on the row.
After that the database is the only place the app reads prompts from; the files are just the
team's editable source, and loading again only adds prompts whose key is new.
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.audit import service as audit
from app.modules.prompts.models import Prompt
from app.modules.prompts.schemas import PromptCreateRequest
from app.modules.prompts.service import _Media
from app.object_store import ObjectStore

DEFAULT_PACK = Path(__file__).resolve().parents[3] / "content" / "prompts" / "prompts.json"


class PackPrompt(PromptCreateRequest):
    image: str | None = Field(default=None, pattern=r"^images/[a-z0-9-]+\.(png|jpg|webp)$")
    note: str | None = None  # for the people editing the file; not stored


class Pack(BaseModel):
    about: str | None = None
    prompts: list[PackPrompt]
    retire: list[str] = Field(default_factory=list)


class PackError(Exception):
    pass


@dataclass
class LoadResult:
    added: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


def read_pack(path: Path) -> Pack:
    try:
        pack = Pack.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise PackError(f"{path}: {exc}") from exc
    keys = [p.prompt_key for p in pack.prompts]
    if len(keys) != len(set(keys)):
        raise PackError(f"{path}: a prompt key is listed twice")
    for prompt in pack.prompts:
        if (prompt.prompt_type == "image") != (prompt.image is not None):
            raise PackError(f"{prompt.prompt_key}: image prompts need a picture, others none")
        if prompt.image and not (path.parent / prompt.image).is_file():
            raise PackError(f"{prompt.prompt_key}: picture {prompt.image} is missing")
    return pack


def load_pack(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    pack_path: Path,
    *,
    actor_id: uuid.UUID,
    approve: bool,
) -> LoadResult:
    """Adds the pack's prompts whose key is not in the database yet (as drafts, or approved when
    `approve`) and retires the keys under `retire`. The caller commits. If loading fails, the
    pictures it stored are removed again."""
    pack = read_pack(pack_path)
    result = LoadResult()
    media = _Media(store, settings)
    try:
        for entry in pack.prompts:
            if db.scalar(select(Prompt.id).where(Prompt.prompt_key == entry.prompt_key).limit(1)):
                continue
            image_key = None
            if entry.image:
                with (pack_path.parent / entry.image).open("rb") as picture:
                    image_key = media.image(picture)
            prompt = Prompt(
                **entry.model_dump(exclude={"image", "note"}),
                version=1,
                image_object_key=image_key,
                status="approved" if approve else "draft",
                approved_by=actor_id if approve else None,
                created_by=actor_id,
            )
            db.add(prompt)
            db.flush()
            _audit(db, "prompt.load", actor_id, prompt)
            result.added.append(entry.prompt_key)
        for key in pack.retire:
            for prompt in db.scalars(
                select(Prompt).where(Prompt.prompt_key == key, Prompt.status != "retired")
            ):
                if prompt.approved_by is None:
                    prompt.approved_by = actor_id
                prompt.status = "retired"
                _audit(db, "prompt.retire", actor_id, prompt)
                if key not in result.retired:
                    result.retired.append(key)
        db.flush()
    except BaseException:
        media.discard()
        raise
    return result


def _audit(db: Session, action: str, actor_id: uuid.UUID, prompt: Prompt) -> None:
    audit.record(
        db,
        action=action,
        context=None,
        actor_user_id=actor_id,
        actor_type="system",
        target_type="prompt",
        target_id=prompt.id,
        details={"prompt_key": prompt.prompt_key, "version": prompt.version, "via": "load-prompts"},
    )
