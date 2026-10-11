"""Identity: users, role grants, invitations, password resets, sessions, login throttle.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11

Raw tokens are never stored; only SHA-256 hashes. See docs/DATABASE_SCHEMA.md §1.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "role IN ('contributor', 'facilitator', 'reviewer', 'researcher', 'admin')"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
          id               uuid PRIMARY KEY DEFAULT uuidv7(),
          username         text NOT NULL
                           CONSTRAINT ck_users_username_format
                           CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,39}$'),
          display_name     text NOT NULL
                           CONSTRAINT ck_users_display_name_length
                           CHECK (char_length(display_name) BETWEEN 1 AND 80),
          email            text,
          phone            text,
          password_hash    text NOT NULL,
          status           text NOT NULL DEFAULT 'active'
                           CONSTRAINT ck_users_status
                           CHECK (status IN ('invited', 'active', 'suspended', 'deactivated')),
          preferred_locale text NOT NULL DEFAULT 'hi'
                           CONSTRAINT ck_users_preferred_locale
                           CHECK (preferred_locale IN ('hi', 'en')),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          last_login_at    timestamptz
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_users_username ON users (username)")
    op.execute("CREATE UNIQUE INDEX uq_users_email ON users (lower(email)) WHERE email IS NOT NULL")

    op.execute(
        f"""
        CREATE TABLE user_roles (
          user_id    uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
          role       text NOT NULL CONSTRAINT ck_user_roles_role CHECK ({ROLE_CHECK}),
          granted_at timestamptz NOT NULL DEFAULT now(),
          scope      text,
          granted_by uuid REFERENCES users (id),
          revoked_at timestamptz,
          revoked_by uuid REFERENCES users (id),
          CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role, granted_at)
        )
        """
    )
    # At most one active grant per (user, role, scope).
    op.execute(
        "CREATE UNIQUE INDEX uq_user_roles_active ON user_roles "
        "(user_id, role, coalesce(scope, '')) WHERE revoked_at IS NULL"
    )

    op.execute(
        f"""
        CREATE TABLE invitations (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          token_hash  text NOT NULL CONSTRAINT uq_invitations_token_hash UNIQUE,
          role        text NOT NULL CONSTRAINT ck_invitations_role CHECK ({ROLE_CHECK}),
          created_by  uuid NOT NULL REFERENCES users (id),
          created_at  timestamptz NOT NULL DEFAULT now(),
          expires_at  timestamptz NOT NULL,
          accepted_by uuid REFERENCES users (id),
          accepted_at timestamptz,
          revoked_at  timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE password_resets (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          user_id    uuid NOT NULL REFERENCES users (id),
          token_hash text NOT NULL CONSTRAINT uq_password_resets_token_hash UNIQUE,
          created_by uuid NOT NULL REFERENCES users (id),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          used_at    timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE sessions (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          user_id         uuid NOT NULL REFERENCES users (id),
          token_hash      text NOT NULL CONSTRAINT uq_sessions_token_hash UNIQUE,
          created_at      timestamptz NOT NULL DEFAULT now(),
          last_seen_at    timestamptz NOT NULL DEFAULT now(),
          expires_at      timestamptz NOT NULL,
          revoked_at      timestamptz,
          user_agent_hash text,
          ip_hash         text
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE login_throttle (
          key_hash          text PRIMARY KEY,
          failures          integer NOT NULL DEFAULT 0,
          window_started_at timestamptz NOT NULL DEFAULT now(),
          locked_until      timestamptz
        )
        """
    )


def downgrade() -> None:
    for table in (
        "login_throttle",
        "sessions",
        "password_resets",
        "invitations",
        "user_roles",
        "users",
    ):
        op.execute(f"DROP TABLE {table}")
