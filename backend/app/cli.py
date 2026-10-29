"""Operator commands.

    uv run python -m app.cli create-admin --username asha --display-name "Asha"
    uv run python -m app.cli seed-dev          # synthetic users, test consent forms and prompts
    uv run python -m app.cli ping-worker       # enqueue a no-op job to check the worker
    uv run python -m app.cli verify-restore --withdrawal-log log.csv   # after a restore
    uv run python -m app.cli reset-mfa --username asha   # lost phone and recovery codes

Accounts are invite-only (ADR-008); create-admin exists to bootstrap the first administrator.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.modules.audit import service as audit
from app.modules.consents import service as consents
from app.modules.identity import mfa_service, service
from app.modules.identity.models import ROLES, User, UserRole
from app.modules.ops.restore import check_restore
from app.modules.processing.queue import enqueue
from app.modules.prompts import service as prompts
from app.object_store import get_object_store
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
        forms = consents.ensure_dev_forms(db)
        admin_id = db.scalar(select(User.id).where(User.username == "dev-admin"))
        assert admin_id is not None  # noqa: S101 - created above or by an earlier run
        added_prompts = prompts.ensure_dev_prompts(db, get_object_store(), settings, admin_id)
        db.commit()
    if not created:
        print("Development users already exist.")
    for username, password in created:
        print(f"{username:16} {password}")
    if forms:
        print(f"Added test consent forms: {', '.join(forms)} (not for real data).")
    if added_prompts:
        print(f"Added {added_prompts} test prompts (Hindi placeholders, not for real data).")
    return 0


def ping_worker() -> int:
    with Session(get_engine()) as db:
        job_id = enqueue(db, "system.ping")
        db.commit()
    print(f"Queued system.ping job {job_id}; a running worker records it in processing_runs.")
    return 0


def reset_mfa(username: str) -> int:
    with Session(get_engine()) as db:
        try:
            mfa_service.reset(db, service.normalize_username(username))
        except ApiError as exc:
            print(f"Error: {exc.title}", file=sys.stderr)
            return 1
    print(f"Two-step sign-in is off for '{username}'; they set it up again when they sign in.")
    return 0


def owner_engine() -> Engine:
    """The schema owner's connection (LKD_MIGRATION_DATABASE_URL), which can read every table."""
    return create_engine(get_settings().effective_migration_url, hide_parameters=True)


def verify_restore(sample: int, withdrawal_log: Path | None) -> int:
    """Run against a freshly restored database before it serves anyone (restore drill)."""
    with Session(owner_engine()) as db:
        report = check_restore(db, get_object_store(), sample=sample, withdrawal_log=withdrawal_log)
    print(
        f"Schema revision: {report.schema_revision} (this code expects {report.expected_revision})"
    )
    print(f"Data as of: {report.data_as_of:%Y-%m-%d %H:%M %Z}" if report.data_as_of else "No data.")
    for table, count in report.counts.items():
        print(f"  {table:22} {count}")
    print(f"Originals checked against their checksums: {report.originals_checked}")
    if report.originals_withdrawn_after_backup:
        print(
            f"  {report.originals_withdrawn_after_backup} originals not checked: their "
            "withdrawal was carried out after the backup (redo it, below)"
        )
    for problem in report.originals_problems:
        print(f"  PROBLEM {problem}")
    if withdrawal_log is None:
        print("No withdrawal log given: check withdrawals made after the backup by hand.")
    for item in report.withdrawals_to_redo:
        target = f"submission {item.submission_id}" if item.submission_id else "all items"
        print(
            f"  REDO withdrawal {item.id}: speaker {item.speaker_id}, {item.requested_scope}, "
            f"{target}"
        )
    print("Restore check passed." if report.ok else "Restore check FAILED: fix the above first.")
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an administrator account")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", required=True)
    admin.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    commands.add_parser(
        "seed-dev",
        help=f"create synthetic users ({', '.join(ROLES)}), test consent forms and prompts",
    )
    commands.add_parser("ping-worker", help="enqueue a no-op job to check the worker")
    verify = commands.add_parser("verify-restore", help="check a database restored from backup")
    verify.add_argument("--sample", type=int, default=20, help="originals to checksum")
    verify.add_argument("--withdrawal-log", type=Path, help="decrypted withdrawal log CSV")
    reset = commands.add_parser("reset-mfa", help="turn off two-step sign-in for a user")
    reset.add_argument("--username", required=True)
    args = parser.parse_args(argv)
    if args.command == "reset-mfa":
        return reset_mfa(args.username)
    if args.command == "verify-restore":
        return verify_restore(args.sample, args.withdrawal_log)
    if args.command == "create-admin":
        return create_admin(args.username, args.display_name, args.password_stdin)
    if args.command == "ping-worker":
        return ping_worker()
    return seed_dev()


if __name__ == "__main__":
    raise SystemExit(main())
