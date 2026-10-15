"""Reports: anyone who can see an item can tell the admins something is wrong with it (ADR-021).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-15

An admin answers a report by hiding the item with a restriction flag (a review event, as before)
or by dismissing it. A report is never deleted, and once decided only its decision is stored:
the reason and note the reporter wrote never change.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = "'personal_information', 'third_party_voice', 'culturally_restricted', 'wrong_content'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE reports (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          submission_id   uuid NOT NULL REFERENCES submissions (id),
          reported_by     uuid NOT NULL REFERENCES users (id),
          reason          text NOT NULL CONSTRAINT ck_reports_reason CHECK (reason IN ({REASONS})),
          note            text CONSTRAINT ck_reports_note_length CHECK (char_length(note) <= 1000),
          created_at      timestamptz NOT NULL DEFAULT now(),
          decision        text CONSTRAINT ck_reports_decision
                          CHECK (decision IN ('hidden', 'dismissed')),
          decided_by      uuid REFERENCES users (id),
          decided_at      timestamptz,
          decision_note   text CONSTRAINT ck_reports_decision_note_length
                          CHECK (char_length(decision_note) <= 2000),
          CONSTRAINT ck_reports_decision_complete
            CHECK ((decision IS NULL) = (decided_by IS NULL)
                   AND (decision IS NULL) = (decided_at IS NULL))
        )
        """
    )
    # One open report per person and item; reporting again after a decision is allowed.
    op.execute(
        "CREATE UNIQUE INDEX uq_reports_open ON reports (submission_id, reported_by) "
        "WHERE decision IS NULL"
    )
    op.execute("CREATE INDEX ix_reports_open ON reports (created_at) WHERE decision IS NULL")
    op.execute(
        "CREATE TRIGGER reports_guard BEFORE UPDATE OR DELETE ON reports "
        "FOR EACH ROW EXECUTE FUNCTION "
        "lkd_guard_columns('decision', 'decided_by', 'decided_at', 'decision_note')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE reports")
