"""Consent forms and consent records (ADR-012, docs/CONSENT_AND_DATA_GOVERNANCE.md §3).

A change of consent never edits a record: it supersedes the active one with a new record, in
one transaction. Oral consent evidence goes to the restricted consent-evidence bucket and is
never handed out as a URL.
"""

import uuid
from collections.abc import Iterable
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audio_formats import CONTENT_TYPES, SNIFF_BYTES, sniff_audio_container
from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.consents.dev_forms import DEV_FORMS, FORM_CODE, VERSION
from app.modules.consents.models import PERMISSIONS, ConsentForm, ConsentRecord
from app.modules.consents.schemas import ConsentRequest
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.releases import withdrawals as releases_withdrawals
from app.modules.speakers import service as speakers
from app.object_store import Bucket, ObjectStore, ObjectTooLarge, new_key


def current_form(db: Session, settings: Settings, language: str) -> ConsentForm:
    query = (
        select(ConsentForm)
        .where(
            ConsentForm.language == language,
            ConsentForm.retired_at.is_(None),
            ConsentForm.effective_from <= utcnow(),
        )
        .order_by(ConsentForm.effective_from.desc())
        .limit(1)
    )
    if settings.env == "production":
        query = query.where(ConsentForm.is_test_form.is_(False))
    form = db.scalar(query)
    if form is None:
        raise ApiError(
            404, "consent_form_not_found", "No consent form is available in this language."
        )
    return form


def ensure_dev_forms(db: Session) -> list[str]:
    """Adds the test forms that are missing; returns their languages. Caller commits."""
    added = []
    for dev_form in DEV_FORMS:
        exists = db.scalar(
            select(ConsentForm.id).where(
                ConsentForm.form_code == FORM_CODE,
                ConsentForm.version == VERSION,
                ConsentForm.language == dev_form.language,
            )
        )
        if exists is None:
            db.add(
                ConsentForm(
                    form_code=FORM_CODE,
                    version=VERSION,
                    language=dev_form.language,
                    body_markdown=dev_form.body_markdown,
                    text_sha256=dev_form.text_sha256,
                    is_test_form=True,
                )
            )
            added.append(dev_form.language)
    return added


def active_consent(db: Session, speaker_id: uuid.UUID) -> ConsentRecord | None:
    return db.scalar(
        select(ConsentRecord).where(
            ConsentRecord.speaker_id == speaker_id, ConsentRecord.status == "active"
        )
    )


def speakers_with_active_consent(db: Session, speaker_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(speaker_ids)
    if not ids:
        return set()
    return set(
        db.scalars(
            select(ConsentRecord.speaker_id).where(
                ConsentRecord.speaker_id.in_(ids), ConsentRecord.status == "active"
            )
        )
    )


def history(db: Session, user: AuthenticatedUser, speaker_id: uuid.UUID) -> list[ConsentRecord]:
    speaker = speakers.get_visible(db, user, speaker_id)
    return list(
        db.scalars(
            select(ConsentRecord)
            .where(ConsentRecord.speaker_id == speaker.id)
            .order_by(ConsentRecord.obtained_at.desc(), ConsentRecord.id.desc())
        )
    )


def _usable_form(db: Session, settings: Settings, form_id: uuid.UUID) -> ConsentForm:
    form = db.get(ConsentForm, form_id)
    if form is None or form.retired_at is not None:
        raise ApiError(
            422, "consent_form_invalid", "This consent form is not available. Reload the form."
        )
    if form.is_test_form and settings.env == "production":
        raise ApiError(
            422, "test_form_not_allowed", "Test consent forms cannot be used for real data."
        )
    return form


def _check_rules(body: ConsentRequest, settings: Settings, has_evidence: bool) -> None:
    if not body.allow_store_and_review:
        raise ApiError(
            422,
            "store_consent_required",
            "Taking part needs permission to store the recording and have it reviewed.",
        )
    if body.guardian_involved and not settings.allow_minors:
        raise ApiError(422, "minors_not_enabled", "Recordings from minors are not collected yet.")
    if body.method == "oral_recorded" and not has_evidence:
        raise ApiError(
            422, "evidence_required", "Oral consent needs the recording of the consent exchange."
        )
    if body.method != "oral_recorded" and has_evidence:
        raise ApiError(422, "evidence_not_expected", "Only oral consent takes a recording.")


def _store_evidence(
    store: ObjectStore, settings: Settings, speaker_id: uuid.UUID, evidence: BinaryIO
) -> str:
    container = sniff_audio_container(evidence.read(SNIFF_BYTES))
    if container is None:
        raise ApiError(
            422, "evidence_not_audio", "The consent recording is not a recognised audio file."
        )
    evidence.seek(0)
    key = new_key("consent", speaker_id, uuid.uuid4(), suffix=f".{container}")
    try:
        store.put(
            Bucket.CONSENT_EVIDENCE,
            key,
            evidence,
            content_type=CONTENT_TYPES[container],
            max_bytes=settings.consent_evidence_max_bytes,
        )
    except ObjectTooLarge as exc:
        raise ApiError(413, "evidence_too_large", "The consent recording is too large.") from exc
    return key


def record_consent(
    db: Session,
    store: ObjectStore,
    settings: Settings,
    *,
    actor: AuthenticatedUser,
    speaker_id: uuid.UUID,
    body: ConsentRequest,
    evidence: BinaryIO | None,
    context: RequestContext,
) -> ConsentRecord:
    # Locking the speaker serialises concurrent consent changes for the same person.
    speaker = speakers.get_for_action(db, actor, speaker_id, for_update=True)
    form = _usable_form(db, settings, body.consent_form_id)
    _check_rules(body, settings, has_evidence=evidence is not None)

    evidence_key = _store_evidence(store, settings, speaker.id, evidence) if evidence else None
    try:
        previous = active_consent(db, speaker.id)
        if previous is not None:
            previous.status = "superseded"
            db.flush()  # the one-active-record index must see this before the insert
        record = ConsentRecord(
            speaker_id=speaker.id,
            consent_form_id=form.id,
            supersedes_id=previous.id if previous else None,
            method=body.method,
            obtained_by=actor.id,
            guardian_involved=body.guardian_involved,
            guardian_relationship=body.guardian_relationship,
            evidence_object_key=evidence_key,
            paper_reference=body.paper_reference,
            attribution_preference=body.attribution_preference,
            demographics_consented=body.demographics_consented,
            applies_to_past_contributions=body.applies_to_past_contributions,
            notes=body.notes,
            **{permission: getattr(body, permission) for permission in PERMISSIONS},
        )
        db.add(record)
        speakers.set_demographics_consent(speaker, body.demographics_consented)
        if previous is not None:
            db.flush()
            # A narrower answer reaches releases that were already frozen (§3 of
            # docs/DATA_RETENTION_AND_DELETION.md).
            releases_withdrawals.mark_consent_narrowed(
                db,
                store,
                speaker_id=speaker.id,
                actor_id=actor.id,
                now=utcnow(),
                context=context,
            )
        audit.record(
            db,
            action="consent.record",
            context=context,
            actor_user_id=actor.id,
            target_type="speaker",
            target_id=speaker.id,
            details={
                "method": body.method,
                "form_version": form.version,
                "form_language": form.language,
                "supersedes": previous is not None,
                "permissions": {p: getattr(body, p) for p in PERMISSIONS},
                "demographics_consented": body.demographics_consented,
            },
        )
        db.commit()
    except BaseException:
        db.rollback()
        if evidence_key is not None:
            # Do not keep a recording of someone's consent that no record points to.
            store.delete(Bucket.CONSENT_EVIDENCE, evidence_key)
        raise
    return record
