"""Migration round-trip and append-only enforcement (ROADMAP M2 acceptance criteria)."""

from collections.abc import Callable

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import alembic_config, requires_postgres

pytestmark = requires_postgres


def test_upgrade_downgrade_upgrade(scratch_database_factory: Callable[[], str]) -> None:
    url = scratch_database_factory()
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
    engine.dispose()
    assert "audit_events" in tables


def _insert_audit_event(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO audit_events (actor_type, action) VALUES ('system', 'test.event')")
        )


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET action = 'changed'", "DELETE FROM audit_events"],
)
def test_audit_events_reject_changes_as_app_rw(engine: Engine, statement: str) -> None:
    _insert_audit_event(engine)
    with engine.connect() as connection, pytest.raises(DBAPIError, match="append_only"):
        connection.execute(text("SET ROLE app_rw"))
        connection.execute(text(statement))


def test_app_rw_cannot_unlock_erasure_by_setting_the_flag(engine: Engine) -> None:
    _insert_audit_event(engine)
    with engine.connect() as connection, pytest.raises(DBAPIError, match="append_only"):
        connection.execute(text("SET ROLE app_rw"))
        connection.execute(text("SET lkd.erasure = 'on'"))
        connection.execute(text("DELETE FROM audit_events"))


def test_even_the_owner_needs_the_erasure_flag(engine: Engine) -> None:
    _insert_audit_event(engine)
    with engine.connect() as connection, pytest.raises(DBAPIError, match="append_only"):
        connection.execute(text("DELETE FROM audit_events"))


def test_erasure_role_with_flag_may_delete(engine: Engine) -> None:
    _insert_audit_event(engine)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE app_erasure"))
        connection.execute(text("SET LOCAL lkd.erasure = 'on'"))
        deleted = connection.execute(text("DELETE FROM audit_events")).rowcount
    assert deleted == 1


def test_app_rw_cannot_truncate(engine: Engine) -> None:
    with engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(text("SET ROLE app_rw"))
        connection.execute(text("TRUNCATE audit_events"))


def test_app_readonly_cannot_write(engine: Engine) -> None:
    with engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(text("SET ROLE app_readonly"))
        connection.execute(
            text("INSERT INTO audit_events (actor_type, action) VALUES ('system', 'x')")
        )
