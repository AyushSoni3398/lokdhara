"""The admin status page: what needs attention (docs/OBSERVABILITY_AND_BACKUPS.md §2)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.ops.status import BackupState, Status, alerts
from tests.conftest import MakeUser, act_as, requires_postgres

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _backup(
    kind: str, age: timedelta, *, ok: bool = True, detail: str | None = None
) -> BackupState:
    return BackupState(kind, NOW - age, ok, detail, NOW - age, 1024)


def healthy(**changes: object) -> Status:
    status = Status(
        checked_at=NOW,
        jobs_queued=3,
        jobs_running=1,
        oldest_due_job_since=NOW - timedelta(minutes=5),
        jobs_failed_last_day=0,
        jobs_failed_waiting=0,
        backups={
            "database": _backup("database", timedelta(hours=10)),
            "withdrawal_log": _backup("withdrawal_log", timedelta(minutes=30)),
        },
        submissions_last_day=12,
        accepted_last_day=10,
        rejected_last_day=1,
        login_failures_last_day=4,
        open_reports=0,
        open_withdrawals=0,
        exports_awaiting_approval=0,
        database_bytes=10_000_000,
        disk_used_share=0.4,
    )
    return replace(status, **changes)  # type: ignore[arg-type]


def test_a_healthy_service_needs_nothing() -> None:
    assert alerts(healthy()) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"oldest_due_job_since": NOW - timedelta(hours=2)}, "queue_behind"),
        ({"jobs_failed_last_day": 2}, "jobs_failed"),
        ({"disk_used_share": 0.85}, "disk_nearly_full"),
        ({"login_failures_last_day": 51}, "many_failed_sign_ins"),
    ],
)
def test_each_threshold_raises_its_alert(changes: dict[str, object], expected: str) -> None:
    assert alerts(healthy(**changes)) == [expected]


def test_a_database_backup_older_than_26_hours_is_missing() -> None:
    old = healthy().backups | {"database": _backup("database", timedelta(hours=27))}
    assert alerts(healthy(backups=old)) == ["backup_missing:database"]


def test_no_withdrawal_log_for_two_hours_is_missing() -> None:
    old = healthy().backups | {"withdrawal_log": _backup("withdrawal_log", timedelta(hours=3))}
    assert alerts(healthy(backups=old)) == ["backup_missing:withdrawal_log"]


def test_a_failed_last_run_is_reported_while_an_older_one_is_recent() -> None:
    failed = replace(_backup("database", timedelta(hours=3)), last_run_succeeded=False)
    assert alerts(healthy(backups=healthy().backups | {"database": failed})) == [
        "backup_failed:database"
    ]


def test_backups_that_never_left_the_server_are_flagged() -> None:
    local = _backup("database", timedelta(hours=1), detail="kept on this server only: no ...")
    assert alerts(healthy(backups=healthy().backups | {"database": local})) == [
        "backup_not_off_site"
    ]


def test_no_backup_ever_is_missing() -> None:
    never = BackupState("database", None, None, None, None, None)
    assert "backup_missing:database" in alerts(
        healthy(backups=healthy().backups | {"database": never})
    )


@requires_postgres
def test_only_admins_see_the_status(client: TestClient, make_user: MakeUser) -> None:
    act_as(client, make_user("asha", "contributor", "researcher", "facilitator"))
    assert client.get("/api/v1/admin/status").status_code == 403


@requires_postgres
def test_the_status_counts_what_is_waiting(
    client: TestClient, db: Session, make_user: MakeUser
) -> None:
    db.execute(
        text(
            "INSERT INTO backup_runs (kind, started_at, succeeded, size_bytes, file_name) "
            "VALUES ('database', now() - interval '1 minute', true, 2048, 'db.dump.age')"
        )
    )
    db.execute(
        text(
            "INSERT INTO jobs (job_type, status, attempts, finished_at, last_error_code) "
            "VALUES ('audio.validate', 'failed', 5, now(), 'ffprobe_failed')"
        )
    )
    db.commit()
    act_as(client, make_user("admin", "admin"))
    body = client.get("/api/v1/admin/status").json()
    assert body["jobs_failed_waiting"] == 1
    assert body["alerts"] == ["backup_missing:withdrawal_log", "jobs_failed"]
    database = next(b for b in body["backups"] if b["kind"] == "database")
    assert (database["last_run_succeeded"], database["last_success_bytes"]) == (True, 2048)
    assert body["database_bytes"] > 0
    assert 0 < body["disk_used_share"] < 1
