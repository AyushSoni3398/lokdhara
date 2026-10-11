import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.security import PASSWORD_MAX_LENGTH

Role = Literal["contributor", "facilitator", "reviewer", "researcher", "admin"]
Locale = Literal["hi", "en"]
Password = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Password


class GrantOut(BaseModel):
    role: Role
    scope: str | None


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    preferred_locale: Locale


class SessionOut(BaseModel):
    user: UserOut
    roles: list[GrantOut]
    csrf_token: str


class InvitationRequest(BaseModel):
    role: Role
    expires_in_hours: int = Field(default=72, gt=0, le=24 * 30)


class InvitationOut(BaseModel):
    id: uuid.UUID
    role: Role
    expires_at: datetime
    invite_url: str  # contains the token; shown once


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Password
    locale: Locale = "hi"


class RoleGrantRequest(BaseModel):
    role: Role
    scope: Literal["culturally_restricted"] | None = None


class PasswordResetOut(BaseModel):
    reset_url: str  # contains the token; shown once
    expires_at: datetime


class PasswordResetUseRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Password


class RevokedSessionsOut(BaseModel):
    revoked: int
