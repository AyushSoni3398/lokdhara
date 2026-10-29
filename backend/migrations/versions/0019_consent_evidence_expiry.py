"""The daily job that deletes proof of consent one month after a withdrawal (Q-G8).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES = (
    "'system.ping', 'audio.validate', 'audio.analyze', 'audio.renditions', 'audio.dedupe', "
    "'text.derive', 'dataset.export', 'cleanup.quarantine', 'cleanup.expire_drafts', "
    "'cleanup.expire_exports', 'withdrawal.erase', 'ops.digest'"
)


def _job_types(job_types: str, tables: tuple[str, ...] = ("jobs", "processing_runs")) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_job_type")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_job_type "
            f"CHECK (job_type IN ({job_types}))"
        )


def upgrade() -> None:
    _job_types(f"{_JOB_TYPES}, 'withdrawal.expire_consent_evidence'")


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE job_type = 'withdrawal.expire_consent_evidence'")
    # processing_runs is append-only, so its past runs stay and so does their job type.
    _job_types(_JOB_TYPES, tables=("jobs",))
