"""Accounts, sign-up, invitations, sessions, and throttling (ADR-008, ADR-028,
docs/ACCESS_CONTROL.md).

Every function that changes data commits its own transaction, together with its audit event.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.audit.service import RequestContext
from app.modules.identity import mfa
from app.modules.identity.models import (
    STAFF_ROLES,
    Invitation,
    LoginThrottle,
    MfaRecoveryCode,
    PasswordReset,
    User,
    UserMfa,
    UserRole,
    UserSession,
)
from app.security import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    hash_password,
    keyed_hash,
    new_token,
    password_needs_rehash,
    token_hash,
    verify_password,
)

# Refresh last_seen_at at most this often, to avoid a write on every request.
_TOUCH_INTERVAL = timedelta(minutes=1)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Grant:
    role: str
    scope: str | None


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    grants: tuple[Grant, ...]
    session_id: uuid.UUID
    session_token: str
    mfa_enabled: bool = False
    # An admin who must use two-step sign-in but has not set it up yet: they keep every role
    # except admin until they do (docs/ACCESS_CONTROL.md §4).
    mfa_setup_required: bool = False

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(g.role for g in self.grants)

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))


# ---------------------------------------------------------------- validation


def normalize_username(username: str) -> str:
    return username.strip().lower()


def check_password_policy(password: str, username: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ApiError(
            422,
            "weak_password",
            "Password does not meet the policy.",
            f"Use {PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters.",
        )
    if normalize_username(username) in password.lower():
        raise ApiError(
            422, "weak_password", "Password does not meet the policy.", "Do not include username."
        )


# ---------------------------------------------------------------- roles


def active_grants(db: Session, user_id: uuid.UUID) -> tuple[Grant, ...]:
    rows = db.execute(
        select(UserRole.role, UserRole.scope)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
        .order_by(UserRole.role)
    ).all()
    return tuple(Grant(role, scope) for role, scope in rows)


def _count_active_admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(func.distinct(UserRole.user_id)))
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.role == "admin",
                UserRole.revoked_at.is_(None),
                User.status == "active",
            )
        )
        or 0
    )


def grant_role(
    db: Session,
    *,
    actor: AuthenticatedUser | None,
    user_id: uuid.UUID,
    role: str,
    scope: str | None,
    context: RequestContext | None,
) -> None:
    if db.get(User, user_id) is None:
        raise ApiError(404, "user_not_found", "User not found.")
    db.add(
        UserRole(
            user_id=user_id,
            role=role,
            scope=scope,
            granted_by=actor.id if actor else None,
            granted_at=utcnow(),
        )
    )
    audit.record(
        db,
        action="role.grant",
        context=context,
        actor_user_id=actor.id if actor else None,
        actor_type="user" if actor else "system",
        target_type="user",
        target_id=user_id,
        details={"role": role, "scope": scope},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "role_already_granted", "The user already has this role.") from None


def revoke_role(
    db: Session,
    *,
    actor: AuthenticatedUser,
    user_id: uuid.UUID,
    role: str,
    context: RequestContext,
) -> None:
    grants = db.scalars(
        select(UserRole)
        .where(UserRole.user_id == user_id, UserRole.role == role, UserRole.revoked_at.is_(None))
        .with_for_update()
    ).all()
    if not grants:
        raise ApiError(404, "role_not_granted", "The user does not have this role.")
    if role == "admin" and _count_active_admins(db) <= 1:
        raise ApiError(409, "last_admin", "The last administrator cannot be removed.")
    now = utcnow()
    for grant in grants:
        grant.revoked_at = now
        grant.revoked_by = actor.id
    audit.record(
        db,
        action="role.revoke",
        context=context,
        actor_user_id=actor.id,
        target_type="user",
        target_id=user_id,
        details={"role": role},
    )
    db.commit()


# ---------------------------------------------------------------- users


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    preferred_locale: str = "hi",
) -> User:
    """Adds an active user to the session without committing (callers own the transaction)."""
    username = normalize_username(username)
    check_password_policy(password, username)
    user = User(
        username=username,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        status="active",
        preferred_locale=preferred_locale,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "username_taken", "This username is already in use.") from None
    return user


# ---------------------------------------------------------------- login throttling


def _throttle_limits(settings: Settings, username: str, context: RequestContext) -> dict[str, int]:
    """Failure limits per throttle key. Facilitators may share one network, so the per-IP
    limit is higher than the per-account limit."""
    secret = settings.secret_key.get_secret_value()
    limits = {keyed_hash(secret, "login-user", username): settings.login_max_failures}
    if context.ip_hash:
        limits[keyed_hash(secret, "login-ip", context.ip_hash)] = settings.login_max_failures_per_ip
    return limits


def _raise_if_locked(
    db: Session,
    keys: list[str],
    now: datetime,
    code: str = "login_locked",
    message: str = "Too many failed sign-in attempts. Try again later.",
) -> None:
    locked_until = db.scalar(
        select(func.max(LoginThrottle.locked_until)).where(LoginThrottle.key_hash.in_(keys))
    )
    if locked_until is not None and locked_until > now:
        retry_after = max(1, int((locked_until - now).total_seconds()))
        raise ApiError(
            429,
            code,
            message,
            headers={"Retry-After": str(retry_after)},
        )


def _record_failure(
    db: Session,
    settings: Settings,
    limits: dict[str, int],
    now: datetime,
    *,
    window_minutes: int | None = None,
    lockout_minutes: int | None = None,
) -> None:
    """Counts one event per key and locks a key that reaches its limit. Used for failed
    sign-ins and, with its own window, for sign-ups."""
    window = window_minutes or settings.login_window_minutes
    lockout = lockout_minutes or settings.login_lockout_minutes
    window_start = now - timedelta(minutes=window)
    expired = LoginThrottle.window_started_at < window_start
    for key, limit in limits.items():
        stmt = insert(LoginThrottle).values(key_hash=key, failures=1, window_started_at=now)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[LoginThrottle.key_hash],
                set_={
                    # A failure after the window has passed starts a new window.
                    "failures": case((expired, 1), else_=LoginThrottle.failures + 1),
                    "window_started_at": case(
                        (expired, now), else_=LoginThrottle.window_started_at
                    ),
                },
            )
        )
        db.execute(
            update(LoginThrottle)
            .where(LoginThrottle.key_hash == key, LoginThrottle.failures >= limit)
            .values(
                locked_until=now + timedelta(minutes=lockout),
                failures=0,
                window_started_at=now,
            )
        )


# ---------------------------------------------------------------- login and sessions


def _session_idle_limit(settings: Settings, grants: tuple[Grant, ...]) -> timedelta:
    staff = any(g.role in STAFF_ROLES for g in grants)
    hours = settings.session_idle_hours_staff if staff else settings.session_idle_hours_contributor
    return timedelta(hours=hours)


def mfa_enabled(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(select(UserMfa.confirmed_at).where(UserMfa.user_id == user_id)) is not None


def _signed_in(
    db: Session,
    settings: Settings,
    user: User,
    grants: tuple[Grant, ...],
    session_id: uuid.UUID,
    token: str,
) -> AuthenticatedUser:
    enabled = mfa_enabled(db, user.id)
    setup_required = (
        settings.admin_mfa_required and not enabled and any(g.role == "admin" for g in grants)
    )
    if setup_required:
        grants = tuple(g for g in grants if g.role != "admin")
    return AuthenticatedUser(
        user, grants, session_id, token, mfa_enabled=enabled, mfa_setup_required=setup_required
    )


def _second_factor_ok(
    db: Session, settings: Settings, user: User, code: str, now: datetime, context: RequestContext
) -> bool:
    """Checks an authenticator code or an unused recovery code, and uses it up."""
    record = db.scalar(select(UserMfa).where(UserMfa.user_id == user.id).with_for_update())
    assert record is not None  # noqa: S101 - the caller found it confirmed
    secret = mfa.MfaCipher(settings).decrypt(user.id, record.secret_enc)
    step = mfa.matching_step(secret, code, now, record.last_used_step)
    if step is not None:
        record.last_used_step = step
        return True
    recovery = db.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == mfa.recovery_code_hash(settings, code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if recovery is None:
        return False
    recovery.used_at = now
    left = db.scalar(
        select(func.count())
        .select_from(MfaRecoveryCode)
        .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
    )
    audit.record(
        db,
        action="auth.mfa_recovery_code_used",
        context=context,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        details={"codes_left": left or 0},
    )
    return True


def login(
    db: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    context: RequestContext,
    code: str | None = None,
) -> AuthenticatedUser:
    now = utcnow()
    username = normalize_username(username)
    limits = _throttle_limits(settings, username, context)
    user_key = next(iter(limits))
    _raise_if_locked(db, list(limits), now)

    user = db.scalar(select(User).where(User.username == username))
    stored_hash = user.password_hash if user else None
    # End the read before the slow password check (about 0.25 s of CPU), so a burst of
    # sign-ins cannot hold every pooled connection; the writes below start a new transaction.
    db.rollback()
    # verify_password runs even for unknown users so timing does not reveal accounts.
    password_ok = verify_password(stored_hash, password)
    if user is None or not password_ok or user.status != "active":
        _record_failure(db, settings, limits, now)
        audit.record(
            db,
            action="auth.login_failed",
            context=context,
            actor_user_id=None,
            actor_type="system",
            target_type="user" if user else None,
            target_id=user.id if user else None,
        )
        db.commit()
        raise ApiError(401, "invalid_credentials", "Username or password is incorrect.")

    if mfa_enabled(db, user.id):
        if not code:
            db.rollback()
            raise ApiError(
                401, "mfa_required", "Enter the 6-digit code from your authenticator app."
            )
        if not _second_factor_ok(db, settings, user, code, now, context):
            db.rollback()
            _record_failure(db, settings, limits, now)
            audit.record(
                db,
                action="auth.login_failed",
                context=context,
                actor_user_id=None,
                actor_type="system",
                target_type="user",
                target_id=user.id,
                details={"step": "mfa"},
            )
            db.commit()
            raise ApiError(401, "invalid_mfa_code", "That code is not right. Try the newest one.")

    db.execute(delete(LoginThrottle).where(LoginThrottle.key_hash == user_key))
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return _start_session(db, settings, user, now, context)


def _start_session(
    db: Session, settings: Settings, user: User, now: datetime, context: RequestContext
) -> AuthenticatedUser:
    user.last_login_at = now
    token = new_token()
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_absolute_days),
        user_agent_hash=context.user_agent_hash,
        ip_hash=context.ip_hash,
    )
    db.add(session)
    db.flush()
    audit.record(
        db,
        action="auth.login",
        context=context,
        actor_user_id=user.id,
        target_type="session",
        target_id=session.id,
    )
    db.commit()
    return _signed_in(db, settings, user, active_grants(db, user.id), session.id, token)


def resolve_session(db: Session, settings: Settings, token: str) -> AuthenticatedUser | None:
    """The signed-in user for a session token, or None if it is unknown, revoked, or expired."""
    now = utcnow()
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == token_hash(token))
    ).first()
    if row is None:
        return None
    session, user = row
    if session.revoked_at is not None or session.expires_at <= now or user.status != "active":
        return None
    grants = active_grants(db, user.id)
    if session.last_seen_at + _session_idle_limit(settings, grants) <= now:
        return None
    if now - session.last_seen_at > _TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return _signed_in(db, settings, user, grants, session.id, token)


def logout(db: Session, current: AuthenticatedUser, context: RequestContext) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.id == current.session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit.record(
        db,
        action="auth.logout",
        context=context,
        actor_user_id=current.id,
        target_type="session",
        target_id=current.session_id,
    )
    db.commit()


def _revoke_sessions(db: Session, user_id: uuid.UUID) -> int:
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def revoke_all_sessions(
    db: Session, *, actor: AuthenticatedUser, user_id: uuid.UUID, context: RequestContext
) -> int:
    if db.get(User, user_id) is None:
        raise ApiError(404, "user_not_found", "User not found.")
    count = _revoke_sessions(db, user_id)
    audit.record(
        db,
        action="auth.sessions_revoked",
        context=context,
        actor_user_id=actor.id,
        target_type="user",
        target_id=user_id,
        details={"count": count},
    )
    db.commit()
    return count


# ---------------------------------------------------------------- public sign-up


def signup(
    db: Session,
    settings: Settings,
    *,
    username: str,
    display_name: str,
    password: str,
    preferred_locale: str,
    context: RequestContext,
) -> AuthenticatedUser:
    """Makes a contributor account and signs it in (ADR-028). Other roles still come from an
    admin, by invitation or by a role grant."""
    if not settings.open_signup:
        raise ApiError(404, "signup_closed", "Sign-up is closed. Ask the team for an invitation.")
    now = utcnow()
    limits = (
        {
            keyed_hash(
                settings.secret_key.get_secret_value(), "signup-ip", context.ip_hash
            ): settings.signup_max_per_ip
        }
        if context.ip_hash
        else {}
    )
    _raise_if_locked(
        db,
        list(limits),
        now,
        code="signup_limited",
        message="Too many new accounts from this network. Try again later.",
    )
    user = create_user(
        db,
        username=username,
        display_name=display_name,
        password=password,
        preferred_locale=preferred_locale,
    )
    db.add(UserRole(user_id=user.id, role="contributor", granted_at=now))
    _record_failure(
        db,
        settings,
        limits,
        now,
        window_minutes=settings.signup_window_minutes,
        lockout_minutes=settings.signup_window_minutes,
    )
    audit.record(
        db,
        action="auth.signup",
        context=context,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    return _start_session(db, settings, user, now, context)


# ---------------------------------------------------------------- invitations


def create_invitation(
    db: Session,
    *,
    actor: AuthenticatedUser,
    role: str,
    expires_in_hours: int,
    context: RequestContext,
) -> tuple[Invitation, str]:
    """Returns the invitation and its raw token, which is shown once and never stored."""
    token = new_token()
    invitation = Invitation(
        token_hash=token_hash(token),
        role=role,
        created_by=actor.id,
        expires_at=utcnow() + timedelta(hours=expires_in_hours),
    )
    db.add(invitation)
    db.flush()
    audit.record(
        db,
        action="invitation.create",
        context=context,
        actor_user_id=actor.id,
        target_type="invitation",
        target_id=invitation.id,
        details={"role": role, "expires_in_hours": expires_in_hours},
    )
    db.commit()
    return invitation, token


def accept_invitation(
    db: Session,
    *,
    token: str,
    username: str,
    display_name: str,
    password: str,
    preferred_locale: str,
    context: RequestContext,
) -> User:
    now = utcnow()
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == token_hash(token)).with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        # One answer for unknown, used, revoked, and expired: do not reveal which.
        raise ApiError(404, "invitation_invalid", "This invitation is not valid.")
    user = create_user(
        db,
        username=username,
        display_name=display_name,
        password=password,
        preferred_locale=preferred_locale,
    )
    invitation.accepted_by = user.id
    invitation.accepted_at = now
    db.add(
        UserRole(
            user_id=user.id, role=invitation.role, granted_by=invitation.created_by, granted_at=now
        )
    )
    audit.record(
        db,
        action="invitation.accept",
        context=context,
        actor_user_id=user.id,
        target_type="invitation",
        target_id=invitation.id,
        details={"role": invitation.role},
    )
    db.commit()
    return user


# ---------------------------------------------------------------- password resets


def create_password_reset(
    db: Session,
    settings: Settings,
    *,
    actor: AuthenticatedUser,
    user_id: uuid.UUID,
    context: RequestContext,
) -> tuple[PasswordReset, str]:
    if db.get(User, user_id) is None:
        raise ApiError(404, "user_not_found", "User not found.")
    token = new_token()
    reset = PasswordReset(
        user_id=user_id,
        token_hash=token_hash(token),
        created_by=actor.id,
        expires_at=utcnow() + timedelta(hours=settings.password_reset_hours),
    )
    db.add(reset)
    db.flush()
    audit.record(
        db,
        action="password_reset.create",
        context=context,
        actor_user_id=actor.id,
        target_type="user",
        target_id=user_id,
    )
    db.commit()
    return reset, token


def use_password_reset(
    db: Session, *, token: str, new_password: str, context: RequestContext
) -> None:
    now = utcnow()
    reset = db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == token_hash(token)).with_for_update()
    )
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise ApiError(404, "reset_invalid", "This reset link is not valid.")
    user = db.get(User, reset.user_id)
    assert user is not None  # noqa: S101 - FK guarantees it
    check_password_policy(new_password, user.username)
    user.password_hash = hash_password(new_password)
    user.updated_at = now
    reset.used_at = now
    # A reset signs the user out everywhere.
    _revoke_sessions(db, user.id)
    audit.record(
        db,
        action="password_reset.use",
        context=context,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    db.commit()
