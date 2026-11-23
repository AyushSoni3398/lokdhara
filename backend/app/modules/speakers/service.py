"""Speaker profiles and their restricted identity details (docs/ACCESS_CONTROL.md §2).

Profiles are pseudonymous: the code is random and the name, contact, and village live encrypted
in speaker_identities, readable only by the creating facilitator and admins (audited).
"""

import uuid

from sqlalchemy import Select, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity.service import AuthenticatedUser, utcnow
from app.modules.speakers.codes import GENDER_LETTERS, code_with_letter, new_speaker_code
from app.modules.speakers.crypto import IdentityCipher
from app.modules.speakers.models import Speaker, SpeakerIdentity

# Roles that may record their own voice (docs/ACCESS_CONTROL.md: "Create submission for self").
SELF_SPEAKER_ROLES = ("contributor", "facilitator", "reviewer", "admin")
DEMOGRAPHIC_FIELDS = (
    "age_band",
    "gender",
    "first_language",
    "other_languages",
    "region_coarse",
)
IDENTITY_FIELDS = ("full_name", "contact", "village", "notes")


def gender_letter(speaker: Speaker) -> str:
    if not speaker.demographics_consented or speaker.gender is None:
        return "X"
    return GENDER_LETTERS.get(speaker.gender, "X")


def refresh_code(db: Session, speaker: Speaker) -> None:
    """Brings the speaker code's last letter in line with the gender now stored, and renames
    the speaker's recordings with it. Earlier frozen releases keep the code they were made with."""
    new = code_with_letter(speaker.speaker_code, gender_letter(speaker))
    old = speaker.speaker_code
    if new == old:
        return
    speaker.speaker_code = new
    db.flush()
    db.execute(
        text(
            "UPDATE recordings SET recording_code = :new || substr(recording_code, :cut) "
            "WHERE starts_with(recording_code, :prefix)"
        ),
        {"new": new, "cut": len(old) + 1, "prefix": f"{old}_"},
    )


# ------------------------------------------------------------------ access rules


def can_view(user: AuthenticatedUser, speaker: Speaker) -> bool:
    return (
        user.has_role("admin") or speaker.linked_user_id == user.id or speaker.created_by == user.id
    )


def can_act_for(user: AuthenticatedUser, speaker: Speaker) -> bool:
    """May capture consent, edit the profile, and submit recordings for this speaker."""
    if user.has_role("admin") or speaker.linked_user_id == user.id:
        return True
    return speaker.created_by == user.id and user.has_role("facilitator")


def can_manage_identity(user: AuthenticatedUser, speaker: Speaker) -> bool:
    """Admins, the facilitator who registered the speaker, and the speakers themselves, who
    fill in their own details when they sign up (ADR-028)."""
    return (
        user.has_role("admin")
        or speaker.linked_user_id == user.id
        or (speaker.created_by == user.id and user.has_role("facilitator"))
    )


def created_by(user_id: uuid.UUID) -> Select[uuid.UUID]:
    """IDs of the speakers this user created, for other modules' access queries."""
    return select(Speaker.id).where(Speaker.created_by == user_id)


def _not_found() -> ApiError:
    # Same answer whether the speaker does not exist or is not visible to this user.
    return ApiError(404, "speaker_not_found", "Speaker not found.")


def _forbidden() -> ApiError:
    return ApiError(403, "forbidden", "You do not have permission for this action.")


def get_visible(
    db: Session, user: AuthenticatedUser, speaker_id: uuid.UUID, *, for_update: bool = False
) -> Speaker:
    query = select(Speaker).where(Speaker.id == speaker_id)
    if for_update:
        query = query.with_for_update()
    speaker = db.scalar(query)
    if speaker is None or not can_view(user, speaker):
        raise _not_found()
    return speaker


def get_for_action(
    db: Session, user: AuthenticatedUser, speaker_id: uuid.UUID, *, for_update: bool = False
) -> Speaker:
    """A speaker the user may act for, and who has not withdrawn."""
    speaker = get_visible(db, user, speaker_id, for_update=for_update)
    if not can_act_for(user, speaker):
        raise _forbidden()
    if speaker.status != "active":
        raise ApiError(409, "speaker_withdrawn", "This speaker has withdrawn.")
    return speaker


# ------------------------------------------------------------------ profiles


def create_speaker(
    db: Session,
    *,
    actor: AuthenticatedUser,
    for_self: bool,
    dialect_label: str | None,
    context: RequestContext,
) -> Speaker:
    if for_self:
        if not actor.has_role(*SELF_SPEAKER_ROLES):
            raise _forbidden()
        if db.scalar(select(Speaker.id).where(Speaker.linked_user_id == actor.id)):
            raise ApiError(409, "self_speaker_exists", "You already have a speaker profile.")
    elif not actor.has_role("facilitator", "admin"):
        raise _forbidden()

    for _attempt in range(5):
        speaker = Speaker(
            speaker_code=new_speaker_code(),
            linked_user_id=actor.id if for_self else None,
            created_by=actor.id,
            dialect_label=dialect_label,
        )
        try:
            with db.begin_nested():
                db.add(speaker)
        except IntegrityError as exc:
            if "uq_speakers_linked_user" in str(exc.orig):
                raise ApiError(
                    409, "self_speaker_exists", "You already have a speaker profile."
                ) from exc
            if not any(
                n in str(exc.orig) for n in ("uq_speakers_speaker_code", "uq_speakers_code_random")
            ):
                raise
            continue  # code collision: draw another
        break
    else:  # pragma: no cover - 30^6 codes make five collisions in a row implausible
        raise RuntimeError("could not allocate a speaker code")

    audit.record(
        db,
        action="speaker.create",
        context=context,
        actor_user_id=actor.id,
        target_type="speaker",
        target_id=speaker.id,
        details={"for_self": for_self},
    )
    db.commit()
    return speaker


def list_speakers(db: Session, user: AuthenticatedUser, *, mine: bool) -> list[Speaker]:
    query = select(Speaker).order_by(Speaker.created_at.desc())
    if mine or not user.has_role("admin"):
        query = query.where(or_(Speaker.linked_user_id == user.id, Speaker.created_by == user.id))
    return list(db.scalars(query.limit(500)))


def update_speaker(
    db: Session,
    *,
    actor: AuthenticatedUser,
    speaker_id: uuid.UUID,
    changes: dict[str, object],
    settings: Settings,
    context: RequestContext,
) -> Speaker:
    speaker = get_for_action(db, actor, speaker_id, for_update=True)
    adds_demographics = any(
        changes[field] is not None for field in DEMOGRAPHIC_FIELDS if field in changes
    )
    if adds_demographics and not speaker.demographics_consented:
        raise ApiError(
            422,
            "demographics_not_consented",
            "The speaker has not agreed to share age group, area, or languages.",
        )
    if changes.get("age_band") == "under_18" and not settings.allow_minors:
        raise ApiError(422, "minors_not_enabled", "Recordings from minors are not collected yet.")
    for field, value in changes.items():
        setattr(speaker, field, value)
    refresh_code(db, speaker)
    audit.record(
        db,
        action="speaker.update",
        context=context,
        actor_user_id=actor.id,
        target_type="speaker",
        target_id=speaker.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return speaker


def set_demographics_consent(db: Session, speaker: Speaker, consented: bool) -> None:
    """Mirrors the active consent record. Withdrawing the answer erases the stored values,
    and the gender letter in the speaker's codes becomes X."""
    speaker.demographics_consented = consented
    if not consented:
        for field in DEMOGRAPHIC_FIELDS:
            setattr(speaker, field, None)
    refresh_code(db, speaker)


# ------------------------------------------------------------------ restricted identity


def _identity_target(db: Session, actor: AuthenticatedUser, speaker_id: uuid.UUID) -> Speaker:
    speaker = get_visible(db, actor, speaker_id)
    if not can_manage_identity(actor, speaker):
        raise _forbidden()
    return speaker


def read_identity(
    db: Session,
    cipher: IdentityCipher,
    *,
    actor: AuthenticatedUser,
    speaker_id: uuid.UUID,
    context: RequestContext,
) -> tuple[dict[str, str | None], SpeakerIdentity | None]:
    speaker = _identity_target(db, actor, speaker_id)
    row = db.get(SpeakerIdentity, speaker.id)
    values: dict[str, str | None] = dict.fromkeys(IDENTITY_FIELDS)
    if row is not None:
        for field in IDENTITY_FIELDS:
            sealed: bytes | None = getattr(row, f"{field}_enc")
            if sealed is not None:
                values[field] = cipher.decrypt(speaker.id, field, sealed, row.key_version)
    # Every read of restricted identity is audited, even when nothing is stored.
    audit.record(
        db,
        action="speaker_identity.read",
        context=context,
        actor_user_id=actor.id,
        target_type="speaker",
        target_id=speaker.id,
    )
    db.commit()
    return values, row


def write_identity(
    db: Session,
    cipher: IdentityCipher,
    *,
    actor: AuthenticatedUser,
    speaker_id: uuid.UUID,
    values: dict[str, str | None],
    context: RequestContext,
) -> SpeakerIdentity:
    speaker = _identity_target(db, actor, speaker_id)
    if speaker.status != "active":
        raise ApiError(409, "speaker_withdrawn", "This speaker has withdrawn.")
    row = db.get(SpeakerIdentity, speaker.id, with_for_update=True)
    if row is None:
        row = SpeakerIdentity(speaker_id=speaker.id)
        db.add(row)
    for field in IDENTITY_FIELDS:
        value = values.get(field)
        sealed = cipher.encrypt(speaker.id, field, value) if value is not None else None
        setattr(row, f"{field}_enc", sealed)
    row.key_version = cipher.key_version
    row.updated_at = utcnow()
    audit.record(
        db,
        action="speaker_identity.write",
        context=context,
        actor_user_id=actor.id,
        target_type="speaker",
        target_id=speaker.id,
        details={"fields_set": sorted(f for f in IDENTITY_FIELDS if values.get(f) is not None)},
    )
    db.commit()
    return row
