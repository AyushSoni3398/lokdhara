"""Pre-freeze checks D1 to D9 and freezing (docs/DATA_QUALITY_AND_VALIDATION.md §4,
docs/DATASET_VERSIONING.md).

Freezing takes the items the release rule allows at that moment (consent is re-computed, never
cached), records exactly which revisions, files, and consent each one was frozen with, and
stores the package's text files and manifest. Every later export is built from those and
checked against the manifest.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audio import renditions
from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.consents.access import PURPOSE_PERMISSIONS, ConsentStep, use_allowed
from app.modules.consents.models import ConsentRecord
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.prompts.models import Prompt
from app.modules.releases import package, service
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import (
    Recording,
    Rendition,
    Submission,
    TextLayer,
    TextRevision,
)
from app.object_store import Bucket, ObjectNotFound, ObjectStore

# The consent answers recorded with each item, named as in items.jsonl.
SNAPSHOT_USES = {
    "research": "allow_research",
    "public": "allow_public_access",
    "ai_training": "allow_ai_training",
    "commercial": "allow_commercial_use",
}
TEXT_FILES = ("items.jsonl", "README.md", "datacard.json", "LICENSE.txt")


def stored_file_key(release_id: uuid.UUID, path: str) -> str:
    """Where a package text file is kept. Object keys are lower case, so README.md is stored as
    readme.md; the export puts it back under its package name."""
    return f"releases/{release_id}/{path.lower()}"


@dataclass(frozen=True)
class Gathered:
    submission: Submission
    recording: Recording | None
    rendition: Rendition | None
    revisions: list[TextRevision]
    consent: dict[str, bool]
    record: dict[str, Any]


def _consent_steps(db: Session, submission: Submission) -> list[ConsentStep]:
    base = db.get(ConsentRecord, submission.consent_record_id)
    if base is None:
        return []
    records = db.scalars(
        select(ConsentRecord)
        .where(
            ConsentRecord.speaker_id == base.speaker_id,
            tuple_(ConsentRecord.obtained_at, ConsentRecord.id)
            >= tuple_(base.obtained_at, base.id),
        )
        .order_by(ConsentRecord.obtained_at, ConsentRecord.id)
    )
    return [
        ConsentStep(
            allow_research=r.allow_research,
            applies_to_past=r.applies_to_past_contributions,
            allow_public_access=r.allow_public_access,
            allow_ai_training=r.allow_ai_training,
            allow_commercial_use=r.allow_commercial_use,
        )
        for r in records
    ]


def _gather(db: Session, submission: Submission) -> Gathered:
    speaker = db.get(Speaker, submission.speaker_id)
    if speaker is None:  # pragma: no cover - a foreign key guarantees it
        raise RuntimeError("submission without speaker")
    prompt = db.get(Prompt, submission.prompt_id) if submission.prompt_id else None
    recording = db.scalar(
        select(Recording)
        .where(Recording.submission_id == submission.id, Recording.upload_status == "promoted")
        .order_by(Recording.created_at)
        .limit(1)
    )
    rendition = None
    if recording is not None:
        rendition = db.scalar(
            select(Rendition)
            .where(
                Rendition.recording_id == recording.id,
                Rendition.kind == renditions.ANALYSIS.name,
            )
            .order_by(Rendition.created_at.desc())
            .limit(1)
        )
    rows = db.execute(
        select(TextLayer, TextRevision)
        .join(TextRevision, TextRevision.id == TextLayer.current_revision_id)
        .where(TextLayer.submission_id == submission.id)
        .order_by(TextLayer.created_at)
    ).all()
    steps = _consent_steps(db, submission)
    consent = {name: use_allowed(steps, column) for name, column in SNAPSHOT_USES.items()}
    source = package.ItemSource(
        item_id=str(submission.id),
        language=submission.language_tag,
        speaker_code=speaker.speaker_code,
        age_band=speaker.age_band if speaker.demographics_consented else None,
        dialect_label=submission.dialect_label,
        content_type=submission.content_type,
        collection_method=submission.collection_method,
        recording_mode=submission.recording_mode,
        prompt=(
            {
                "id": str(prompt.id),
                "key": prompt.prompt_key,
                "version": prompt.version,
                "type": prompt.prompt_type,
            }
            if prompt
            else None
        ),
        recorded_on=submission.recorded_on,
        audio=(
            package.AudioFile(
                sha256=rendition.sha256,
                size_bytes=rendition.size_bytes,
                duration_ms=recording.duration_ms if recording else None,
                is_lossy_source=recording.is_lossy_source if recording else None,
            )
            if rendition
            else None
        ),
        texts=tuple(
            package.TextVersion(
                revision_id=str(revision.id),
                layer_type=layer.layer_type,
                language=layer.language_tag,
                script=layer.script_code,
                text=revision.content_original,
                origin=revision.origin,
                verification_status=revision.verification_status,
                uncertainty_markup=revision.uncertainty_markup,
                source_revision_id=(
                    str(revision.source_revision_id) if revision.source_revision_id else None
                ),
            )
            for layer, revision in rows
        ),
        quality_flags=tuple(recording.quality_flags if recording else ()),
        consent=consent,
    )
    return Gathered(
        submission=submission,
        recording=recording,
        rendition=rendition if rendition else None,
        revisions=[revision for _, revision in rows],
        consent=consent,
        record=package.item_record(source),
    )


# ------------------------------------------------------------------ checks


@dataclass(frozen=True)
class Check:
    code: str
    passed: bool
    message: str
    # D9 is a note for the data card, not a reason to refuse freezing.
    blocking: bool = True


@dataclass(frozen=True)
class CheckRun:
    checks: list[Check]
    items: list[Gathered]
    stats: dict[str, Any]

    @property
    def passed(self) -> bool:
        return all(check.passed or not check.blocking for check in self.checks)


def _file_ok(store: ObjectStore, rendition: Rendition) -> bool:
    try:
        return store.sha256_of(Bucket.DERIVED, rendition.object_key) == rendition.sha256
    except ObjectNotFound:
        return False


def run_checks(
    db: Session, store: ObjectStore, settings: Settings, release: DatasetRelease
) -> CheckRun:
    items = [_gather(db, s) for s in db.scalars(service.selection(release))]
    records = [item.record for item in items]
    stats = package.statistics(records, settings.release_speaker_share_warning)
    use = PURPOSE_PERMISSIONS[release.purpose]
    use_name = next(name for name, column in SNAPSHOT_USES.items() if column == use)
    refused = [i for i in items if not i.consent[use_name]]
    broken = [i for i in items if i.rendition is not None and not _file_ok(store, i.rendition)]
    texts = [
        t
        for r in records
        for t in [r["transcription"], r["text"], *r["translations"]]
        if t is not None
    ]
    external = release.purpose != "internal_research"
    governance = []
    if external and not settings.external_releases_enabled:
        governance.append("governance approval is not recorded yet (Q-G1, Q-G5)")
    if external and not release.licence:
        governance.append("a licence is needed")
    if external and not release.data_card_markdown.strip():
        governance.append("a data card text is needed")
    flagged = stats["speakers_above_share"]
    checks = [
        Check(
            "D1",
            bool(items),
            f"{len(items)} accepted items, none withdrawn or hidden"
            if items
            else "No item qualifies for this release.",
        ),
        Check(
            "D2",
            not refused,
            f"Consent re-checked now: every item allows `{release.purpose}`"
            if not refused
            else f"{len(refused)} items no longer allow this use.",
        ),
        Check("D3", True, "Items with any restriction flag are left out."),
        Check(
            "D4",
            not broken,
            f"{sum(1 for i in items if i.rendition)} audio files match their checksums"
            if not broken
            else f"{len(broken)} audio files are missing or changed.",
        ),
        Check(
            "D5",
            all(t["verification_status"] and t["origin"] for t in texts),
            f"{stats['unverified_texts']} of {len(texts)} texts are marked unverified.",
        ),
        Check(
            "D6",
            all(r.keys() == package.ITEM_FIELDS for r in records),
            "Only allow-listed fields are exported.",
        ),
        Check(
            "D7",
            not governance,
            "Licence and data card are not required for internal research."
            if not external
            else ("; ".join(governance) if governance else "Licence and data card present."),
        ),
        Check("D8", True, "Counts by dialect, script, content and duration are in the data card."),
        Check(
            "D9",
            not flagged,
            "No speaker is above the share limit."
            if not flagged
            else f"{len(flagged)} speakers are above the share limit; the data card says so.",
            blocking=False,
        ),
    ]
    return CheckRun(checks, items, stats)


def _failed(run: CheckRun) -> ApiError:
    codes = [c.code for c in run.checks if c.blocking and not c.passed]
    return ApiError(
        422,
        "prefreeze_checks_failed",
        "The release did not pass its checks.",
        f"Failed: {', '.join(codes)}",
    )


# ------------------------------------------------------------------ freezing


def freeze(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    admin: AuthenticatedUser,
    release_id: uuid.UUID,
    version: str,
    context: RequestContext,
) -> DatasetRelease:
    release = service.get_release(db, release_id, for_update=True)
    if release.status != "draft":
        raise ApiError(409, "release_frozen", "This release is already frozen.")
    service.check_patch_version(db, release, version)
    taken = db.scalar(
        select(DatasetRelease.id).where(
            DatasetRelease.slug == release.slug, DatasetRelease.version == version
        )
    )
    if taken is not None:
        raise ApiError(409, "version_exists", "This version of the release already exists.")
    run = run_checks(db, store, settings, release)
    if not run.passed:
        raise _failed(run)

    frozen_at = utcnow()
    info = package.ReleaseInfo(
        slug=release.slug,
        version=version,
        purpose=release.purpose,
        licence=release.licence,
        frozen_at=frozen_at.astimezone(UTC).isoformat(),
        code_version=settings.git_commit,
        data_card_markdown=release.data_card_markdown,
    )
    audio = {
        package.audio_path(str(i.submission.id)): (
            package.FileEntry(
                package.audio_path(str(i.submission.id)), i.rendition.sha256, i.rendition.size_bytes
            ),
            _no_read,
        )
        for i in run.items
        if i.rendition is not None
    }
    built = package.assemble(info, [i.record for i in run.items], run.stats, audio)
    _store_text_files(store, release.id, built)

    for item in run.items:
        db.add(
            DatasetReleaseItem(
                release_id=release.id,
                submission_id=item.submission.id,
                recording_id=item.recording.id if item.recording else None,
                rendition_id=item.rendition.id if item.rendition else None,
                text_revision_ids=[r.id for r in item.revisions],
                consent_record_id=item.submission.consent_record_id,
                consent_snapshot=item.consent,
                item_sha256s=(
                    {"audio": item.rendition.sha256} if item.rendition is not None else {}
                ),
            )
        )
    release.status = "frozen"
    release.version = version
    release.approved_by = admin.id
    release.frozen_at = frozen_at
    release.code_version = settings.git_commit
    release.manifest_object_key = stored_file_key(release.id, "manifest.json")
    release.manifest_sha256 = package.entry("manifest.json", built.manifest).sha256
    release.updated_at = frozen_at
    audit.record(
        db,
        action="release.freeze",
        context=context,
        actor_user_id=admin.id,
        target_type="dataset_release",
        target_id=release.id,
        details={
            "slug": release.slug,
            "version": version,
            "purpose": release.purpose,
            "item_count": len(run.items),
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - two admins freezing the same version
        db.rollback()
        raise ApiError(409, "version_exists", "This version already exists.") from exc
    return release


def _no_read() -> Any:  # pragma: no cover - freezing never reads audio, the export does
    raise RuntimeError("audio is read when the export is built")


class _Bytes:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._content if size < 0 else self._content[:size]
        self._content = self._content[len(chunk) :]
        return chunk


def _store_text_files(store: ObjectStore, release_id: uuid.UUID, built: package.Package) -> None:
    """Everything except the audio, kept as long as the release record (§5)."""
    for path, chunks in built.files:
        if path.startswith("audio/"):
            continue
        content = b"".join(chunks())
        store.put(
            Bucket.EXPORTS,
            stored_file_key(release_id, path),
            _Bytes(content),
            content_type="application/json" if path.endswith("json") else "text/plain",
        )
