"""Password hashing, opaque tokens, and keyed hashes. No secrets or raw tokens are logged."""

import hashlib
import hmac
import os
import secrets
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults follow RFC 9106's second recommended profile (Argon2id).
_hasher = PasswordHasher()
# Verified against when the username is unknown, so response time does not reveal accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
# Each hash uses 64 MiB and a core for about 0.25 s. Without a limit, a burst of sign-ins runs
# one per request thread (40 per API process): gigabytes of memory on a 4 GB server, and no
# CPU left for other requests. Extra sign-ins wait their turn instead (docs/LOAD_TESTING.md).
_hash_slots = threading.BoundedSemaphore(os.process_cpu_count() or 1)

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 256


def hash_password(password: str) -> str:
    with _hash_slots:
        return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        with _hash_slots:
            verified = _hasher.verify(password_hash or _DUMMY_HASH, password)
        return verified and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """256-bit random URL-safe token for sessions, invitations, and resets."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Stored instead of the token itself."""
    return hashlib.sha256(token.encode()).hexdigest()


def keyed_hash(secret_key: str, purpose: str, value: str) -> str:
    """HMAC used for IP/user-agent hashes, throttle keys, and CSRF tokens."""
    message = f"{purpose}:{value}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
