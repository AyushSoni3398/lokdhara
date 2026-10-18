"""The backup role and the record of backup runs (migration 0015)."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from tests.conftest import requires_postgres

pytestmark = requires_postgres

_RECORD = (
    "INSERT INTO backup_runs (kind, started_at, succeeded, size_bytes, file_name) "
    "VALUES ('database', now() - interval '1 minute', true, 1024, 'lokdhara-x.dump.age')"
)


def test_backup_role_can_read_every_table(engine: Engine) -> None:
    with engine.connect() as connection:
        tables = connection.execute(
            text("SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        connection.execute(text("SET ROLE app_backup"))
        for table in tables:
            connection.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        # Identities are left out of the reporting role but a restore needs them.
        connection.execute(text("SELECT count(*) FROM speaker_identities"))
        connection.execute(text("SELECT count(*) FROM alembic_version"))


def test_backup_role_writes_only_its_own_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE app_backup"))
        connection.execute(text(_RECORD))
    with engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(text("SET ROLE app_backup"))
        connection.execute(
            text("INSERT INTO audit_events (actor_type, action) VALUES ('system', 'x')")
        )


@pytest.mark.parametrize(
    "statement", ["UPDATE backup_runs SET succeeded = false", "DELETE FROM backup_runs"]
)
def test_backup_runs_are_never_changed(engine: Engine, statement: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(_RECORD))
    with engine.connect() as connection, pytest.raises(DBAPIError, match="append_only"):
        connection.execute(text("SET ROLE app_rw"))
        connection.execute(text(statement))


def test_a_successful_run_names_its_file(engine: Engine) -> None:
    with engine.connect() as connection, pytest.raises(IntegrityError, match="success_has_file"):
        connection.execute(
            text(
                "INSERT INTO backup_runs (kind, started_at, succeeded) "
                "VALUES ('database', now(), true)"
            )
        )
