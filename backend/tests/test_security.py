from app.security import (
    constant_time_equals,
    hash_password,
    keyed_hash,
    new_token,
    token_hash,
    verify_password,
)


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("a long passphrase")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a long passphrase")
    assert not verify_password(hashed, "a long passphrasE")


def test_unknown_user_never_verifies() -> None:
    assert not verify_password(None, "anything at all")


def test_corrupt_hash_does_not_raise() -> None:
    assert not verify_password("not-a-hash", "anything at all")


def test_tokens_are_random_and_stored_hashed() -> None:
    first, second = new_token(), new_token()
    assert first != second
    assert len(first) >= 43  # 32 random bytes, base64url
    assert token_hash(first) != first
    assert len(token_hash(first)) == 64


def test_keyed_hash_depends_on_key_and_purpose() -> None:
    base = keyed_hash("key-one", "ip", "203.0.113.7")
    assert base != keyed_hash("key-two", "ip", "203.0.113.7")
    assert base != keyed_hash("key-one", "ua", "203.0.113.7")
    assert "203.0.113.7" not in base
    assert constant_time_equals(base, keyed_hash("key-one", "ip", "203.0.113.7"))
