"""Authentication and account administration (docs/API_SPECIFICATION.md §2).

Tokens travel in request bodies and URL fragments (`/invite#<token>`), never in URL paths
or query strings, so they do not end up in access logs.
"""

import uuid

from fastapi import APIRouter, Response, status

from app.config import Settings
from app.db import DbSession
from app.modules.identity import service
from app.modules.identity.deps import (
    SESSION_COOKIE,
    AdminUser,
    Context,
    CurrentUser,
    SettingsDep,
    csrf_token_for,
)
from app.modules.identity.schemas import (
    AcceptInvitationRequest,
    GrantOut,
    InvitationOut,
    InvitationRequest,
    LoginRequest,
    PasswordResetOut,
    PasswordResetUseRequest,
    RevokedSessionsOut,
    Role,
    RoleGrantRequest,
    SessionOut,
    UserOut,
)
from app.modules.identity.service import AuthenticatedUser

router = APIRouter(tags=["auth"])


def _session_out(settings: Settings, user: AuthenticatedUser) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(user.user, from_attributes=True),
        roles=[GrantOut(role=g.role, scope=g.scope) for g in user.grants],
        csrf_token=csrf_token_for(settings, user.session_token),
    )


@router.post("/auth/login")
def login(
    body: LoginRequest, response: Response, db: DbSession, settings: SettingsDep, context: Context
) -> SessionOut:
    user = service.login(
        db, settings, username=body.username, password=body.password, context=context
    )
    response.set_cookie(
        SESSION_COOKIE,
        user.session_token,
        max_age=int(settings.session_absolute_days * 86400),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return _session_out(settings, user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, response: Response, db: DbSession, context: Context) -> None:
    service.logout(db, user, context)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me")
def me(user: CurrentUser, settings: SettingsDep) -> SessionOut:
    return _session_out(settings, user)


@router.post("/auth/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InvitationRequest,
    admin: AdminUser,
    db: DbSession,
    settings: SettingsDep,
    context: Context,
) -> InvitationOut:
    invitation, token = service.create_invitation(
        db, actor=admin, role=body.role, expires_in_hours=body.expires_in_hours, context=context
    )
    return InvitationOut(
        id=invitation.id,
        role=body.role,
        expires_at=invitation.expires_at,
        invite_url=f"{settings.base_url}/invite#{token}",
    )


@router.post("/auth/invitations/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(body: AcceptInvitationRequest, db: DbSession, context: Context) -> UserOut:
    user = service.accept_invitation(
        db,
        token=body.token,
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        preferred_locale=body.locale,
        context=context,
    )
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/auth/password-reset", status_code=status.HTTP_204_NO_CONTENT)
def use_password_reset(body: PasswordResetUseRequest, db: DbSession, context: Context) -> None:
    service.use_password_reset(db, token=body.token, new_password=body.password, context=context)


@router.post("/admin/users/{user_id}/password-reset", status_code=status.HTTP_201_CREATED)
def create_password_reset(
    user_id: uuid.UUID, admin: AdminUser, db: DbSession, settings: SettingsDep, context: Context
) -> PasswordResetOut:
    reset, token = service.create_password_reset(
        db, settings, actor=admin, user_id=user_id, context=context
    )
    return PasswordResetOut(
        reset_url=f"{settings.base_url}/reset-password#{token}", expires_at=reset.expires_at
    )


@router.post("/admin/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def grant_role(
    user_id: uuid.UUID, body: RoleGrantRequest, admin: AdminUser, db: DbSession, context: Context
) -> None:
    service.grant_role(
        db, actor=admin, user_id=user_id, role=body.role, scope=body.scope, context=context
    )


@router.delete("/admin/users/{user_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_role(
    user_id: uuid.UUID, role: Role, admin: AdminUser, db: DbSession, context: Context
) -> None:
    service.revoke_role(db, actor=admin, user_id=user_id, role=role, context=context)


@router.post("/admin/users/{user_id}/sessions/revoke")
def revoke_sessions(
    user_id: uuid.UUID, admin: AdminUser, db: DbSession, context: Context
) -> RevokedSessionsOut:
    count = service.revoke_all_sessions(db, actor=admin, user_id=user_id, context=context)
    return RevokedSessionsOut(revoked=count)
