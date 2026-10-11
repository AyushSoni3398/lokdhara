"""Operator commands.

    uv run python -m app.cli create-admin --username asha --display-name "Asha"
    uv run python -m app.cli seed-dev          # synthetic users; development/test only

Accounts are invite-only (ADR-008); create-admin exists to bootstrap the first administrator.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.identity import service
from app.modules.identity.models import ROLES, User, UserRole
from app.security import new_token

# Synthetic development accounts: one per role, plus a second admin (two-admin rule).
DEV_USERS = (
    ("dev-admin", "Dev Admin", ("admin",)),
    ("dev-admin2", "Dev Admin Two", ("admin",)),
    ("dev-reviewer", "Dev Reviewer", ("reviewer", "contributor")),
    ("dev-facilitator", "Dev Facilitator", ("facilitator", "contributor")),
    ("dev-contributor", "Dev Contributor", ("contributor",)),
    ("dev-researcher", "Dev Researcher", ("researcher",)),
)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return first


def _create(
    db: Session, username: str, display_name: str, password: str, roles: Sequence[str]
) -> User:
    user = service.create_user(db, username=username, display_name=display_name, password=password)
    for role in roles:
        db.add(UserRole(user_id=user.id, role=role, granted_at=service.utcnow()))
    audit.record(
        db,
        action="user.create_cli",
        context=None,
        actor_user_id=None,
        actor_type="system",
        target_type="user",
        target_id=user.id,
        details={"roles": list(roles)},
    )
    return user


def create_admin(username: str, display_name: str, password_stdin: bool) -> int:
    password = _read_password(password_stdin)
    with Session(get_engine()) as db:
        try:
            _create(db, username, display_name, password, ["admin"])
        except ApiError as exc:
            print(f"Error: {exc.title} {exc.detail or ''}".strip(), file=sys.stderr)
            return 1
        db.commit()
    print(f"Created administrator '{service.normalize_username(username)}'.")
    return 0


def seed_dev() -> int:
    settings = get_settings()
    if not settings.is_local:
        print("seed-dev only runs when LKD_ENV is development or test.", file=sys.stderr)
        return 1
    with Session(get_engine()) as db:
        created: list[tuple[str, str]] = []
        for username, display_name, roles in DEV_USERS:
            if db.scalar(select(User.id).where(User.username == username)):
                continue
            password = new_token()[:20]
            _create(db, username, display_name, password, roles)
            created.append((username, password))
        db.commit()
    if not created:
        print("Development users already exist.")
    for username, password in created:
        print(f"{username:16} {password}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an administrator account")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", required=True)
    admin.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    commands.add_parser("seed-dev", help=f"create synthetic users ({', '.join(ROLES)})")
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.username, args.display_name, args.password_stdin)
    return seed_dev()


if __name__ == "__main__":
    raise SystemExit(main())
