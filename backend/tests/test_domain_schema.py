"""Database-level rules for the domain tables (migrations 0004 to 0007, 0012 for reports, and
0013 for dataset releases).

The application will enforce these too; the database is the last line of defence.
"""

import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.consents.models import ConsentForm, ConsentRecord
from app.modules.prompts.models import Prompt
from app.modules.releases.models import DatasetRelease, DatasetReleaseItem, ExportRequest
from app.modules.reports.models import Report
from app.modules.review.models import ReviewEvent
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import (
    Recording,
    Rendition,
    Submission,
    TextLayer,
    TextRevision,
)
from tests.conftest import MakeUser, requires_postgres

pytestmark = requires_postgres

SHA = "a" * 64
FORM_BODY = "TEST CONSENT FORM. Not for real use."


@dataclass
class World:
    contributor: uuid.UUID
    reviewer: uuid.UUID
    speaker: Speaker
    form: ConsentForm
    consent: ConsentRecord


def _speaker(
    db: Session, created_by: uuid.UUID, code: str = "SPK-7Q3M9", **extra: object
) -> Speaker:
    speaker = Speaker(speaker_code=code, created_by=created_by, **extra)
    db.add(speaker)
    db.flush()
    return speaker


def _consent(
    db: Session, world_speaker: Speaker, form: ConsentForm, by: uuid.UUID, **extra: object
) -> ConsentRecord:
    values: dict[str, object] = {
        "speaker_id": world_speaker.id,
        "consent_form_id": form.id,
        "method": "in_app",
        "obtained_by": by,
        "guardian_involved": False,
        "allow_store_and_review": True,
    }
    values.update(extra)
    record = ConsentRecord(**values)
    db.add(record)
    db.flush()
    return record


@pytest.fixture
def world(db: Session, make_user: MakeUser) -> World:
    contributor = make_user("asha", "contributor").id
    reviewer = make_user("ravi", "reviewer").id
    speaker = _speaker(db, contributor)
    form = ConsentForm(
        form_code="LKD-CONSENT",
        version="0.1-test",
        language="hi",
        text_sha256=hashlib.sha256(FORM_BODY.encode()).hexdigest(),
        body_markdown=FORM_BODY,
    )
    db.add(form)
    db.flush()
    consent = _consent(db, speaker, form, contributor)
    db.commit()
    return World(contributor, reviewer, speaker, form, consent)


def _submission(db: Session, world: World, **extra: object) -> Submission:
    values: dict[str, object] = {
        "client_submission_id": uuid.uuid4(),
        "submitted_by": world.contributor,
        "speaker_id": world.speaker.id,
        "consent_record_id": world.consent.id,
        "kind": "audio",
        "content_type": "story",
        "recording_mode": "free",
        "collection_method": "self_recorded",
    }
    values.update(extra)
    submission = Submission(**values)
    db.add(submission)
    db.flush()
    return submission


def _new_recording(submission: Submission, **extra: object) -> Recording:
    return Recording(
        submission_id=submission.id,
        original_object_key=f"originals/{uuid.uuid4()}.webm",
        sha256_original=SHA,
        size_bytes=1000,
        **extra,
    )


def _recording(db: Session, submission: Submission, **extra: object) -> Recording:
    recording = _new_recording(submission, **extra)
    db.add(recording)
    db.flush()
    return recording


def _fails(db: Session, statement: object, match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        db.execute(statement)  # type: ignore[call-overload]
        db.flush()
    db.rollback()


def _fails_add(db: Session, row: object, match: str) -> None:
    db.add(row)
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ happy path


def test_a_full_contribution_fits_the_schema(db: Session, world: World) -> None:
    submission = _submission(db, world)
    recording = _recording(db, submission)
    layer = TextLayer(
        submission_id=submission.id,
        layer_type="transcription",
        recording_id=recording.id,
        language_tag="unr",
        script_code="Deva",
    )
    db.add(layer)
    db.flush()
    revision = TextRevision(
        layer_id=layer.id,
        revision_number=1,
        content_original="ओते दिसुम",
        content_nfc="ओते दिसुम",
        detected_scripts=["Deva"],
        origin="human_contributor",
        author_user_id=world.contributor,
    )
    db.add(revision)
    db.flush()
    layer.current_revision_id = revision.id
    submission.status = "awaiting_review"
    db.add(ReviewEvent(submission_id=submission.id, reviewer_id=world.reviewer, action="approve"))
    db.commit()
    assert layer.current_revision_id == revision.id


# ------------------------------------------------------------------ speakers


def test_demographics_need_consent(db: Session, world: World) -> None:
    _fails_add(
        db,
        Speaker(speaker_code="SPK-AAAAA", created_by=world.contributor, age_band="30-44"),
        "demographics_need_consent",
    )
    _speaker(db, world.contributor, "SPK-BBBBB", age_band="30-44", demographics_consented=True)


def test_speaker_codes_are_pseudonymous_and_fixed(db: Session, world: World) -> None:
    _fails_add(db, Speaker(speaker_code="Asha Munda", created_by=world.contributor), "speaker_code")
    _fails(
        db,
        update(Speaker).where(Speaker.id == world.speaker.id).values(speaker_code="SPK-ZZZZZ"),
        "speaker_code on speakers cannot change",
    )


def test_reporting_role_cannot_read_identities(db: Session) -> None:
    db.execute(text("SET ROLE app_readonly"))
    _fails(db, text("SELECT count(*) FROM speaker_identities"), "permission denied")


# ------------------------------------------------------------------ consent


def test_consent_requires_permission_to_store(db: Session, world: World) -> None:
    second = _speaker(db, world.contributor, "SPK-CCCCC")
    with pytest.raises(IntegrityError, match="store_required"):
        _consent(db, second, world.form, world.contributor, allow_store_and_review=False)
    db.rollback()


def test_one_active_consent_per_speaker(db: Session, world: World) -> None:
    with pytest.raises(IntegrityError, match="one_active"):
        _consent(db, world.speaker, world.form, world.contributor)
    db.rollback()


def test_oral_consent_needs_evidence(db: Session, world: World) -> None:
    second = _speaker(db, world.contributor, "SPK-DDDDD")
    with pytest.raises(IntegrityError, match="oral_evidence"):
        _consent(db, second, world.form, world.contributor, method="oral_recorded")
    db.rollback()


def test_consent_records_change_only_status(db: Session, world: World) -> None:
    this = ConsentRecord.id == world.consent.id
    _fails(
        db,
        update(ConsentRecord).where(this).values(allow_ai_training=True),
        "only .* may change",
    )
    _fails(db, delete(ConsentRecord).where(this), "append_only")
    db.execute(update(ConsentRecord).where(this).values(status="superseded"))
    db.commit()


def test_consent_form_text_is_fixed_and_hashed(db: Session, world: World) -> None:
    _fails(
        db,
        update(ConsentForm).where(ConsentForm.id == world.form.id).values(body_markdown="changed"),
        "only .* may change|hash_matches_body",
    )
    _fails_add(
        db,
        ConsentForm(
            form_code="LKD-CONSENT",
            version="0.2-test",
            language="hi",
            text_sha256=SHA,
            body_markdown=FORM_BODY,
        ),
        "hash_matches_body",
    )
    db.execute(
        update(ConsentForm).where(ConsentForm.id == world.form.id).values(retired_at=text("now()"))
    )
    db.commit()


# ------------------------------------------------------------------ submissions and prompts


def test_no_submission_leaves_draft_without_consent(db: Session, world: World) -> None:
    submission = _submission(db, world, consent_record_id=None)
    db.commit()
    _fails(
        db,
        update(Submission).where(Submission.id == submission.id).values(status="uploading"),
        "consent_before_submit",
    )


@pytest.mark.parametrize(
    ("extra", "constraint"),
    [
        ({"kind": "audio", "recording_mode": None}, "mode_matches_kind"),
        ({"kind": "text", "recording_mode": "free"}, "mode_matches_kind"),
        ({"recording_mode": "read", "prompt_id": None}, "prompt_matches_mode"),
        ({"restriction_flags": ["popular"]}, "restriction_flags"),
        ({"collection_context": ["not", "an", "object"]}, "context_is_object"),
    ],
)
def test_submission_shape_rules(
    db: Session, world: World, extra: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        _submission(db, world, **extra)
    db.rollback()


def test_submitter_cannot_be_rewritten(db: Session, world: World) -> None:
    submission = _submission(db, world)
    db.commit()
    _fails(
        db,
        update(Submission)
        .where(Submission.id == submission.id)
        .values(submitted_by=world.reviewer),
        "submitted_by on submissions cannot change",
    )


def test_prompts_are_versioned_not_edited(db: Session, world: World) -> None:
    _fails_add(
        db,
        Prompt(
            prompt_key="read-greeting",
            version=1,
            prompt_type="read_sentence",
            text="जोहार",
            source_and_licence="written by the team, CC BY 4.0",
            created_by=world.reviewer,
        ),
        "sentence_has_text_and_script",
    )
    prompt = Prompt(
        prompt_key="read-greeting",
        version=1,
        prompt_type="read_sentence",
        text="जोहार",
        script_code="Deva",
        source_and_licence="written by the team, CC BY 4.0",
        created_by=world.reviewer,
    )
    db.add(prompt)
    db.commit()
    _fails(
        db, update(Prompt).where(Prompt.id == prompt.id).values(text="नया"), "only .* may change"
    )
    _fails(
        db,
        update(Prompt).where(Prompt.id == prompt.id).values(status="approved"),
        "approval_recorded",
    )
    db.execute(
        update(Prompt)
        .where(Prompt.id == prompt.id)
        .values(status="approved", approved_by=world.reviewer)
    )
    db.commit()
    submission = _submission(db, world, recording_mode="read", prompt_id=prompt.id)
    assert submission.prompt_id == prompt.id


# ------------------------------------------------------------------ recordings


def test_original_recording_identity_is_frozen(db: Session, world: World) -> None:
    recording = _recording(db, _submission(db, world))
    db.commit()
    for column, value in (
        ("original_object_key", "originals/other"),
        ("sha256_original", "b" * 64),
        ("upload_key", uuid.uuid4()),
    ):
        _fails(
            db,
            update(Recording).where(Recording.id == recording.id).values({column: value}),
            f"{column} on recordings cannot change",
        )
    db.execute(
        update(Recording)
        .where(Recording.id == recording.id)
        .values(upload_status="promoted", duration_ms=4000, quality_flags=["very_quiet"])
    )
    db.commit()
    _fails(db, delete(Recording).where(Recording.id == recording.id), "append_only")


def test_an_upload_key_is_used_once_per_submission(db: Session, world: World) -> None:
    submission = _submission(db, world)
    key = uuid.uuid4()
    _recording(db, submission, upload_key=key)
    db.commit()
    _fails_add(db, _new_recording(submission, upload_key=key), "uq_recordings_upload_key")
    _recording(db, _submission(db, world), upload_key=key)  # another submission may reuse it
    db.commit()


def test_only_the_erasure_routine_deletes_recordings(db: Session, world: World) -> None:
    recording = _recording(db, _submission(db, world))
    db.commit()
    db.execute(text("SET LOCAL ROLE app_erasure"))
    db.execute(text("SET LOCAL lkd.erasure = 'on'"))
    db.execute(delete(Recording).where(Recording.id == recording.id))
    db.commit()


def test_renditions_are_append_only(db: Session, world: World) -> None:
    recording = _recording(db, _submission(db, world))
    rendition = Rendition(
        recording_id=recording.id,
        kind="playback_opus",
        object_key="derived/x.ogg",
        sha256=SHA,
        size_bytes=10,
        params_sha256=SHA,
    )
    db.add(rendition)
    db.commit()
    _fails(db, update(Rendition).values(size_bytes=11), "append_only")


# ------------------------------------------------------------------ text


def test_layer_types_need_their_links(db: Session, world: World) -> None:
    submission = _submission(db, world)
    db.commit()
    _fails_add(
        db,
        TextLayer(
            submission_id=submission.id,
            layer_type="transcription",
            language_tag="unr",
            script_code="Deva",
        ),
        "transcription_has_recording",
    )
    _fails_add(
        db,
        TextLayer(
            submission_id=submission.id,
            layer_type="translation",
            language_tag="hi",
            script_code="Deva",
        ),
        "translation_has_source",
    )


def _layer(db: Session, world: World) -> TextLayer:
    layer = TextLayer(
        submission_id=_submission(db, world, kind="text", recording_mode=None).id,
        layer_type="standalone",
        entry_type="sentence",
        language_tag="unr",
        script_code="Latn",
    )
    db.add(layer)
    db.flush()
    return layer


def _revision(layer: TextLayer, **extra: object) -> TextRevision:
    values: dict[str, object] = {
        "layer_id": layer.id,
        "revision_number": 1,
        "content_original": "Johar",
        "content_nfc": "Johar",
        "origin": "human_contributor",
    }
    values.update(extra)
    return TextRevision(**values)


def test_revision_provenance_rules(db: Session, world: World, make_user: MakeUser) -> None:
    layer = _layer(db, world)
    db.commit()
    _fails_add(db, _revision(layer), "humans_have_authors")
    layer = _layer(db, world)
    _fails_add(db, _revision(layer, origin="machine"), "machines_name_their_tool")
    layer = _layer(db, world)
    _fails_add(
        db,
        _revision(layer, author_user_id=world.contributor, confidence=Decimal("0.9")),
        "confidence_only_for_machines",
    )


def test_revisions_are_append_only_except_verification(db: Session, world: World) -> None:
    layer = _layer(db, world)
    revision = _revision(layer, author_user_id=world.contributor)
    db.add(revision)
    db.commit()
    _fails(
        db,
        update(TextRevision).where(TextRevision.id == revision.id).values(content_original="x"),
        "only .* may change",
    )
    _fails(db, delete(TextRevision).where(TextRevision.id == revision.id), "append_only")
    db.execute(
        update(TextRevision)
        .where(TextRevision.id == revision.id)
        .values(verification_status="verified")
    )
    db.commit()
    db.add(_revision(layer, author_user_id=world.contributor))  # same revision number
    with pytest.raises(IntegrityError, match="uq_text_revisions_number"):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------ review


def test_reviewers_cannot_decide_on_their_own_submissions(db: Session, world: World) -> None:
    own = _submission(db, world, submitted_by=world.reviewer)
    db.commit()
    _fails_add(
        db,
        ReviewEvent(submission_id=own.id, reviewer_id=world.reviewer, action="approve"),
        "self_review",
    )
    db.add(ReviewEvent(submission_id=own.id, reviewer_id=world.reviewer, action="comment"))
    db.commit()


def test_review_events_are_append_only_and_well_formed(db: Session, world: World) -> None:
    submission = _submission(db, world)
    db.commit()
    _fails_add(
        db,
        ReviewEvent(
            submission_id=submission.id, reviewer_id=world.reviewer, action="add_restriction"
        ),
        "restriction_actions",
    )
    db.add(
        ReviewEvent(
            submission_id=submission.id,
            reviewer_id=world.reviewer,
            action="add_restriction",
            restriction="contains_pii",
        )
    )
    db.commit()
    _fails(db, update(ReviewEvent).values(note="rewritten"), "append_only")


def test_reports_keep_what_was_reported_and_are_decided_completely(
    db: Session, world: World
) -> None:
    submission = _submission(db, world)
    report = Report(submission_id=submission.id, reported_by=world.reviewer, reason="wrong_content")
    db.add(report)
    db.commit()
    _fails_add(
        db,
        Report(submission_id=submission.id, reported_by=world.reviewer, reason="wrong_content"),
        "uq_reports_open",
    )
    _fails_add(
        db,
        Report(submission_id=submission.id, reported_by=world.contributor, reason="boring"),
        "ck_reports_reason",
    )
    _fails(db, update(Report).values(decision="dismissed"), "decision_complete")
    _fails(db, update(Report).values(reason="personal_information"), "immutable_columns")
    _fails(db, delete(Report), "append_only")
    db.execute(
        update(Report).values(
            decision="dismissed", decided_by=world.reviewer, decided_at=func.now()
        )
    )
    db.commit()
    # Once decided, the same person can report the item again.
    db.add(Report(submission_id=submission.id, reported_by=world.reviewer, reason="wrong_content"))
    db.commit()


def _release(db: Session, world: World, **extra: object) -> DatasetRelease:
    release = DatasetRelease(
        slug="mundari-speech-pilot", purpose="internal_research", created_by=world.reviewer, **extra
    )
    db.add(release)
    db.flush()
    return release


def test_releases_freeze_completely_and_then_only_retract(db: Session, world: World) -> None:
    _fails_add(
        db,
        DatasetRelease(slug="Bad Slug", purpose="internal_research", created_by=world.reviewer),
        "ck_dataset_releases_slug",
    )
    _fails_add(
        db,
        DatasetRelease(slug="pilot", purpose="marketing", created_by=world.reviewer),
        "ck_dataset_releases_purpose",
    )
    release = _release(db, world)
    db.commit()
    # A half-frozen release is refused: version, freezer, time and manifest go together.
    _fails(db, update(DatasetRelease).values(status="frozen", version="0.1.0"), "frozen_complete")
    frozen = {
        "status": "frozen",
        "version": "0.1.0",
        "approved_by": world.reviewer,
        "frozen_at": func.now(),
        "manifest_sha256": SHA,
    }
    bad_version = {**frozen, "version": "1.0"}
    _fails(db, update(DatasetRelease).values(**bad_version), "ck_dataset_releases_version")
    db.execute(update(DatasetRelease).values(**frozen))
    db.commit()

    _fails(db, update(DatasetRelease).values(data_card_markdown="changed"), "only be retracted")
    _fails(db, delete(DatasetRelease), "cannot be deleted")
    db.execute(
        update(DatasetRelease).values(
            status="retracted", retracted_at=func.now(), retraction_note="Consent issue."
        )
    )
    db.commit()
    _fails(db, update(DatasetRelease).values(retraction_note="Rewritten."), "only be retracted")
    # The same slug and version cannot be frozen twice.
    _fails_add(
        db,
        DatasetRelease(
            slug=release.slug,
            purpose="internal_research",
            created_by=world.reviewer,
            **{k: v for k, v in frozen.items() if k != "frozen_at"},
            frozen_at=release.frozen_at,
        ),
        "uq_dataset_releases_slug_version",
    )


def test_release_items_only_get_a_withdrawal_mark(db: Session, world: World) -> None:
    submission = _submission(db, world)
    release = _release(db, world)
    db.add(
        DatasetReleaseItem(
            release_id=release.id,
            submission_id=submission.id,
            consent_record_id=world.consent.id,
            consent_snapshot={"allow_research": True},
        )
    )
    db.commit()
    _fails(db, update(DatasetReleaseItem).values(consent_snapshot={}), "immutable_columns")
    _fails(db, delete(DatasetReleaseItem), "append_only")
    db.execute(update(DatasetReleaseItem).values(withdrawn_after_release_at=func.now()))
    db.commit()


def test_export_requests_keep_who_asked_and_why(db: Session, world: World) -> None:
    release = _release(db, world)
    request = ExportRequest(
        release_id=release.id, requested_by=world.reviewer, purpose_statement="Thesis analysis."
    )
    db.add(request)
    db.commit()
    _fails(db, update(ExportRequest).values(purpose_statement="Other"), "immutable_columns")
    _fails(db, update(ExportRequest).values(status="approved"), "ck_export_requests_decided")
    _fails(
        db,
        update(ExportRequest).values(
            status="ready", decided_by=world.reviewer, decided_at=func.now()
        ),
        "ck_export_requests_ready",
    )
