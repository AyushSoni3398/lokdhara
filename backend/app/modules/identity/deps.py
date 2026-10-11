"""Request dependencies: request context, the signed-in user, CSRF, and role checks."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.db import DbSession
from app.errors import ApiError
from app.modules.audit.service import RequestContext
from app.modules.identity import service
from app.modules.identity.service import AuthenticatedUser
from app.security import constant_time_equals, keyed_hash

SESSION_COOKIE = "lkd_session"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SettingsDep = Annotated[Settings, Depends(get_settings)]


def csrf_token_for(settings: Settings, session_token: str) -> str:
    """Bound to the session, so it cannot be reused with another session."""
    return keyed_hash(settings.secret_key.get_secret_value(), "csrf", session_token)


def request_context(request: Request, settings: SettingsDep) -> RequestContext:
    secret = settings.secret_key.get_secret_value()
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return RequestContext(
        request_id=uuid.uuid4(),
        ip_hash=keyed_hash(secret, "ip", ip) if ip else None,
        user_agent_hash=keyed_hash(secret, "ua", user_agent) if user_agent else None,
    )


Context = Annotated[RequestContext, Depends(request_context)]


def current_user(request: Request, db: DbSession, settings: SettingsDep) -> AuthenticatedUser:
    token = request.cookies.get(SESSION_COOKIE)
    user = service.resolve_session(db, settings, token) if token else None
    if user is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not constant_time_equals(sent, csrf_token_for(settings, user.session_token)):
            raise ApiError(403, "csrf_failed", "The request could not be verified.")
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]


def require_roles(*roles: str) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    def dependency(user: CurrentUser) -> AuthenticatedUser:
        if not user.has_role(*roles):
            raise ApiError(403, "forbidden", "You do not have permission for this action.")
        return user

    return dependency


AdminUser = Annotated[AuthenticatedUser, Depends(require_roles("admin"))]
