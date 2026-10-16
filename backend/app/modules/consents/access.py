"""Effective access: who may find an item in the researcher catalogue, and which items a dataset
release may hold (ADR-012, docs/ACCESS_CONTROL.md §3, docs/CONSENT_AND_DATA_GOVERNANCE.md §3.3,
docs/DATASET_VERSIONING.md §3).

The rule is written twice, as plain Python for reasoning and tests, and as a SQL condition for
searching, and one shared table of cases checks that both agree (tests/test_effective_access.py).
Nothing here can widen what the speaker agreed to.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import (
    ARRAY,
    Boolean,
    ColumnElement,
    Text,
    and_,
    any_,
    cast,
    exists,
    false,
    func,
    literal,
    not_,
    select,
    true,
    tuple_,
)
from sqlalchemy.orm import aliased

from app.modules.consents.models import ConsentRecord
from app.modules.identity.service import AuthenticatedUser
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import Submission

# Only accepted items are listed; there is no reviewer, so nothing is ever "approved" (ADR-021).
CATALOGUE_STATUSES = ("accepted",)
# Set by an admin to hide an item after a report. Culturally restricted items stay listed, but
# only for people given that scope (who decides that waits on Q-G3).
CULTURALLY_RESTRICTED = "culturally_restricted"
HIDING_FLAGS = frozenset({"sensitive", "third_party_voice", "contains_pii", "minor"})


# The consent answer each release purpose needs (DATASET_VERSIONING §3).
PURPOSE_PERMISSIONS = {
    "internal_research": "allow_research",
    "external_research": "allow_research",
    "public": "allow_public_access",
    "ai_training": "allow_ai_training",
}


@dataclass(frozen=True)
class ConsentStep:
    """One consent record of the speaker: the uses it allows."""

    allow_research: bool
    applies_to_past: bool = False
    allow_public_access: bool = False
    allow_ai_training: bool = False
    allow_commercial_use: bool = False


def use_allowed(steps: Sequence[ConsentStep], permission: str) -> bool:
    """`steps` are the record in force when the item was sent, then every later record of the
    same speaker, oldest first. A later record can only narrow what was agreed, unless the
    speaker said it applies to past contributions too."""
    if not steps:
        return False
    allowed: bool = getattr(steps[0], permission)
    for step in steps[1:]:
        answer: bool = getattr(step, permission)
        allowed = answer if step.applies_to_past else allowed and answer
    return allowed


def research_allowed(steps: Sequence[ConsentStep]) -> bool:
    return use_allowed(steps, "allow_research")


@dataclass(frozen=True)
class Viewer:
    is_admin: bool
    is_researcher: bool
    scopes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Item:
    status: str
    restriction_flags: Collection[str]
    speaker_withdrawn: bool
    consent_withdrawn: bool
    consent: Sequence[ConsentStep]


def in_catalogue(viewer: Viewer, item: Item) -> bool:
    if not (viewer.is_admin or viewer.is_researcher):
        return False
    if item.status not in CATALOGUE_STATUSES or item.speaker_withdrawn or item.consent_withdrawn:
        return False
    if HIDING_FLAGS & set(item.restriction_flags):
        return False
    if CULTURALLY_RESTRICTED in item.restriction_flags and not (
        viewer.is_admin or CULTURALLY_RESTRICTED in viewer.scopes
    ):
        return False
    return research_allowed(item.consent)


def in_release(purpose: str, item: Item) -> bool:
    """Releases are stricter than the catalogue: any restriction flag keeps an item out,
    including `culturally_restricted` until the community approves it (Q-G3)."""
    if item.status not in CATALOGUE_STATUSES or item.speaker_withdrawn or item.consent_withdrawn:
        return False
    if item.restriction_flags:
        return False
    return use_allowed(item.consent, PURPOSE_PERMISSIONS[purpose])


# ------------------------------------------------------------------ the same rule in SQL


def _use_allowed_sql(permission: str) -> ColumnElement[bool]:
    """use_allowed() for Submission rows: refused when some record from the one the item was
    sent under onwards says no, and no later record widened it again for past items."""
    base = aliased(ConsentRecord)
    refusing = aliased(ConsentRecord)
    widening = aliased(ConsentRecord)
    order = tuple_(refusing.obtained_at, refusing.id)
    refused = (
        select(refusing.id)
        .join(base, base.id == Submission.consent_record_id)
        .where(
            refusing.speaker_id == base.speaker_id,
            order >= tuple_(base.obtained_at, base.id),
            not_(getattr(refusing, permission)),
            ~exists().where(
                widening.speaker_id == refusing.speaker_id,
                tuple_(widening.obtained_at, widening.id) > order,
                widening.applies_to_past_contributions,
                getattr(widening, permission),
            ),
        )
    )
    return and_(Submission.consent_record_id.is_not(None), ~exists(refused))


def _accepted_and_not_withdrawn() -> ColumnElement[bool]:
    withdrawn_consent = aliased(ConsentRecord)
    return and_(
        Submission.status.in_(CATALOGUE_STATUSES),
        ~exists().where(Speaker.id == Submission.speaker_id, Speaker.status == "withdrawn"),
        ~exists().where(
            withdrawn_consent.speaker_id == Submission.speaker_id,
            withdrawn_consent.status == "withdrawn",
        ),
    )


def catalogue_filter(viewer: Viewer) -> ColumnElement[bool]:
    """in_catalogue() as a condition on Submission, for searches."""
    if not (viewer.is_admin or viewer.is_researcher):
        return false()
    culture_ok = (
        true()
        if viewer.is_admin or CULTURALLY_RESTRICTED in viewer.scopes
        else not_(literal(CULTURALLY_RESTRICTED, Text) == any_(Submission.restriction_flags))
    )
    return and_(
        _accepted_and_not_withdrawn(),
        not_(
            Submission.restriction_flags.op("&&", return_type=Boolean)(
                cast(sorted(HIDING_FLAGS), ARRAY(Text))
            )
        ),
        culture_ok,
        _use_allowed_sql("allow_research"),
    )


def release_filter(purpose: str) -> ColumnElement[bool]:
    """in_release() as a condition on Submission."""
    return and_(
        _accepted_and_not_withdrawn(),
        func.cardinality(Submission.restriction_flags) == 0,
        _use_allowed_sql(PURPOSE_PERMISSIONS[purpose]),
    )


def consent_allows(purpose: str) -> ColumnElement[bool]:
    """Only the consent part of release_filter(): does the speaker still allow this use? Used
    to find frozen release items whose consent was narrowed after freezing."""
    return _use_allowed_sql(PURPOSE_PERMISSIONS[purpose])


def viewer_for(user: AuthenticatedUser) -> Viewer:
    return Viewer(
        is_admin=user.has_role("admin"),
        is_researcher=user.has_role("researcher"),
        scopes=frozenset(g.scope for g in user.grants if g.scope),
    )
