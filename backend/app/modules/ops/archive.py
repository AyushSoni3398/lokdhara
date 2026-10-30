"""The full admin archive (ADR-027): everything the app holds, as one zip.

Unlike a dataset release, nothing is filtered by consent, restriction flags, or hiding: every
row of the data tables, the speakers' names and contacts in plain text, and every original
recording, consent recording and prompt file still stored. Only secrets that would let someone
sign in are left out (password and token hashes, MFA secrets, sessions). What a completed
withdrawal erased is already gone, so the archive cannot contain it.

The tables are read inside the request; the files are read from storage while the zip streams,
so the zip is never held in memory or on disk.
"""

import csv
import io
import json
import uuid
import zipfile
from collections import defaultdict
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
from app.modules.releases.package import csv_cell
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
from app.modules.topics.models import Topic
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
    "topics": Topic,
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
- recordings_overview.csv   one row per recording (and per text-only item) with its speaker,
                        name, consent, prompt, details, file name, quality and current texts,
                        for opening in a spreadsheet. data/*.jsonl stay the exact copy.

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


OVERVIEW_COLUMNS = (
    "submission_id",
    "recording_id",
    "file",
    "submission_status",
    "restriction_flags",
    "upload_status",
    "sent_by",
    "speaker_code",
    "speaker_name",
    "speaker_contact",
    "speaker_village",
    "age_band",
    "gender",
    "first_language",
    "other_languages",
    "speaker_region",
    "demographics_consented",
    "title",
    "kind",
    "content_type",
    "language",
    "dialect_label",
    "area",
    "recording_mode",
    "topics",
    "collection_method",
    "recorded_on",
    "submitted_at",
    "prompt_key",
    "prompt_version",
    "prompt_text",
    "setting",
    "speaker_count",
    "equipment",
    "collection_notes",
    "source",
    "container",
    "codec",
    "sample_rate_hz",
    "channels",
    "bit_depth",
    "duration_seconds",
    "size_bytes",
    "is_lossy_source",
    "sha256_original",
    "quality_flags",
    "consent_status",
    "consent_research",
    "consent_public",
    "consent_ai_training",
    "consent_commercial",
    "guardian_involved",
    "transcription",
    "text",
    "translations",
)


def _texts(db: Session) -> dict[uuid.UUID, dict[str, list[str]]]:
    """Each submission's current texts by layer type; translations as `language: text`."""
    found: dict[uuid.UUID, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    rows = db.execute(
        select(TextLayer, TextRevision)
        .join(TextRevision, TextRevision.id == TextLayer.current_revision_id)
        .order_by(TextLayer.created_at, TextLayer.id)
    )
    for layer, revision in rows:
        text = revision.content_original
        if layer.layer_type == "translation":
            text = f"{layer.language_tag}: {text}"
        found[layer.submission_id][layer.layer_type].append(text)
    return found


def overview_csv(db: Session, identities: list[dict[str, Any]]) -> bytes:
    """recordings_overview.csv: the tables joined, so the archive is usable without code."""
    speakers = {s.id: s for s in db.scalars(select(Speaker))}
    names = {uuid.UUID(row["speaker_id"]): row for row in identities}
    users = {user_id: name for user_id, name in db.execute(select(User.id, User.username))}
    prompts = {p.id: p for p in db.scalars(select(Prompt))}
    consents = {c.id: c for c in db.scalars(select(ConsentRecord))}
    recordings: dict[uuid.UUID, list[Recording]] = defaultdict(list)
    for stored in db.scalars(select(Recording).order_by(Recording.created_at, Recording.id)):
        recordings[stored.submission_id].append(stored)
    texts = _texts(db)

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(OVERVIEW_COLUMNS)
    order = (Submission.created_at, Submission.id)
    for submission in db.scalars(select(Submission).order_by(*order)):
        speaker = speakers[submission.speaker_id]
        identity = names.get(speaker.id, {})
        prompt = prompts.get(submission.prompt_id) if submission.prompt_id else None
        consent = (
            consents.get(submission.consent_record_id) if submission.consent_record_id else None
        )
        context = submission.collection_context or {}
        own = texts.get(submission.id, {})
        common: dict[str, Any] = {
            "submission_id": submission.id,
            "submission_status": submission.status,
            "restriction_flags": submission.restriction_flags,
            "sent_by": users.get(submission.submitted_by),
            "speaker_code": speaker.speaker_code,
            "speaker_name": identity.get("full_name"),
            "speaker_contact": identity.get("contact"),
            "speaker_village": identity.get("village"),
            "age_band": speaker.age_band,
            "gender": speaker.gender_self_described,
            "first_language": speaker.first_language,
            "other_languages": speaker.other_languages,
            "speaker_region": speaker.region_coarse,
            "demographics_consented": speaker.demographics_consented,
            "title": submission.title,
            "kind": submission.kind,
            "content_type": submission.content_type,
            "language": submission.language_tag,
            "dialect_label": submission.dialect_label,
            "area": submission.region_coarse,
            "recording_mode": submission.recording_mode,
            "topics": submission.topics,
            "collection_method": submission.collection_method,
            "recorded_on": submission.recorded_on,
            "submitted_at": submission.submitted_at,
            "prompt_key": prompt.prompt_key if prompt else None,
            "prompt_version": prompt.version if prompt else None,
            "prompt_text": prompt.text if prompt else None,
            "setting": context.get("setting"),
            "speaker_count": context.get("speaker_count"),
            "equipment": context.get("equipment"),
            "collection_notes": context.get("notes"),
            "consent_status": consent.status if consent else None,
            "consent_research": consent.allow_research if consent else None,
            "consent_public": consent.allow_public_access if consent else None,
            "consent_ai_training": consent.allow_ai_training if consent else None,
            "consent_commercial": consent.allow_commercial_use if consent else None,
            "guardian_involved": consent.guardian_involved if consent else None,
            "transcription": " | ".join(own.get("transcription", [])),
            "text": " | ".join(own.get("standalone", [])),
            "translations": " | ".join(own.get("translation", [])),
        }
        found: list[Recording | None] = [*recordings.get(submission.id, [])]
        for recording in found or [None]:
            row = dict(common)
            if recording is not None:
                duration = recording.duration_ms
                row |= {
                    "recording_id": recording.id,
                    "file": f"originals/{recording.id}{_suffix(recording.original_object_key)}",
                    "upload_status": recording.upload_status,
                    "source": recording.recorded_device_hint,
                    "container": recording.detected_container,
                    "codec": recording.detected_codec,
                    "sample_rate_hz": recording.sample_rate_hz,
                    "channels": recording.channels,
                    "bit_depth": recording.bit_depth,
                    "duration_seconds": round(duration / 1000, 3) if duration else None,
                    "size_bytes": recording.size_bytes,
                    "is_lossy_source": recording.is_lossy_source,
                    "sha256_original": recording.sha256_original,
                    "quality_flags": recording.quality_flags,
                }
            writer.writerow([csv_cell(_json_value(row.get(c))) for c in OVERVIEW_COLUMNS])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


PEOPLE_COLUMNS = (
    "speaker_id",
    "speaker_code",
    "account",
    "signed_up_at",
    "speaker_status",
    "age_band",
    "gender",
    "first_language",
    "other_languages",
    "dialect_label",
    "region",
    "demographics_consented",
    "consent_status",
    "consent_given_at",
    "consent_form",
    "consent_method",
    "consent_research",
    "consent_public",
    "consent_ai_training",
    "consent_commercial",
    "attribution",
    "guardian_involved",
    "consent_records",
    "withdrawal_status",
    "withdrawal_received_at",
    "submissions",
    "recordings",
)


def _form_name(form: ConsentForm) -> str:
    return f"{form.form_code}-{form.version}-{form.language}"


def _current_consent(records: list[ConsentRecord]) -> ConsentRecord | None:
    """The latest active consent, or the latest of any status when none is active."""
    active = [r for r in records if r.status == "active"]
    return max(active or records, key=lambda r: r.obtained_at, default=None)


def people_csv(db: Session) -> bytes:
    """people.csv: one row per speaker with what they gave at sign-up and their consent.
    No names or contacts: those are in people_names.csv."""
    users = {u.id: u for u in db.scalars(select(User))}
    forms = {f.id: f for f in db.scalars(select(ConsentForm))}
    consents: dict[uuid.UUID, list[ConsentRecord]] = defaultdict(list)
    for record in db.scalars(select(ConsentRecord)):
        consents[record.speaker_id].append(record)
    withdrawals: dict[uuid.UUID, WithdrawalRequest] = {}
    order = (WithdrawalRequest.received_at, WithdrawalRequest.id)
    for request in db.scalars(select(WithdrawalRequest).order_by(*order)):
        if request.speaker_id is not None:
            withdrawals[request.speaker_id] = request  # the latest wins
    submissions: dict[uuid.UUID, int] = defaultdict(int)
    for speaker_id in db.scalars(select(Submission.speaker_id)):
        submissions[speaker_id] += 1
    recordings: dict[uuid.UUID, int] = defaultdict(int)
    for speaker_id in db.scalars(
        select(Submission.speaker_id).join(Recording, Recording.submission_id == Submission.id)
    ):
        recordings[speaker_id] += 1

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(PEOPLE_COLUMNS)
    for speaker in db.scalars(select(Speaker).order_by(Speaker.created_at, Speaker.id)):
        account = users.get(speaker.linked_user_id) if speaker.linked_user_id else None
        consent = _current_consent(consents[speaker.id])
        withdrawal = withdrawals.get(speaker.id)
        row: dict[str, Any] = {
            "speaker_id": speaker.id,
            "speaker_code": speaker.speaker_code,
            "account": account.username if account else None,
            "signed_up_at": account.created_at if account else None,
            "speaker_status": speaker.status,
            "age_band": speaker.age_band,
            "gender": speaker.gender_self_described,
            "first_language": speaker.first_language,
            "other_languages": speaker.other_languages,
            "dialect_label": speaker.dialect_label,
            "region": speaker.region_coarse,
            "demographics_consented": speaker.demographics_consented,
            "consent_records": len(consents[speaker.id]),
            "withdrawal_status": withdrawal.status if withdrawal else None,
            "withdrawal_received_at": withdrawal.received_at if withdrawal else None,
            "submissions": submissions[speaker.id],
            "recordings": recordings[speaker.id],
        }
        if consent is not None:
            row |= {
                "consent_status": consent.status,
                "consent_given_at": consent.obtained_at,
                "consent_form": _form_name(forms[consent.consent_form_id]),
                "consent_method": consent.method,
                "consent_research": consent.allow_research,
                "consent_public": consent.allow_public_access,
                "consent_ai_training": consent.allow_ai_training,
                "consent_commercial": consent.allow_commercial_use,
                "attribution": consent.attribution_preference,
                "guardian_involved": consent.guardian_involved,
            }
        writer.writerow([csv_cell(_json_value(row.get(c))) for c in PEOPLE_COLUMNS])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


NAMES_COLUMNS = (
    "speaker_id",
    "speaker_code",
    "full_name",
    "contact",
    "village",
    "notes",
    "account",
    "account_display_name",
    "account_email",
    "account_phone",
    "details_updated_at",
)


def people_names_csv(db: Session, identities: list[dict[str, Any]]) -> bytes:
    """people_names.csv: what identifies each speaker, kept apart from people.csv so that
    file can be used without anyone's name. Joined to it by speaker_id or speaker_code."""
    users = {u.id: u for u in db.scalars(select(User))}
    names = {uuid.UUID(row["speaker_id"]): row for row in identities}

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(NAMES_COLUMNS)
    for speaker in db.scalars(select(Speaker).order_by(Speaker.created_at, Speaker.id)):
        account = users.get(speaker.linked_user_id) if speaker.linked_user_id else None
        identity = names.get(speaker.id, {})
        row: dict[str, Any] = {
            "speaker_id": speaker.id,
            "speaker_code": speaker.speaker_code,
            **{field: identity.get(field) for field in IDENTITY_FIELDS},
            "details_updated_at": identity.get("updated_at"),
        }
        if account is not None:
            row |= {
                "account": account.username,
                "account_display_name": account.display_name,
                "account_email": account.email,
                "account_phone": account.phone,
            }
        writer.writerow([csv_cell(_json_value(row.get(c))) for c in NAMES_COLUMNS])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


CONSENT_COLUMNS = (
    "consent_record_id",
    "speaker_id",
    "speaker_code",
    "status",
    "given_at",
    "method",
    "taken_by",
    "consent_form",
    "form_file",
    "store_and_review",
    "research",
    "public",
    "ai_training",
    "commercial",
    "attribution",
    "demographics_consented",
    "applies_to_past_contributions",
    "guardian_involved",
    "guardian_relationship",
    "evidence_file",
    "paper_reference",
    "replaces",
    "notes",
)


def form_file(form: ConsentForm) -> str:
    return f"consent_forms/{_form_name(form)}.md"


def consents_csv(db: Session) -> bytes:
    """consents.csv: every consent ever given, newest last, with the form agreed to.
    A changed consent is a new row that replaces an older one; nothing is overwritten."""
    users = {user_id: name for user_id, name in db.execute(select(User.id, User.username))}
    codes = {s.id: s.speaker_code for s in db.scalars(select(Speaker))}
    forms = {f.id: f for f in db.scalars(select(ConsentForm))}

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CONSENT_COLUMNS)
    order = (ConsentRecord.obtained_at, ConsentRecord.id)
    for record in db.scalars(select(ConsentRecord).order_by(*order)):
        form = forms[record.consent_form_id]
        evidence = record.evidence_object_key
        row: dict[str, Any] = {
            "consent_record_id": record.id,
            "speaker_id": record.speaker_id,
            "speaker_code": codes.get(record.speaker_id),
            "status": record.status,
            "given_at": record.obtained_at,
            "method": record.method,
            "taken_by": users.get(record.obtained_by),
            "consent_form": _form_name(form),
            "form_file": form_file(form),
            "store_and_review": record.allow_store_and_review,
            "research": record.allow_research,
            "public": record.allow_public_access,
            "ai_training": record.allow_ai_training,
            "commercial": record.allow_commercial_use,
            "attribution": record.attribution_preference,
            "demographics_consented": record.demographics_consented,
            "applies_to_past_contributions": record.applies_to_past_contributions,
            "guardian_involved": record.guardian_involved,
            "guardian_relationship": record.guardian_relationship,
            "evidence_file": (
                f"consent_evidence/{record.id}{_suffix(evidence)}" if evidence else None
            ),
            "paper_reference": record.paper_reference,
            "replaces": record.supersedes_id,
            "notes": record.notes,
        }
        writer.writerow([csv_cell(_json_value(row.get(c))) for c in CONSENT_COLUMNS])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


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
    identities = _identities(db, cipher)
    entries["data/speaker_identities.jsonl"] = _jsonl(identities)
    entries["recordings_overview.csv"] = overview_csv(db, identities)
    entries["people.csv"] = people_csv(db)
    entries["people_names.csv"] = people_names_csv(db, identities)
    entries["consents.csv"] = consents_csv(db)
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
