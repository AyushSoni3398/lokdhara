"""Database roles, the append-only guard, and the audit log.

Revision ID: 0001
Revises:
Create Date: 2026-10-11

Roles (docs/ACCESS_CONTROL.md §4) are NOLOGIN groups. Deployments create login roles and
grant membership: the API and worker log in as a member of app_rw, the withdrawal routine as a
member of app_erasure. Roles are cluster-wide, so downgrade revokes privileges but keeps them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("app_rw", "app_erasure", "app_readonly")


def upgrade() -> None:
    for role in ROLES:
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN;
              END IF;
            END $$
            """
        )
    op.execute("GRANT USAGE ON SCHEMA public TO app_rw, app_erasure, app_readonly")
    # Tables created later by the migration owner get these grants automatically.
    # No TRUNCATE for anyone: it would bypass the append-only row triggers.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw, app_erasure"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO app_readonly")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO app_rw, app_erasure"
    )

    # Append-only guard (ADR-009/011). UPDATE and DELETE are rejected unless the erasure
    # routine runs as a member of app_erasure AND has set lkd.erasure for its transaction.
    op.execute(
        """
        CREATE FUNCTION lkd_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF current_setting('lkd.erasure', true) = 'on'
             AND pg_has_role(current_user, 'app_erasure', 'MEMBER') THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'append_only: % on % is not allowed', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE audit_events (
          id            uuid PRIMARY KEY DEFAULT uuidv7(),
          occurred_at   timestamptz NOT NULL DEFAULT now(),
          actor_user_id uuid,
          actor_type    text NOT NULL
                        CONSTRAINT ck_audit_events_actor_type
                        CHECK (actor_type IN ('user', 'system', 'worker')),
          action        text NOT NULL,
          target_type   text,
          target_id     uuid,
          request_id    uuid,
          ip_hash       text,
          details       jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_events_target ON audit_events (target_type, target_id)")
    op.execute("CREATE INDEX ix_audit_events_actor ON audit_events (actor_user_id, occurred_at)")
    op.execute("CREATE INDEX ix_audit_events_action ON audit_events (action, occurred_at)")
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION lkd_reject_change()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events")
    op.execute("DROP FUNCTION lkd_reject_change()")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE ON SEQUENCES FROM app_rw, app_erasure"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM app_readonly"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_rw, app_erasure"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_rw, app_erasure, app_readonly")
