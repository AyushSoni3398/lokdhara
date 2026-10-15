"""Dataset releases, the exact items each frozen release holds, and export requests (ROADMAP M7).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-15

A draft release is a selection that can still change. Freezing records the version, who froze
it, the manifest, and one row per item with the revisions, files, and consent it was frozen
with; after that only retraction changes a release. Datasets themselves never live in Git
(ADR-013, ADR-017): export packages are built in the `exports` bucket and expire.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_TYPES = (
    "'system.ping', 'audio.validate', 'audio.analyze', 'audio.renditions', 'audio.dedupe', "
    "'text.derive', 'dataset.export', 'cleanup.quarantine', 'cleanup.expire_drafts'"
)
PURPOSES = "'internal_research', 'external_research', 'public', 'ai_training'"
EXPORT_STATUSES = "'requested', 'approved', 'building', 'ready', 'expired', 'rejected', 'failed'"
SEMVER = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"


def _job_types(job_types: str, tables: tuple[str, ...] = ("jobs", "processing_runs")) -> None:
    for table in tables:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_job_type")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_job_type "
            f"CHECK (job_type IN ({job_types}))"
        )


def upgrade() -> None:
    _job_types(f"{_JOB_TYPES}, 'cleanup.expire_exports'")
    op.execute(
        f"""
        CREATE TABLE dataset_releases (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          slug                text NOT NULL CONSTRAINT ck_dataset_releases_slug
                              CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 60),
          version             text CONSTRAINT ck_dataset_releases_version
                              CHECK (version ~ '{SEMVER}'),
          purpose             text NOT NULL CONSTRAINT ck_dataset_releases_purpose
                              CHECK (purpose IN ({PURPOSES})),
          selection_criteria  jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          status              text NOT NULL DEFAULT 'draft' CONSTRAINT ck_dataset_releases_status
                              CHECK (status IN ('draft', 'frozen', 'retracted')),
          licence             text CONSTRAINT ck_dataset_releases_licence_length
                              CHECK (char_length(licence) <= 200),
          data_card_markdown  text NOT NULL DEFAULT ''
                              CONSTRAINT ck_dataset_releases_data_card_length
                              CHECK (char_length(data_card_markdown) <= 50000),
          manifest_object_key text,
          manifest_sha256     text CONSTRAINT ck_dataset_releases_manifest_sha256
                              CHECK (manifest_sha256 ~ '^[0-9a-f]{{64}}$'),
          code_version        text,
          created_by          uuid NOT NULL REFERENCES users (id),
          approved_by         uuid REFERENCES users (id),
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          frozen_at           timestamptz,
          retracted_at        timestamptz,
          retraction_note     text CONSTRAINT ck_dataset_releases_retraction_note_length
                              CHECK (char_length(retraction_note) <= 2000),
          CONSTRAINT uq_dataset_releases_slug_version UNIQUE (slug, version),
          CONSTRAINT ck_dataset_releases_frozen_complete CHECK (
            (status = 'draft') = (version IS NULL)
            AND (status = 'draft') = (frozen_at IS NULL)
            AND (status = 'draft') = (approved_by IS NULL)
            AND (status = 'draft') = (manifest_sha256 IS NULL)
            AND (status = 'retracted') = (retracted_at IS NOT NULL)
            AND (status = 'retracted') = (retraction_note IS NOT NULL))
        )
        """
    )
    # Once frozen, a release only moves on to retracted; drafts change freely.
    op.execute(
        """
        CREATE FUNCTION lkd_release_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'immutable_columns: a frozen release cannot be deleted'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status <> 'draft' AND (
               NEW.status <> 'retracted'
               OR (to_jsonb(OLD) - '{status,retracted_at,retraction_note,updated_at}'::text[])
                  IS DISTINCT FROM
                  (to_jsonb(NEW) - '{status,retracted_at,retraction_note,updated_at}'::text[])
               OR (OLD.status = 'retracted' AND to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW))
             ) THEN
            RAISE EXCEPTION 'immutable_columns: a frozen release can only be retracted'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER dataset_releases_guard BEFORE UPDATE OR DELETE ON dataset_releases "
        "FOR EACH ROW EXECUTE FUNCTION lkd_release_guard()"
    )
    op.execute("CREATE INDEX ix_dataset_releases_status ON dataset_releases (status, created_at)")

    op.execute(
        """
        CREATE TABLE dataset_release_items (
          release_id                 uuid NOT NULL REFERENCES dataset_releases (id),
          submission_id              uuid NOT NULL REFERENCES submissions (id),
          recording_id               uuid REFERENCES recordings (id),
          rendition_id               uuid REFERENCES renditions (id),
          text_revision_ids          uuid[] NOT NULL DEFAULT '{}',
          consent_record_id          uuid NOT NULL REFERENCES consent_records (id),
          consent_snapshot           jsonb NOT NULL,
          item_sha256s               jsonb NOT NULL DEFAULT '{}'::jsonb,
          withdrawn_after_release_at timestamptz,
          PRIMARY KEY (release_id, submission_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_dataset_release_items_submission ON dataset_release_items (submission_id)"
    )
    op.execute(
        "CREATE TRIGGER dataset_release_items_guard BEFORE UPDATE OR DELETE "
        "ON dataset_release_items FOR EACH ROW "
        "EXECUTE FUNCTION lkd_guard_columns('withdrawn_after_release_at')"
    )

    op.execute(
        f"""
        CREATE TABLE export_requests (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          release_id        uuid NOT NULL REFERENCES dataset_releases (id),
          requested_by      uuid NOT NULL REFERENCES users (id),
          purpose_statement text NOT NULL CONSTRAINT ck_export_requests_purpose_length
                            CHECK (char_length(purpose_statement) BETWEEN 1 AND 2000),
          status            text NOT NULL DEFAULT 'requested'
                            CONSTRAINT ck_export_requests_status
                            CHECK (status IN ({EXPORT_STATUSES})),
          decided_by        uuid REFERENCES users (id),
          decided_at        timestamptz,
          decision_note     text CONSTRAINT ck_export_requests_decision_note_length
                            CHECK (char_length(decision_note) <= 2000),
          object_key        text,
          sha256            text CONSTRAINT ck_export_requests_sha256
                            CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
          size_bytes        bigint,
          created_at        timestamptz NOT NULL DEFAULT now(),
          ready_at          timestamptz,
          expires_at        timestamptz,
          downloaded_at     timestamptz[] NOT NULL DEFAULT '{{}}',
          CONSTRAINT ck_export_requests_decided
            CHECK ((status = 'requested') = (decided_by IS NULL)
                   AND (decided_by IS NULL) = (decided_at IS NULL)),
          CONSTRAINT ck_export_requests_ready
            CHECK (status <> 'ready' OR (object_key IS NOT NULL AND sha256 IS NOT NULL
                                         AND expires_at IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ix_export_requests_release ON export_requests (release_id)")
    op.execute(
        "CREATE INDEX ix_export_requests_expiry ON export_requests (expires_at) "
        "WHERE status = 'ready'"
    )
    op.execute(
        "CREATE TRIGGER export_requests_frozen BEFORE UPDATE OR DELETE ON export_requests "
        "FOR EACH ROW EXECUTE FUNCTION "
        "lkd_freeze_columns('id', 'release_id', 'requested_by', 'purpose_statement', 'created_at')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE export_requests")
    op.execute("DROP TABLE dataset_release_items")
    op.execute("DROP TABLE dataset_releases")
    op.execute("DROP FUNCTION lkd_release_guard()")
    op.execute("DELETE FROM jobs WHERE job_type = 'cleanup.expire_exports'")
    # processing_runs is append-only, so its past runs stay and so does their job type.
    _job_types(_JOB_TYPES, tables=("jobs",))
