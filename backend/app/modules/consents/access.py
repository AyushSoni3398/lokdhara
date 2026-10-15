"""Effective access: who may find an item in the researcher catalogue (ADR-012,
docs/ACCESS_CONTROL.md §3, docs/CONSENT_AND_DATA_GOVERNANCE.md §3.3).

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


@dataclass(frozen=True)
class ConsentStep:
    """One consent record of the speaker, as far as research use is concerned."""

    allow_research: bool
    applies_to_past: bool = False


def research_allowed(steps: Sequence[ConsentStep]) -> bool:
    """`steps` are the record in force when the item was sent, then every later record of the
    same speaker, oldest first. A later record can only narrow what was agreed, unless the
    speaker said it applies to past contributions too."""
    if not steps:
        return False
    allowed = steps[0].allow_research
    for step in steps[1:]:
        allowed = step.allow_research if step.applies_to_past else allowed and step.allow_research
    return allowed


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


# ------------------------------------------------------------------ the same rule in SQL


def _research_allowed_sql() -> ColumnElement[bool]:
    """research_allowed() for Submission rows: refused when some record from the one the item
    was sent under onwards says no, and no later record widened it again for past items."""
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
            not_(refusing.allow_research),
            ~exists().where(
                widening.speaker_id == refusing.speaker_id,
                tuple_(widening.obtained_at, widening.id) > order,
                widening.applies_to_past_contributions,
                widening.allow_research,
            ),
        )
    )
    return and_(Submission.consent_record_id.is_not(None), ~exists(refused))


def catalogue_filter(viewer: Viewer) -> ColumnElement[bool]:
    """in_catalogue() as a condition on Submission, for searches."""
    if not (viewer.is_admin or viewer.is_researcher):
        return false()
    withdrawn_consent = aliased(ConsentRecord)
    culture_ok = (
        true()
        if viewer.is_admin or CULTURALLY_RESTRICTED in viewer.scopes
        else not_(literal(CULTURALLY_RESTRICTED, Text) == any_(Submission.restriction_flags))
    )
    return and_(
        Submission.status.in_(CATALOGUE_STATUSES),
        ~exists().where(Speaker.id == Submission.speaker_id, Speaker.status == "withdrawn"),
        ~exists().where(
            withdrawn_consent.speaker_id == Submission.speaker_id,
            withdrawn_consent.status == "withdrawn",
        ),
        not_(
            Submission.restriction_flags.op("&&", return_type=Boolean)(
                cast(sorted(HIDING_FLAGS), ARRAY(Text))
            )
        ),
        culture_ok,
        _research_allowed_sql(),
    )


def viewer_for(user: AuthenticatedUser) -> Viewer:
    return Viewer(
        is_admin=user.has_role("admin"),
        is_researcher=user.has_role("researcher"),
        scopes=frozenset(g.scope for g in user.grants if g.scope),
    )
