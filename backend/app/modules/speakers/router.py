"""Speaker profiles and restricted identity details (docs/API_SPECIFICATION.md §3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.db import DbSession
from app.modules.consents import service as consents
from app.modules.identity.deps import Context, CurrentUser, SettingsDep
from app.modules.identity.service import AuthenticatedUser
from app.modules.speakers import service
from app.modules.speakers.crypto import IdentityCipher, identity_cipher
from app.modules.speakers.models import Speaker
from app.modules.speakers.schemas import (
    IdentityOut,
    IdentityRequest,
    SpeakerCreateRequest,
    SpeakerListOut,
    SpeakerOut,
    SpeakerUpdateRequest,
)

router = APIRouter(tags=["speakers"])


def get_identity_cipher(settings: SettingsDep) -> IdentityCipher:
    return identity_cipher(settings)


Cipher = Annotated[IdentityCipher, Depends(get_identity_cipher)]


def _out(speaker: Speaker, user: AuthenticatedUser, with_consent: set[uuid.UUID]) -> SpeakerOut:
    return SpeakerOut(
        id=speaker.id,
        speaker_code=speaker.speaker_code,
        is_self=speaker.linked_user_id == user.id,
        status=speaker.status,
        has_active_consent=speaker.id in with_consent,
        demographics_consented=speaker.demographics_consented,
        dialect_label=speaker.dialect_label,
        age_band=speaker.age_band,
        gender=speaker.gender,
        first_language=speaker.first_language,
        other_languages=speaker.other_languages,
        region_coarse=speaker.region_coarse,
        created_at=speaker.created_at,
    )


def _single(db: DbSession, speaker: Speaker, user: AuthenticatedUser) -> SpeakerOut:
    return _out(speaker, user, consents.speakers_with_active_consent(db, [speaker.id]))


@router.post("/speakers", status_code=status.HTTP_201_CREATED)
def create_speaker(
    body: SpeakerCreateRequest, user: CurrentUser, db: DbSession, context: Context
) -> SpeakerOut:
    speaker = service.create_speaker(
        db, actor=user, for_self=body.for_self, dialect_label=body.dialect_label, context=context
    )
    return _single(db, speaker, user)


@router.get("/speakers")
def list_speakers(user: CurrentUser, db: DbSession, mine: bool = True) -> SpeakerListOut:
    """Speakers you created or that are you. Admins may pass mine=false to list everyone."""
    found = service.list_speakers(db, user, mine=mine)
    with_consent = consents.speakers_with_active_consent(db, (s.id for s in found))
    return SpeakerListOut(items=[_out(s, user, with_consent) for s in found])


@router.get("/speakers/{speaker_id}")
def get_speaker(speaker_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SpeakerOut:
    return _single(db, service.get_visible(db, user, speaker_id), user)


@router.patch("/speakers/{speaker_id}")
def update_speaker(
    speaker_id: uuid.UUID,
    body: SpeakerUpdateRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    context: Context,
) -> SpeakerOut:
    speaker = service.update_speaker(
        db,
        actor=user,
        speaker_id=speaker_id,
        changes=body.model_dump(exclude_unset=True),
        settings=settings,
        context=context,
    )
    return _single(db, speaker, user)


@router.get("/speakers/{speaker_id}/identity")
def read_identity(
    speaker_id: uuid.UUID, user: CurrentUser, db: DbSession, cipher: Cipher, context: Context
) -> IdentityOut:
    values, row = service.read_identity(
        db, cipher, actor=user, speaker_id=speaker_id, context=context
    )
    return IdentityOut(**values, updated_at=row.updated_at if row else None)


@router.put("/speakers/{speaker_id}/identity")
def write_identity(
    speaker_id: uuid.UUID,
    body: IdentityRequest,
    user: CurrentUser,
    db: DbSession,
    cipher: Cipher,
    context: Context,
) -> IdentityOut:
    values = body.model_dump()
    row = service.write_identity(
        db, cipher, actor=user, speaker_id=speaker_id, values=values, context=context
    )
    return IdentityOut(**values, updated_at=row.updated_at)
