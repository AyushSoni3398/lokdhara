"""Two-step sign-in with an authenticator app (TOTP, RFC 6238) and one-time recovery codes.

The secret is 20 random bytes, shown once as a QR code and as base32 text for apps that cannot
scan. It is stored encrypted with a key derived from LKD_IDENTITY_ENCRYPTION_KEY, bound to the
user, so a database copy alone does not let anyone make codes. A code is accepted for the
30-second step before and after the current one (phone clocks drift), and never twice.
"""

import base64
import hashlib
import hmac
import io
import os
import secrets
import struct
import uuid
from datetime import datetime
from urllib.parse import quote

import segno
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings
from app.security import keyed_hash

STEP_SECONDS = 30
DIGITS = 6
ISSUER = "Lokdhara"
RECOVERY_CODES = 10
KEY_VERSION = 1
_NONCE_BYTES = 12
# Unambiguous letters and digits for recovery codes: no 0/O, 1/I/L.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_secret() -> bytes:
    return os.urandom(20)


def secret_text(secret: bytes) -> str:
    """Base32 without padding, as authenticator apps expect when the key is typed."""
    return base64.b32encode(secret).decode().rstrip("=")


def step_at(moment: datetime) -> int:
    return int(moment.timestamp()) // STEP_SECONDS


def code_for(secret: bytes, step: int) -> str:
    """RFC 4226 HOTP for the given time step."""
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def matching_step(secret: bytes, code: str, moment: datetime, last_used_step: int) -> int | None:
    """The step `code` belongs to, if it is current (±1 step) and newer than the last one used."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = step_at(moment)
    for step in (now - 1, now, now + 1):
        if step > last_used_step and hmac.compare_digest(code_for(secret, step), code):
            return step
    return None


def provisioning_uri(secret: bytes, username: str) -> str:
    label = quote(f"{ISSUER}:{username}")
    return (
        f"otpauth://totp/{label}?secret={secret_text(secret)}&issuer={ISSUER}"
        f"&digits={DIGITS}&period={STEP_SECONDS}"
    )


def qr_svg(uri: str) -> str:
    """The provisioning link as an SVG QR code, made on the server (no third-party service)."""
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", scale=5, border=2, xmldecl=False)
    return buffer.getvalue().decode()


def new_recovery_codes() -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"

    return [one() for _ in range(RECOVERY_CODES)]


def normalize_recovery_code(code: str) -> str:
    return code.strip().upper().replace(" ", "").replace("-", "")


def recovery_code_hash(settings: Settings, code: str) -> str:
    """Codes have 49 bits of randomness, so a keyed hash is enough (no slow password hash)."""
    return keyed_hash(
        settings.secret_key.get_secret_value(), "mfa-recovery", normalize_recovery_code(code)
    )


class MfaSecretError(Exception):
    """The stored secret was tampered with, moved, or encrypted under another key."""


class MfaCipher:
    def __init__(self, settings: Settings) -> None:
        base = settings.identity_key_bytes() or settings.secret_key.get_secret_value().encode()
        key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"lokdhara mfa key v1"
        ).derive(base)
        self._aead = AESGCM(key)

    @staticmethod
    def _associated_data(user_id: uuid.UUID) -> bytes:
        return f"user_mfa:secret:{user_id}:v{KEY_VERSION}".encode()

    def encrypt(self, user_id: uuid.UUID, secret: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, secret, self._associated_data(user_id))

    def decrypt(self, user_id: uuid.UUID, value: bytes) -> bytes:
        try:
            return self._aead.decrypt(
                value[:_NONCE_BYTES], value[_NONCE_BYTES:], self._associated_data(user_id)
            )
        except InvalidTag as exc:
            raise MfaSecretError("two-step sign-in secret failed authentication") from exc
