"""Backups: a login role that can dump the database, and a row for every backup run (M8).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-18

The nightly backup (infra/prod/backup/backup.sh) logs in as a member of app_backup. That role
can read every table, speaker identities included (they are encrypted, and a restore needs
them), and can write nothing except its own `backup_runs` rows. A row is written once, when a
run ends, and never changed, so the admin status page can tell whether last night's backup
worked (docs/OBSERVABILITY_AND_BACKUPS.md §2).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_backup') THEN
            CREATE ROLE app_backup NOLOGIN;
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE backup_runs (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          kind         text NOT NULL CONSTRAINT ck_backup_runs_kind
                       CHECK (kind IN ('database', 'withdrawal_log')),
          started_at   timestamptz NOT NULL,
          finished_at  timestamptz NOT NULL DEFAULT now(),
          succeeded    boolean NOT NULL,
          size_bytes   bigint CONSTRAINT ck_backup_runs_size CHECK (size_bytes >= 0),
          file_name    text CONSTRAINT ck_backup_runs_file_name_length
                       CHECK (char_length(file_name) <= 200),
          detail       text CONSTRAINT ck_backup_runs_detail_length
                       CHECK (char_length(detail) <= 500),
          CONSTRAINT ck_backup_runs_finished_after_start CHECK (finished_at >= started_at),
          CONSTRAINT ck_backup_runs_success_has_file
            CHECK (NOT succeeded OR (file_name IS NOT NULL AND size_bytes IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ix_backup_runs_latest ON backup_runs (kind, finished_at DESC)")
    op.execute(
        "CREATE TRIGGER backup_runs_append_only BEFORE UPDATE OR DELETE ON backup_runs "
        "FOR EACH ROW EXECUTE FUNCTION lkd_reject_change()"
    )

    op.execute("GRANT USAGE ON SCHEMA public TO app_backup")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_backup")
    op.execute("GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO app_backup")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO app_backup")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO app_backup")
    op.execute("GRANT INSERT ON backup_runs TO app_backup")


def downgrade() -> None:
    op.execute("DROP TABLE backup_runs")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM app_backup"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM app_backup")
    op.execute("REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM app_backup")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM app_backup")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_backup")
