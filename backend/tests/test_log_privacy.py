"""Personal data and secrets never reach the logs (docs/OBSERVABILITY_AND_BACKUPS.md §1)."""

import io
import logging
from collections.abc import Iterator

import pytest

from app import db, log_privacy
from app.log_privacy import MASK, RedactingFilter, redact


@pytest.fixture
def captured() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(log_privacy.LOG_FORMAT))
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("lokdhara.test.privacy")
    logger.addHandler(handler)
    logger.propagate = False
    yield logger, stream
    logger.removeHandler(handler)


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ("sign-in failed for asha@example.org", "sign-in failed for"),
        ("client 203.0.113.7 throttled", "client"),
        ("client 2001:db8::1 throttled", "client"),
        ("client ::ffff:10.0.0.1 throttled", "client"),
        ("password=hunter2 rejected", "rejected"),
        ('{"password": "hunter2"}', "password"),
        ("X-CSRF-Token: 6f1c9e", "X-CSRF-Token"),
        ("Cookie: lkd_session=abc123", "Cookie"),
        ("Authorization: Bearer eyJhbGciOi.abc", "Authorization"),
        ("GET /storage/originals/x?exp=1&sig=deadbeef", "exp=1"),
        ("LKD_SECRET_KEY=s3cret", "LKD_SECRET_KEY"),
    ],
)
def test_sensitive_values_are_masked(line: str, kept: str) -> None:
    cleaned = redact(line)
    assert MASK in cleaned
    assert kept in cleaned
    for secret in ("asha@", "203.0.113.7", "2001:db8", "10.0.0.1", "hunter2", "6f1c9e"):
        assert secret not in cleaned
    for secret in ("abc123", "eyJhbGciOi", "deadbeef", "s3cret"):
        assert secret not in cleaned


@pytest.mark.parametrize(
    "line",
    [
        "job audio.analyze succeeded in 12:30:45",
        "migration 0017_user_mfa applied",
        "recording 0192f0c4-7d1e-7a3b-9c2d-5e6f7a8b9c0d promoted",
        "worker started",
    ],
)
def test_ordinary_lines_are_left_alone(line: str) -> None:
    assert redact(line) == line


def test_arguments_and_tracebacks_are_masked(
    captured: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = captured
    logger.warning("login for %s from %s failed %d times", "asha@example.org", "203.0.113.7", 3)
    try:
        raise ValueError("token=abcdef for asha@example.org")
    except ValueError:
        logger.exception("upload failed")
    written = stream.getvalue()
    assert "failed 3 times" in written
    assert "ValueError" in written
    for secret in ("asha@example.org", "203.0.113.7", "abcdef"):
        assert secret not in written


def test_installing_twice_adds_one_filter() -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        log_privacy.install()
        log_privacy.install()
        assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
    finally:
        root.removeHandler(handler)


def test_database_errors_do_not_include_the_values_sent() -> None:
    assert db.get_engine().hide_parameters
