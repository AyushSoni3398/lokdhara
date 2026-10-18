"""Two-step sign-in for admins: an authenticator app code after the password (M8).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-18

`user_mfa` holds one TOTP secret per user, encrypted by the app (AES-256-GCM, like speaker
identities). It counts only once confirmed with a first code. `last_used_step` stops the same
code from being used twice. `mfa_recovery_codes` holds keyed hashes of one-time codes for a
lost phone; a used code is marked, never deleted, so it cannot be used again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_mfa (
          user_id         uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
          secret_enc      bytea NOT NULL,
          key_version     integer NOT NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          confirmed_at    timestamptz,
          last_used_step  bigint NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        """
        CREATE TABLE mfa_recovery_codes (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          user_id     uuid NOT NULL REFERENCES user_mfa (user_id) ON DELETE CASCADE,
          code_hash   text NOT NULL,
          used_at     timestamptz
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_mfa_recovery_codes_hash ON mfa_recovery_codes (code_hash)")
    op.execute("CREATE INDEX ix_mfa_recovery_codes_user ON mfa_recovery_codes (user_id)")
    # Secrets are for signing in only: the reporting role cannot read them. The backup role
    # can, because a restored database must still let admins sign in.
    op.execute("REVOKE ALL ON user_mfa, mfa_recovery_codes FROM app_readonly")


def downgrade() -> None:
    op.execute("DROP TABLE mfa_recovery_codes")
    op.execute("DROP TABLE user_mfa")
