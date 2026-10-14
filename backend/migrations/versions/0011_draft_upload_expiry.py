"""Remove the audio of drafts left unsent for 30 days (Q-T7), keeping the draft itself.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-14

A recording uploaded to a draft waits in quarantine until the draft is submitted. The new
`cleanup.expire_drafts` job deletes that copy once it has waited `LKD_DRAFT_UPLOAD_RETENTION_DAYS`
and marks the recording `expired`. `quarantined_at` says when the bytes were last stored, so a
draft whose audio is uploaded again gets the full period again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES = (
    "'system.ping', 'audio.validate', 'audio.analyze', 'audio.renditions', 'audio.dedupe', "
    "'text.derive', 'dataset.export', 'cleanup.quarantine'"
)
_UPLOAD_STATUSES = "'quarantined', 'validated', 'rejected_invalid', 'promoted'"


def _job_types(job_types: str, tables: tuple[str, ...] = ("jobs", "processing_runs")) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_job_type")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_job_type "
            f"CHECK (job_type IN ({job_types}))"
        )


def _upload_statuses(statuses: str) -> None:
    op.execute("ALTER TABLE recordings DROP CONSTRAINT ck_recordings_upload_status")
    op.execute(
        "ALTER TABLE recordings ADD CONSTRAINT ck_recordings_upload_status "
        f"CHECK (upload_status IN ({statuses}))"
    )


def upgrade() -> None:
    _job_types(f"{_JOB_TYPES}, 'cleanup.expire_drafts'")
    _upload_statuses(f"{_UPLOAD_STATUSES}, 'expired'")
    op.execute("ALTER TABLE recordings ADD COLUMN quarantined_at timestamptz")
    op.execute("UPDATE recordings SET quarantined_at = created_at")
    op.execute(
        "ALTER TABLE recordings ALTER COLUMN quarantined_at SET NOT NULL, "
        "ALTER COLUMN quarantined_at SET DEFAULT now()"
    )
    op.execute(
        "CREATE INDEX ix_recordings_quarantined_at ON recordings (quarantined_at) "
        "WHERE upload_status = 'quarantined'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_recordings_quarantined_at")
    op.execute("ALTER TABLE recordings DROP COLUMN quarantined_at")
    # The audio of an expired recording is gone; back to rejected is the closest old state.
    op.execute(
        "UPDATE recordings SET upload_status = 'rejected_invalid' WHERE upload_status = 'expired'"
    )
    _upload_statuses(_UPLOAD_STATUSES)
    op.execute("DELETE FROM jobs WHERE job_type = 'cleanup.expire_drafts'")
    # processing_runs is append-only, so its past sweep runs stay and so does their job type.
    _job_types(_JOB_TYPES, tables=("jobs",))
