"""Two-step sign-in for admins (docs/ACCESS_CONTROL.md §4, ADR-025)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.modules.identity import mfa

RFC_SECRET = b"12345678901234567890"  # RFC 6238 appendix B, SHA-1


@pytest.mark.parametrize(
    ("unix_time", "code"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_codes_match_the_rfc_test_vectors(unix_time: int, code: str) -> None:
    assert mfa.code_for(RFC_SECRET, mfa.step_at(datetime.fromtimestamp(unix_time, UTC))) == code


def test_a_code_is_accepted_one_step_either_side_and_only_once() -> None:
    now = datetime.fromtimestamp(1111111109, UTC)
    step = mfa.step_at(now)
    for offset in (-1, 0, 1):
        code = mfa.code_for(RFC_SECRET, step + offset)
        assert mfa.matching_step(RFC_SECRET, code, now, 0) == step + offset
        assert mfa.matching_step(RFC_SECRET, code, now, step + offset) is None  # used
    assert mfa.matching_step(RFC_SECRET, mfa.code_for(RFC_SECRET, step + 2), now, 0) is None
    assert mfa.matching_step(RFC_SECRET, "081 804", now, 0) == step
    assert mfa.matching_step(RFC_SECRET, "08180", now, 0) is None
    assert mfa.matching_step(RFC_SECRET, "abcdef", now, 0) is None


def test_secrets_are_bound_to_their_user(settings: Settings) -> None:
    cipher, user = mfa.MfaCipher(settings), uuid.uuid4()
    sealed = cipher.encrypt(user, RFC_SECRET)
    assert cipher.decrypt(user, sealed) == RFC_SECRET
    with pytest.raises(mfa.MfaSecretError):
        cipher.decrypt(uuid.uuid4(), sealed)


def test_recovery_codes_are_readable_and_distinct() -> None:
    codes = mfa.new_recovery_codes()
    assert len(set(codes)) == 10
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    assert not set("".join(codes)) & set("01OIL")


def test_the_provisioning_link_and_qr_code() -> None:
    uri = mfa.provisioning_uri(RFC_SECRET, "asha")
    assert uri.startswith("otpauth://totp/Lokdhara%3Aasha?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert mfa.qr_svg(uri).startswith("<svg")
