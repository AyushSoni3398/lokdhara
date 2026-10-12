"""Prepares a separate database for the load test (docs/LOAD_TESTING.md).

    uv run --group loadtest python -m loadtest.prepare --users 50

Drops and recreates the database named in LKD_DATABASE_URL, which must end in `_loadtest`,
migrates it, adds the test consent forms and prompts, and creates contributors with random
passwords. The accounts are written to loadtest/results/accounts.json (git-ignored).
Synthetic data only: it refuses to run outside development and test.
"""

import argparse
import json
import secrets
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.consents import service as consents
from app.modules.identity import service as identity
from app.modules.identity.models import UserRole
from app.modules.prompts import service as prompts

BACKEND = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results"


def recreate_database(url: str) -> None:
    name = make_url(url).database
    if not name or not name.endswith("_loadtest"):
        raise SystemExit("LKD_DATABASE_URL must name a database ending in _loadtest.")
    server = make_url(url).set(database="postgres")
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def create_accounts(url: str, count: int) -> list[dict[str, str]]:
    accounts = []
    with Session(create_engine(url)) as db:
        consents.ensure_dev_forms(db)
        admin = identity.create_user(
            db, username="load-admin", display_name="Load Admin", password=secrets.token_hex(16)
        )
        db.add(UserRole(user_id=admin.id, role="admin", granted_at=identity.utcnow()))
        prompts.ensure_dev_prompts(db, admin.id)
        for number in range(1, count + 1):
            account = {"username": f"load-{number:03}", "password": secrets.token_hex(16)}
            user = identity.create_user(
                db, display_name=f"Load Test {number}", preferred_locale="hi", **account
            )
            db.add(UserRole(user_id=user.id, role="contributor", granted_at=identity.utcnow()))
            accounts.append(account)
        db.commit()
    return accounts


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m loadtest.prepare")
    parser.add_argument("--users", type=int, default=50)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.is_local:
        print("The load test only runs when LKD_ENV is development or test.", file=sys.stderr)
        return 1
    recreate_database(settings.database_url)
    accounts = create_accounts(settings.database_url, args.users)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "accounts.json").write_text(json.dumps(accounts))
    print(f"Prepared {make_url(settings.database_url).database} with {len(accounts)} contributors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
