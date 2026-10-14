"""Deletes the audio of drafts that were never submitted (Q-T7, docs/DATA_LIFECYCLE.md stage 2).

A recording uploaded to a draft waits in quarantine until the draft is submitted. After
`draft_upload_retention_days` without that, `cleanup.expire_drafts` deletes the quarantine copy
and marks the recording `expired`. The draft and its text stay: the contributor's phone keeps
the recording until the draft is sent, and uploading it again restores the same recording
(app.modules.submissions.uploads). The worker queues this job every hour
(app.modules.processing.schedule).
"""

from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.modules.processing.queue import JobContext, JobResult, handler, utcnow
from app.modules.submissions.models import Recording, Submission
from app.object_store import Bucket, get_object_store

# Per run; anything left over is picked up by the next hourly run.
BATCH_SIZE = 500


@handler("cleanup.expire_drafts")
def expire_draft_uploads(context: JobContext) -> JobResult:
    settings, store, db = get_settings(), get_object_store(), context.db
    cutoff = utcnow() - timedelta(days=settings.draft_upload_retention_days)
    # Locking the submission keeps this from racing a submit or an upload of the same draft;
    # drafts being worked on right now are skipped and looked at again next time.
    stale = db.scalars(
        select(Recording)
        .join(Submission, Submission.id == Recording.submission_id)
        .where(
            Recording.upload_status == "quarantined",
            Recording.quarantined_at < cutoff,
            Submission.status == "draft",
        )
        .order_by(Recording.quarantined_at)
        .limit(BATCH_SIZE)
        .with_for_update(of=(Recording, Submission), skip_locked=True)
    ).all()
    for recording in stale:
        store.delete(Bucket.QUARANTINE, recording.original_object_key)
        recording.upload_status = "expired"
    return JobResult(
        output_summary={
            "expired": len(stale),
            "retention_days": settings.draft_upload_retention_days,
        }
    )
