import io

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.modules.identity.models import User, UserRole
from tests.conftest import requires_postgres


def test_seed_dev_refuses_outside_local_environments(monkeypatch: pytest.MonkeyPatch) -> None:
    production = Settings(_env_file=None, env="production", secret_key="x" * 40)
    monkeypatch.setattr(cli, "get_settings", lambda: production)
    assert cli.main(["seed-dev"]) == 1


@requires_postgres
def test_create_admin_reads_password_from_stdin(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, db: Session
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr("sys.stdin", io.StringIO("a long admin passphrase\n"))
    args = ["create-admin", "--username", "Asha", "--display-name", "Asha", "--password-stdin"]
    assert cli.main(args) == 0
    user = db.scalar(select(User).where(User.username == "asha"))
    assert user is not None
    assert db.scalar(select(UserRole.role).where(UserRole.user_id == user.id)) == "admin"


@requires_postgres
def test_seed_dev_creates_one_account_per_role_once(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, env="development"))
    assert cli.main(["seed-dev"]) == 0
    assert cli.main(["seed-dev"]) == 0
    assert "already exist" in capsys.readouterr().out
    roles = set(db.scalars(select(UserRole.role)))
    assert roles == {"admin", "reviewer", "facilitator", "contributor", "researcher"}
