"""Job handlers. Importing this module registers every handler with the queue."""

from app.modules.ops import digest  # noqa: F401 - ops.digest
from app.modules.processing.queue import JobContext, JobResult, handler
from app.modules.releases import export_job  # noqa: F401 - dataset.export, cleanup.expire_exports
from app.modules.submissions import (
    expiry,  # noqa: F401 - cleanup.expire_drafts
    processing,  # noqa: F401 - audio.*, cleanup.quarantine
    service,  # noqa: F401 - moves submissions on as their jobs settle
    text_processing,  # noqa: F401 - text.derive
)
from app.modules.withdrawals import erasure  # noqa: F401 - withdrawal.erase and its follow-up


@handler("system.ping")
def ping(context: JobContext) -> JobResult:
    """Proves the queue → worker → processing_runs path works (used by `app.cli ping-worker`)."""
    return JobResult(output_summary={"pong": True, "attempt": context.attempt})
