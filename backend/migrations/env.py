"""Alembic environment. Migrations are hand-written; models are imported for reference only."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests and tools may pass a URL explicitly; otherwise use settings.
    url = context.config.attributes.get("database_url")
    return str(url) if url else get_settings().effective_migration_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
