"""Checking a database restored from backup (docs/OBSERVABILITY_AND_BACKUPS.md §4)."""

import hashlib
import io
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import cli
from app.modules.ops.restore import (
    LOG_COLUMNS,
    LoggedWithdrawal,
    check_originals,
    check_restore,
    expected_revision,
    read_withdrawal_log,
    withdrawals_to_redo,
)
from app.object_store import Bucket, ObjectStore
from tests.conftest import requires_postgres


def _logged(status: str) -> LoggedWithdrawal:
    return LoggedWithdrawal(uuid.uuid4(), uuid.uuid4(), None, "full", status)


def test_completed_withdrawals_missing_from_the_restore_are_redone() -> None:
    lost, kept, open_request = _logged("completed"), _logged("completed"), _logged("verified")
    restored = [kept, open_request]
    assert withdrawals_to_redo([lost, kept, open_request], restored) == [lost]


def test_a_withdrawal_the_restore_has_only_started_is_redone() -> None:
    started = _logged("completed")
    assert withdrawals_to_redo([started], [replace(started, status="in_progress")]) == [started]


def test_a_new_completed_request_for_the_same_items_counts_as_redone() -> None:
    lost = replace(
        _logged("completed"), requested_scope="specific_items", submission_id=uuid.uuid4()
    )
    redone = replace(lost, id=uuid.uuid4())
    other_item = replace(redone, submission_id=uuid.uuid4())
    assert withdrawals_to_redo([lost], [other_item]) == [lost]
    assert withdrawals_to_redo([lost], [redone]) == []


def _write_log(path: Path, rows: list[list[str]], header: tuple[str, ...] = LOG_COLUMNS) -> Path:
    path.write_text("\n".join(",".join(r) for r in [list(header), *rows]) + "\n")
    return path


def test_the_withdrawal_log_is_read_strictly(tmp_path: Path) -> None:
    request, speaker, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        [str(request), str(speaker), "", "full", "completed", "2026-10-18 01:00:00+00"],
        [str(uuid.uuid4()), str(speaker), str(item), "specific_items", "verified", ""],
    ]
    logged = read_withdrawal_log(_write_log(tmp_path / "log.csv", rows))
    assert logged[0] == LoggedWithdrawal(request, speaker, None, "full", "completed")
    assert logged[1].submission_id == item
    with pytest.raises(ValueError, match="columns"):
        read_withdrawal_log(_write_log(tmp_path / "bad.csv", [], header=("id", "speaker_name")))


def test_originals_must_exist_with_the_same_bytes(object_store: ObjectStore) -> None:
    good, changed, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stored = object_store.put(Bucket.ORIGINALS, "originals/good.webm", io.BytesIO(b"synthetic"))
    object_store.put(Bucket.ORIGINALS, "originals/changed.webm", io.BytesIO(b"other bytes"))
    problems = check_originals(
        [
            (good, "originals/good.webm", stored.sha256),
            (changed, "originals/changed.webm", hashlib.sha256(b"synthetic").hexdigest()),
            (missing, "originals/missing.webm", stored.sha256),
        ],
        object_store,
    )
    assert problems == [
        f"recording {changed}: original does not match its checksum",
        f"recording {missing}: original missing from storage",
    ]


@requires_postgres
def test_a_restore_with_a_lost_withdrawal_fails(
    db: Session, object_store: ObjectStore, tmp_path: Path
) -> None:
    log = _write_log(
        tmp_path / "log.csv",
        [[str(uuid.uuid4()), str(uuid.uuid4()), "", "full", "completed", "2026-10-18"]],
    )
    report = check_restore(db, object_store, sample=5, withdrawal_log=log)
    assert report.schema_revision == expected_revision()
    assert report.counts["recordings"] == 0
    assert len(report.withdrawals_to_redo) == 1
    assert not report.ok
    assert check_restore(db, object_store, sample=5, withdrawal_log=None).ok


@requires_postgres
def test_verify_restore_command_reports_what_to_redo(
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
    object_store: ObjectStore,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "owner_engine", lambda: db.get_bind())
    monkeypatch.setattr(cli, "get_object_store", lambda: object_store)
    request = uuid.uuid4()
    log = _write_log(
        tmp_path / "log.csv", [[str(request), str(uuid.uuid4()), "", "full", "completed", "x"]]
    )
    assert cli.main(["verify-restore", "--withdrawal-log", str(log)]) == 1
    output = capsys.readouterr().out
    assert f"REDO withdrawal {request}" in output
    assert "FAILED" in output
