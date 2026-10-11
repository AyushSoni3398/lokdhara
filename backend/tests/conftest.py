"""Shared fixtures. Database tests run against real PostgreSQL (docs/TESTING_STRATEGY.md).

Each test session creates a throwaway database next to LKD_TEST_DATABASE_URL, migrates it,
and drops it afterwards, so a developer's local data is never touched.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_engine
from app.main import create_app

TEST_DATABASE_URL = os.environ.get("LKD_TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parent.parent
requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="LKD_TEST_DATABASE_URL not set"
)


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture(scope="session")
def scratch_database_factory() -> Iterator[Callable[[], str]]:
    """Creates empty databases on the test server; drops them all at the end."""
    assert TEST_DATABASE_URL is not None
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    created: list[str] = []

    def create() -> str:
        name = f"lkd_test_{uuid.uuid4().hex[:12]}"
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)

    yield create
    with admin.connect() as connection:
        for name in created:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_engine(scratch_database_factory: Callable[[], str]) -> Iterator[Engine]:
    url = scratch_database_factory()
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(migrated_engine: Engine) -> Iterator[Engine]:
    yield migrated_engine
    with migrated_engine.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, env="test", secret_key="test-secret-key-not-for-real-use")


@pytest.fixture
def client(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
