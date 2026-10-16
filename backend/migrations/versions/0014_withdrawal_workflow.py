"""The withdrawal workflow: a speaker takes their recordings back (ROADMAP M7 part 2).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-16

`withdrawal_requests` (created by 0004) gets what the workflow needs: every request names its
speaker, a request for one item names that submission, a short note from whoever logged it,
and `erased_at` for when the deletion routine finished. Who logged it and what was asked never
change afterwards. Recordings whose files the routine deleted are marked `erased`; their rows
stay so release manifests can still be read. A draft release can name the release it replaces,
which is how a PATCH release leaves withdrawn items out (docs/DATASET_VERSIONING.md §2).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES = (
    "'system.ping', 'audio.validate', 'audio.analyze', 'audio.renditions', 'audio.dedupe', "
    "'text.derive', 'dataset.export', 'cleanup.quarantine', 'cleanup.expire_drafts', "
    "'cleanup.expire_exports'"
)
_UPLOAD_STATUSES = "'quarantined', 'validated', 'rejected_invalid', 'promoted', 'expired'"
_FROZEN = (
    "'id', 'speaker_id', 'submission_id', 'received_via', 'received_at', 'recorded_by', "
    "'requested_scope', 'note'"
)


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
    _job_types(f"{_JOB_TYPES}, 'withdrawal.erase'")
    _upload_statuses(f"{_UPLOAD_STATUSES}, 'erased'")

    # Nothing wrote withdrawal requests before this migration, so the table is empty.
    op.execute("ALTER TABLE withdrawal_requests ALTER COLUMN speaker_id SET NOT NULL")
    op.execute(
        "ALTER TABLE withdrawal_requests "
        "ADD COLUMN note text CONSTRAINT ck_withdrawal_requests_note_length "
        "CHECK (char_length(note) <= 1000), "
        "ADD COLUMN erased_at timestamptz"
    )
    op.execute(
        """
        ALTER TABLE withdrawal_requests
          ADD CONSTRAINT ck_withdrawal_requests_item_scope
            CHECK ((requested_scope = 'specific_items') = (submission_id IS NOT NULL)),
          ADD CONSTRAINT ck_withdrawal_requests_verified
            CHECK ((status IN ('verified', 'in_progress', 'completed'))
                     = (verified_by IS NOT NULL)
                   AND (verified_by IS NULL) = (verified_at IS NULL)),
          ADD CONSTRAINT ck_withdrawal_requests_completed
            CHECK ((status IN ('completed', 'rejected')) = (completed_at IS NOT NULL)),
          ADD CONSTRAINT ck_withdrawal_requests_erased_after_verified
            CHECK (erased_at IS NULL OR verified_at IS NOT NULL)
        """
    )
    # One waiting request per speaker and item; asking again after a decision is allowed.
    op.execute(
        "CREATE UNIQUE INDEX uq_withdrawal_requests_waiting ON withdrawal_requests "
        "(speaker_id, coalesce(submission_id, '00000000-0000-0000-0000-000000000000'::uuid), "
        "requested_scope) WHERE status = 'received'"
    )
    op.execute("CREATE INDEX ix_withdrawal_requests_speaker ON withdrawal_requests (speaker_id)")
    op.execute(
        "CREATE TRIGGER withdrawal_requests_frozen BEFORE UPDATE OR DELETE ON withdrawal_requests "
        f"FOR EACH ROW EXECUTE FUNCTION lkd_freeze_columns({_FROZEN})"
    )

    op.execute(
        "ALTER TABLE dataset_releases ADD COLUMN replaces_id uuid REFERENCES dataset_releases (id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE dataset_releases DROP COLUMN replaces_id")
    op.execute("DROP TRIGGER withdrawal_requests_frozen ON withdrawal_requests")
    op.execute("DROP INDEX ix_withdrawal_requests_speaker")
    op.execute("DROP INDEX uq_withdrawal_requests_waiting")
    op.execute(
        """
        ALTER TABLE withdrawal_requests
          DROP CONSTRAINT ck_withdrawal_requests_erased_after_verified,
          DROP CONSTRAINT ck_withdrawal_requests_completed,
          DROP CONSTRAINT ck_withdrawal_requests_verified,
          DROP CONSTRAINT ck_withdrawal_requests_item_scope,
          DROP COLUMN erased_at,
          DROP COLUMN note
        """
    )
    op.execute("ALTER TABLE withdrawal_requests ALTER COLUMN speaker_id DROP NOT NULL")
    op.execute("DELETE FROM jobs WHERE job_type = 'withdrawal.erase'")
    # processing_runs is append-only, so its past runs stay and so does their job type.
    _job_types(_JOB_TYPES, tables=("jobs",))
    # Erased recordings have no files left; `expired` is the nearest earlier status.
    op.execute("UPDATE recordings SET upload_status = 'expired' WHERE upload_status = 'erased'")
    _upload_statuses(_UPLOAD_STATUSES)
