"""The daily digest job: a summary of the service sent to the maintainers (M8).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES = (
    "'system.ping', 'audio.validate', 'audio.analyze', 'audio.renditions', 'audio.dedupe', "
    "'text.derive', 'dataset.export', 'cleanup.quarantine', 'cleanup.expire_drafts', "
    "'cleanup.expire_exports', 'withdrawal.erase'"
)


def _job_types(job_types: str, tables: tuple[str, ...] = ("jobs", "processing_runs")) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_job_type")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_job_type "
            f"CHECK (job_type IN ({job_types}))"
        )


def upgrade() -> None:
    _job_types(f"{_JOB_TYPES}, 'ops.digest'")


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE job_type = 'ops.digest'")
    # processing_runs is append-only, so its past runs stay and so does their job type.
    _job_types(_JOB_TYPES, tables=("jobs",))
