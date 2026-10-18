"""Setting up and resetting two-step sign-in (docs/ACCESS_CONTROL.md §4, ADR-025)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity import mfa
from app.modules.identity.models import MfaRecoveryCode, User, UserMfa, UserSession
from app.modules.identity.service import AuthenticatedUser, utcnow


@dataclass(frozen=True)
class SetupStarted:
    secret: str
    uri: str
    qr_svg: str


def start_setup(db: Session, settings: Settings, current: AuthenticatedUser) -> SetupStarted:
    """A new secret, not yet in use; starting again replaces an unconfirmed one."""
    record = db.get(UserMfa, current.id)
    if record is not None and record.confirmed_at is not None:
        raise ApiError(409, "mfa_already_enabled", "Two-step sign-in is already on.")
    secret = mfa.new_secret()
    encrypted = mfa.MfaCipher(settings).encrypt(current.id, secret)
    if record is None:
        db.add(UserMfa(user_id=current.id, secret_enc=encrypted, key_version=mfa.KEY_VERSION))
    else:
        record.secret_enc, record.created_at = encrypted, utcnow()
    db.commit()
    uri = mfa.provisioning_uri(secret, current.user.username)
    return SetupStarted(secret=mfa.secret_text(secret), uri=uri, qr_svg=mfa.qr_svg(uri))


def confirm_setup(
    db: Session,
    settings: Settings,
    current: AuthenticatedUser,
    code: str,
    context: RequestContext,
) -> list[str]:
    """Turns two-step sign-in on with a first code; returns the recovery codes, shown once.

    Every other session of the user is signed out, so the only sessions left are ones that
    proved the second step.
    """
    record = db.scalar(select(UserMfa).where(UserMfa.user_id == current.id).with_for_update())
    if record is None:
        raise ApiError(409, "mfa_not_started", "Start setting up two-step sign-in first.")
    if record.confirmed_at is not None:
        raise ApiError(409, "mfa_already_enabled", "Two-step sign-in is already on.")
    now = utcnow()
    secret = mfa.MfaCipher(settings).decrypt(current.id, record.secret_enc)
    step = mfa.matching_step(secret, code, now, record.last_used_step)
    if step is None:
        raise ApiError(422, "invalid_mfa_code", "That code is not right. Try the newest one.")
    record.confirmed_at, record.last_used_step = now, step
    codes = mfa.new_recovery_codes()
    db.add_all(
        MfaRecoveryCode(user_id=current.id, code_hash=mfa.recovery_code_hash(settings, c))
        for c in codes
    )
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == current.id,
            UserSession.id != current.session_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    audit.record(
        db,
        action="auth.mfa_enabled",
        context=context,
        actor_user_id=current.id,
        target_type="user",
        target_id=current.id,
    )
    db.commit()
    return codes


def reset(db: Session, username: str) -> uuid.UUID:
    """Turns two-step sign-in off for a user who lost their phone and codes (server command).

    Their sessions end; an admin then sets it up again at the next sign-in.
    """
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise ApiError(404, "user_not_found", "No such user.")
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit.record(
        db,
        action="auth.mfa_reset",
        context=None,
        actor_user_id=None,
        actor_type="system",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return user.id
