import base64
import io

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.modules.identity.models import User, UserRole
from app.object_store import ObjectStore
from tests.conftest import requires_postgres


def test_seed_dev_refuses_outside_local_environments(monkeypatch: pytest.MonkeyPatch) -> None:
    production = Settings(
        _env_file=None,
        env="production",
        secret_key="x" * 40,
        identity_encryption_key=base64.b64encode(bytes(32)).decode(),
    )
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
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "get_object_store", lambda: object_store)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, env="development"))
    assert cli.main(["seed-dev"]) == 0
    assert cli.main(["seed-dev"]) == 0
    assert "already exist" in capsys.readouterr().out
    roles = set(db.scalars(select(UserRole.role)))
    assert roles == {"admin", "reviewer", "facilitator", "contributor", "researcher"}


@requires_postgres
def test_seed_dev_adds_test_consent_forms_and_prompts_once(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.modules.consents.models import ConsentForm
    from app.modules.prompts.models import Prompt

    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "get_object_store", lambda: object_store)  # the test pictures
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, env="development"))
    assert cli.main(["seed-dev"]) == 0
    assert "not for real data" in capsys.readouterr().out
    assert cli.main(["seed-dev"]) == 0
    forms = list(db.scalars(select(ConsentForm)))
    assert sorted(f.language for f in forms) == ["en", "hi"]
    assert all(f.is_test_form for f in forms)
    assert len(list(db.scalars(select(Prompt.id)))) == 12


@requires_postgres
def test_ping_worker_queues_a_job(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, db: Session
) -> None:
    from app.modules.processing.models import Job

    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    assert cli.main(["ping-worker"]) == 0
    assert db.scalar(select(Job.job_type)) == "system.ping"
