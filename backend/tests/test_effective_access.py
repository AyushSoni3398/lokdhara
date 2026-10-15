"""Who may find an item in the catalogue, and what a release may hold (docs/ACCESS_CONTROL.md
§3, docs/DATASET_VERSIONING.md §3, ADR-012).

One table of cases is run against both the Python rule and the SQL condition, so the two can
never disagree. All people and records are synthetic.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.consents import service as consents
from app.modules.consents.access import (
    ConsentStep,
    Item,
    Viewer,
    catalogue_filter,
    in_catalogue,
    in_release,
    release_filter,
    research_allowed,
)
from app.modules.consents.models import ConsentForm, ConsentRecord
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import Submission
from tests.conftest import MakeUser, requires_postgres

YES = ConsentStep(allow_research=True)
NO = ConsentStep(allow_research=False)
YES_FOR_PAST = ConsentStep(allow_research=True, applies_to_past=True)
NO_FOR_PAST = ConsentStep(allow_research=False, applies_to_past=True)

RESEARCHER = Viewer(is_admin=False, is_researcher=True)
STEWARD = Viewer(is_admin=False, is_researcher=True, scopes=frozenset({"culturally_restricted"}))
ADMIN = Viewer(is_admin=True, is_researcher=False)
CONTRIBUTOR = Viewer(is_admin=False, is_researcher=False)

LISTED = Item(
    status="accepted",
    restriction_flags=(),
    speaker_withdrawn=False,
    consent_withdrawn=False,
    consent=(YES,),
)

# (case, viewer, item, expected)
CASES = [
    ("accepted with research consent", RESEARCHER, LISTED, True),
    ("admins use the same list", ADMIN, LISTED, True),
    ("contributors have no catalogue", CONTRIBUTOR, LISTED, False),
    ("no research consent", RESEARCHER, replace(LISTED, consent=(NO,)), False),
    ("still processing", RESEARCHER, replace(LISTED, status="processing"), False),
    ("failed checks", RESEARCHER, replace(LISTED, status="rejected_invalid"), False),
    ("withdrawn item", ADMIN, replace(LISTED, status="withdrawn"), False),
    ("draft", RESEARCHER, replace(LISTED, status="draft"), False),
    ("speaker withdrew", RESEARCHER, replace(LISTED, speaker_withdrawn=True), False),
    ("consent withdrawn", RESEARCHER, replace(LISTED, consent_withdrawn=True), False),
    ("later no narrows", RESEARCHER, replace(LISTED, consent=(YES, NO)), False),
    ("later yes does not widen", RESEARCHER, replace(LISTED, consent=(NO, YES)), False),
    ("later yes for past widens", RESEARCHER, replace(LISTED, consent=(NO, YES_FOR_PAST)), True),
    ("no after widening", RESEARCHER, replace(LISTED, consent=(NO, YES_FOR_PAST, NO)), False),
    ("no for past", RESEARCHER, replace(LISTED, consent=(YES, NO_FOR_PAST, YES)), False),
    ("narrowed, widened, kept", RESEARCHER, replace(LISTED, consent=(YES, NO, YES_FOR_PAST)), True),
    ("plain yes after yes", RESEARCHER, replace(LISTED, consent=(YES, YES)), True),
    *[
        (f"hidden as {flag}", viewer, replace(LISTED, restriction_flags=(flag,)), False)
        for flag in ("sensitive", "third_party_voice", "contains_pii", "minor")
        for viewer in (RESEARCHER, STEWARD, ADMIN)
    ],
    (
        "culturally restricted, no scope",
        RESEARCHER,
        replace(LISTED, restriction_flags=("culturally_restricted",)),
        False,
    ),
    (
        "culturally restricted, with scope",
        STEWARD,
        replace(LISTED, restriction_flags=("culturally_restricted",)),
        True,
    ),
    (
        "culturally restricted, admin",
        ADMIN,
        replace(LISTED, restriction_flags=("culturally_restricted",)),
        True,
    ),
    (
        "culturally restricted and hidden",
        STEWARD,
        replace(LISTED, restriction_flags=("culturally_restricted", "contains_pii")),
        False,
    ),
    (
        "culturally restricted without research consent",
        STEWARD,
        replace(LISTED, restriction_flags=("culturally_restricted",), consent=(NO,)),
        False,
    ),
]
IDS = [case[0] for case in CASES]

EVERYTHING = ConsentStep(allow_research=True, allow_public_access=True, allow_ai_training=True)

# (case, purpose, item, expected)
RELEASE_CASES = [
    ("research", "internal_research", LISTED, True),
    ("external research", "external_research", LISTED, True),
    ("public needs public consent", "public", LISTED, False),
    ("public with consent", "public", replace(LISTED, consent=(EVERYTHING,)), True),
    ("ai training needs its consent", "ai_training", LISTED, False),
    ("ai training with consent", "ai_training", replace(LISTED, consent=(EVERYTHING,)), True),
    (
        "public narrowed later",
        "public",
        replace(LISTED, consent=(EVERYTHING, ConsentStep(allow_research=True))),
        False,
    ),
    *[
        (
            f"never with {flag}",
            "internal_research",
            replace(LISTED, restriction_flags=(flag,)),
            False,
        )
        for flag in (
            "sensitive",
            "third_party_voice",
            "contains_pii",
            "minor",
            "culturally_restricted",
        )
    ],
    ("not processing", "internal_research", replace(LISTED, status="processing"), False),
    ("not withdrawn", "internal_research", replace(LISTED, status="withdrawn"), False),
    ("speaker withdrew", "internal_research", replace(LISTED, speaker_withdrawn=True), False),
    ("consent withdrawn", "internal_research", replace(LISTED, consent_withdrawn=True), False),
]
RELEASE_IDS = [case[0] for case in RELEASE_CASES]


def test_no_consent_record_means_no_research() -> None:
    assert research_allowed([]) is False


@pytest.mark.parametrize(("case", "viewer", "item", "expected"), CASES, ids=IDS)
def test_python_rule(case: str, viewer: Viewer, item: Item, expected: bool) -> None:
    assert in_catalogue(viewer, item) is expected


@pytest.mark.parametrize(("case", "purpose", "item", "expected"), RELEASE_CASES, ids=RELEASE_IDS)
def test_python_release_rule(case: str, purpose: str, item: Item, expected: bool) -> None:
    assert in_release(purpose, item) is expected


def _store(db: Session, owner: uuid.UUID, item: Item) -> uuid.UUID:
    """Writes `item` as real rows: a speaker, their consent records in order, a submission."""
    consents.ensure_dev_forms(db)
    form_id = db.scalars(select(ConsentForm.id)).first()
    speaker = Speaker(
        speaker_code=f"SPK-{uuid.uuid4().hex[:8].upper()}",
        created_by=owner,
        status="withdrawn" if item.speaker_withdrawn else "active",
    )
    db.add(speaker)
    db.flush()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    records: list[ConsentRecord] = []
    for number, step in enumerate(item.consent):
        last = number == len(item.consent) - 1
        record = ConsentRecord(
            speaker_id=speaker.id,
            consent_form_id=form_id,
            supersedes_id=records[-1].id if records else None,
            status=("withdrawn" if item.consent_withdrawn else "active") if last else "superseded",
            method="in_app",
            obtained_by=owner,
            obtained_at=start + timedelta(days=number),
            guardian_involved=False,
            allow_store_and_review=True,
            allow_research=step.allow_research,
            allow_public_access=step.allow_public_access,
            allow_ai_training=step.allow_ai_training,
            applies_to_past_contributions=step.applies_to_past,
        )
        db.add(record)
        db.flush()
        records.append(record)
    submission = Submission(
        client_submission_id=uuid.uuid4(),
        submitted_by=owner,
        speaker_id=speaker.id,
        consent_record_id=records[0].id,
        kind="text",
        content_type="story",
        collection_method="self_recorded",
        status=item.status,
        restriction_flags=list(item.restriction_flags),
    )
    db.add(submission)
    db.flush()
    return submission.id


@requires_postgres
def test_sql_condition_agrees_with_the_python_rule(db: Session, make_user: MakeUser) -> None:
    owner = make_user("owner", "contributor").id
    stored = [
        (_store(db, owner, item), case, viewer, expected) for case, viewer, item, expected in CASES
    ]
    db.commit()
    for submission_id, case, viewer, expected in stored:
        found = db.scalar(
            select(Submission.id).where(Submission.id == submission_id, catalogue_filter(viewer))
        )
        assert (found is not None) is expected, case


@requires_postgres
def test_sql_release_condition_agrees_with_the_python_rule(
    db: Session, make_user: MakeUser
) -> None:
    owner = make_user("owner", "contributor").id
    stored = [
        (_store(db, owner, item), case, purpose, expected)
        for case, purpose, item, expected in RELEASE_CASES
    ]
    db.commit()
    for submission_id, case, purpose, expected in stored:
        found = db.scalar(
            select(Submission.id).where(Submission.id == submission_id, release_filter(purpose))
        )
        assert (found is not None) is expected, case
