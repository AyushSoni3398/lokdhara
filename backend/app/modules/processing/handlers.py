"""Job handlers. Importing this module registers every handler with the queue."""

from app.modules.processing.queue import JobContext, JobResult, handler
from app.modules.submissions import (
    expiry,  # noqa: F401 - cleanup.expire_drafts
    processing,  # noqa: F401 - audio.*, cleanup.quarantine
    service,  # noqa: F401 - moves submissions on as their jobs settle
    text_processing,  # noqa: F401 - text.derive
)


@handler("system.ping")
def ping(context: JobContext) -> JobResult:
    """Proves the queue → worker → processing_runs path works (used by `app.cli ping-worker`)."""
    return JobResult(output_summary={"pong": True, "attempt": context.attempt})
