"""Keeps personal data and secrets out of the logs (docs/OBSERVABILITY_AND_BACKUPS.md §1).

Log lines go to the server's disk and to whoever reads them, so addresses, emails and secret
values are masked before any handler writes a record, whichever code logged it.
"""

import logging
import re
from typing import Any

MASK = "[redacted]"
# Uvicorn's own loggers do not propagate to the root logger, so their handlers are filtered too.
LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

_SECRET_VALUE = re.compile(
    r"(?i)(\b[\w-]*(?:password|passwd|token|secret|cookie|session|csrf|authorization"
    r"|api[_-]?key|sig)[\w-]*[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s\"'&,;]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[\w.~+/-]+=*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_HEX = r"[0-9A-Fa-f]{1,4}"
# At least three colons, or a "::", so clock times like 12:30:45 are left alone.
_IPV6 = re.compile(
    rf"(?<![\w:])(?:(?:{_HEX}:){{3,7}}{_HEX}|(?:{_HEX}(?::{_HEX})*)?::(?:{_HEX}(?::{_HEX})*)?)"
    r"(?![\w:])"
)


def redact(text: str) -> str:
    text = _SECRET_VALUE.sub(rf"\1{MASK}", text)
    text = _BEARER.sub(MASK, text)
    text = _EMAIL.sub(MASK, text)
    text = _IPV6.sub(MASK, text)
    return _IPV4.sub(MASK, text)


def _redact_arg(value: Any) -> Any:
    if isinstance(value, (int, float)) or value is None:
        return value
    text = str(value)
    cleaned = redact(text)
    # Unchanged values keep their type, so format strings like %d still work.
    return value if cleaned == text else cleaned


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: _redact_arg(value) for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(value) for value in record.args)
        if record.exc_info and not record.exc_text:
            # Formatters reuse exc_text, so the traceback is written already masked.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install() -> None:
    """Masks every handler of the root and uvicorn loggers; safe to call more than once."""
    for name in LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(RedactingFilter())


def configure(level: str) -> None:
    """Gives the root logger a handler (once) and masks what every handler writes."""
    logging.basicConfig(level=level, format=LOG_FORMAT)
    install()
