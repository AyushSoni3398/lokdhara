"""The full admin archive (ADR-027): everything the app holds, as one zip.

Unlike a dataset release, nothing is filtered by consent, restriction flags, or hiding: every
row of the data tables, the speakers' names and contacts in plain text, and every original
recording, consent recording and prompt file still stored. Only secrets that would let someone
sign in are left out (password and token hashes, MFA secrets, sessions). What a completed
withdrawal erased is already gone, so the archive cannot contain it.

The tables are read inside the request; the files are read from storage while the zip streams,
so the zip is never held in memory or on disk.
"""

import json
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base
from app.modules.audit import service as audit
from app.modules.audit.models import AuditEvent
from app.modules.audit.service import RequestContext
from app.modules.consents.models import ConsentForm, ConsentRecord, WithdrawalRequest
from app.modules.identity.models import User, UserRole
from app.modules.identity.service import AuthenticatedUser
from app.modules.prompts.models import Prompt
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem, ExportRequest
from app.modules.reports.models import Report
from app.modules.review.models import ReviewEvent
from app.modules.speakers.crypto import IdentityCipher
from app.modules.speakers.models import Speaker, SpeakerIdentity
from app.modules.speakers.service import IDENTITY_FIELDS
from app.modules.submissions.models import (
    Recording,
    RelatedItem,
    Rendition,
    Submission,
    TextLayer,
    TextRevision,
)
from app.object_store import Bucket, ObjectNotFound, ObjectStore

# File name in the zip -> table. Each line of a file is one row, every column but those below.
TABLES: dict[str, type[Base]] = {
    "users": User,
    "user_roles": UserRole,
    "speakers": Speaker,
    "consent_forms": ConsentForm,
    "consent_records": ConsentRecord,
    "withdrawal_requests": WithdrawalRequest,
    "prompts": Prompt,
    "submissions": Submission,
    "related_items": RelatedItem,
    "recordings": Recording,
    "renditions": Rendition,
    "text_layers": TextLayer,
    "text_revisions": TextRevision,
    "review_events": ReviewEvent,
    "reports": Report,
    "dataset_releases": DatasetRelease,
    "dataset_release_items": DatasetReleaseItem,
    "export_requests": ExportRequest,
    "audit_events": AuditEvent,
}
# Sign-in secrets; never exported.
LEFT_OUT = {"users": frozenset({"password_hash"})}
MIN_REASON_LENGTH = 10

README = """Lokdhara full archive
=====================

Made {made_at} by {admin} for this reason:
{reason}

This zip holds EVERYTHING the app stores, without the consent, restriction or withdrawal
filters of a dataset release:

- data/*.jsonl          one row per line, one file per table
- data/speaker_identities.jsonl   speakers' names, contacts and villages IN PLAIN TEXT
- originals/            every original recording, named <recording id>.<format>
- consent_evidence/     recorded oral consents, named <consent record id>.<format>
- prompts/              prompt images and audio, named <prompt id>-image|audio.<format>
- files.jsonl           which stored file each entry came from, and any that were missing

It includes recordings marked culturally restricted, hidden after a report, waiting for a
withdrawal, and recordings whose speaker did not agree to research, public or AI use. Look at
submissions.restriction_flags, submissions.status, consent_records and withdrawal_requests
before using anything.

Keep this file encrypted and private. Do not share it. If a speaker later withdraws, the app
deletes its own copies, but it cannot reach this one: delete their data from your copies too.
"""


@dataclass(frozen=True)
class ArchiveFile:
    bucket: Bucket
    object_key: str
    name: str


@dataclass(frozen=True)
class Archive:
    entries: dict[str, bytes]
    files: list[ArchiveFile]


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return None  # only ciphertext and secrets are stored as bytes
    return value


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(row, ensure_ascii=False, default=_json_value) for row in rows)
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _rows(db: Session, name: str, model: type[Base]) -> list[dict[str, Any]]:
    left_out = LEFT_OUT.get(name, frozenset())
    columns = [c for c in model.__mapper__.column_attrs if c.key not in left_out]
    order = list(model.__mapper__.primary_key)
    return [
        {c.key: _json_value(getattr(row, c.key)) for c in columns}
        for row in db.scalars(select(model).order_by(*order))
    ]


def _identities(db: Session, cipher: IdentityCipher) -> list[dict[str, Any]]:
    rows = []
    for identity in db.scalars(select(SpeakerIdentity).order_by(SpeakerIdentity.speaker_id)):
        row: dict[str, Any] = {"speaker_id": str(identity.speaker_id)}
        for field in IDENTITY_FIELDS:
            sealed: bytes | None = getattr(identity, f"{field}_enc")
            row[field] = (
                cipher.decrypt(identity.speaker_id, field, sealed, identity.key_version)
                if sealed is not None
                else None
            )
        row["updated_at"] = identity.updated_at.isoformat()
        rows.append(row)
    return rows


def _suffix(key: str) -> str:
    return PurePosixPath(key).suffix


def _files(db: Session) -> list[ArchiveFile]:
    files = [
        ArchiveFile(Bucket.ORIGINALS, key, f"originals/{rid}{_suffix(key)}")
        for rid, key in db.execute(
            select(Recording.id, Recording.original_object_key).order_by(Recording.id)
        )
    ]
    files += [
        ArchiveFile(Bucket.CONSENT_EVIDENCE, key, f"consent_evidence/{cid}{_suffix(key)}")
        for cid, key in db.execute(
            select(ConsentRecord.id, ConsentRecord.evidence_object_key)
            .where(ConsentRecord.evidence_object_key.is_not(None))
            .order_by(ConsentRecord.id)
        )
        if key
    ]
    for prompt in db.scalars(select(Prompt).order_by(Prompt.id)):
        for kind, key in (
            ("image", prompt.image_object_key),
            ("audio", prompt.prompt_audio_object_key),
        ):
            if key:
                name = f"prompts/{prompt.id}-{kind}{_suffix(key)}"
                files.append(ArchiveFile(Bucket.DERIVED, key, name))
    return files


def collect(
    db: Session,
    cipher: IdentityCipher,
    *,
    admin: AuthenticatedUser,
    reason: str,
    made_at: datetime,
    context: RequestContext,
) -> Archive:
    """Reads every table and records who took the archive and why, before anything is sent."""
    reason = reason.strip()
    entries = {
        "README.txt": README.format(
            made_at=made_at.isoformat(timespec="seconds"), admin=admin.user.username, reason=reason
        ).encode("utf-8")
    }
    for name, model in TABLES.items():
        entries[f"data/{name}.jsonl"] = _jsonl(_rows(db, name, model))
    entries["data/speaker_identities.jsonl"] = _jsonl(_identities(db, cipher))
    files = _files(db)
    audit.record(
        db,
        action="archive.download",
        context=context,
        actor_user_id=admin.id,
        details={"reason": reason, "files": len(files)},
    )
    db.commit()
    return Archive(entries, files)


class _Pipe:
    """A write-only file the zip writes into. Without tell() or seek(), zipfile writes data
    descriptors instead of going back, so the zip can be sent while it is written."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def take(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


def zip_chunks(store: ObjectStore, contents: Archive) -> Iterator[bytes]:
    """The zip's bytes, written while they are sent."""
    pipe = _Pipe()
    listing = []
    with zipfile.ZipFile(pipe, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in contents.entries.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        yield pipe.take()
        for file in contents.files:
            try:
                chunks = store.open(file.bucket, file.object_key)
                first = next(chunks, b"")
            except ObjectNotFound:
                stored = False
            else:
                stored = True
                # Audio and images are already compressed.
                with archive.open(file.name, "w", force_zip64=True) as entry:
                    entry.write(first)
                    for chunk in chunks:
                        entry.write(chunk)
                        yield pipe.take()
                yield pipe.take()
            listing.append(
                {
                    "name": file.name,
                    "bucket": str(file.bucket),
                    "object_key": file.object_key,
                    "stored": stored,
                }
            )
        archive.writestr("files.jsonl", _jsonl(listing), compress_type=zipfile.ZIP_DEFLATED)
    yield pipe.take()
