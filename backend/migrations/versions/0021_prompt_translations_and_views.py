"""Prompt meanings in Hindi and English, and which prompts each person has already seen (ADR-036).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-25

- prompts.translation_hi and prompts.translation_en: what the prompt means, shown under it so a
  reader knows what they are saying. Optional; the prompt text itself stays the original.
- prompt_views: one row per person and prompt the app has shown them, so "show another" does
  not bring the same prompt back. Rows go when the person has seen every prompt of a kind and
  the app starts again from the beginning.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE prompts "
        "ADD COLUMN translation_hi text CONSTRAINT ck_prompts_translation_hi_length "
        "CHECK (length(translation_hi) BETWEEN 1 AND 1000), "
        "ADD COLUMN translation_en text CONSTRAINT ck_prompts_translation_en_length "
        "CHECK (length(translation_en) BETWEEN 1 AND 1000)"
    )
    op.execute(
        """
        CREATE TABLE prompt_views (
          user_id        uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
          prompt_key     text NOT NULL,
          first_shown_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, prompt_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE prompt_views")
    op.execute("ALTER TABLE prompts DROP COLUMN translation_en, DROP COLUMN translation_hi")
