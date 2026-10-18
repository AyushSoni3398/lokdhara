"""Checks a database restored from a backup before anyone uses it (restore drill).

docs/OBSERVABILITY_AND_BACKUPS.md §4: the schema is the one this code expects, the originals
the database names are in storage with the same bytes, and every withdrawal finished after the
backup was taken is listed so it can be carried out again before the service reopens.
"""

import csv
import random
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.submissions.models import Recording, Submission
from app.object_store import Bucket, ObjectStore

BACKEND_DIR = Path(__file__).resolve().parents[3]
# Counted and printed so the operator can compare them with the live service.
COUNTED_TABLES = (
    "users",
    "speakers",
    "consent_records",
    "submissions",
    "recordings",
    "text_revisions",
    "withdrawal_requests",
    "dataset_releases",
    "audit_events",
)
# Columns of the withdrawal log the backup job writes every hour (backup.sh withdrawal-log).
LOG_COLUMNS = ("id", "speaker_id", "submission_id", "requested_scope", "status", "completed_at")


@dataclass(frozen=True)
class LoggedWithdrawal:
    id: uuid.UUID
    speaker_id: uuid.UUID
    submission_id: uuid.UUID | None
    requested_scope: str
    status: str


@dataclass
class RestoreReport:
    schema_revision: str | None
    expected_revision: str
    counts: dict[str, int]
    data_as_of: datetime | None
    originals_checked: int = 0
    originals_problems: list[str] = field(default_factory=list)
    # Originals of withdrawals to redo: deleted after the backup, so their absence is expected.
    originals_withdrawn_after_backup: int = 0
    withdrawals_to_redo: list[LoggedWithdrawal] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.schema_revision == self.expected_revision
            and not self.originals_problems
            and not self.withdrawals_to_redo
        )


def expected_revision() -> str:
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    head = script.get_current_head()
    assert head is not None  # noqa: S101 - the code always ships with migrations
    return head


def read_withdrawal_log(path: Path) -> list[LoggedWithdrawal]:
    """Reads the decrypted CSV the backup job writes; unknown or missing columns are an error."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LOG_COLUMNS:
            raise ValueError(f"expected the columns {', '.join(LOG_COLUMNS)}")
        return [
            LoggedWithdrawal(
                id=uuid.UUID(row["id"]),
                speaker_id=uuid.UUID(row["speaker_id"]),
                submission_id=uuid.UUID(row["submission_id"]) if row["submission_id"] else None,
                requested_scope=row["requested_scope"],
                status=row["status"],
            )
            for row in reader
        ]


def withdrawals_to_redo(
    logged: Iterable[LoggedWithdrawal], restored: Iterable[LoggedWithdrawal]
) -> list[LoggedWithdrawal]:
    """Withdrawals the log shows as completed that the restored database has not completed.

    Their files may already be gone from storage, but the restored rows still describe them
    (and could put them in a release), so each must be logged and carried out again. Once a
    new request for the same speaker and items is completed, it no longer needs redoing.
    """
    done = [item for item in restored if item.status == "completed"]
    done_ids = {item.id for item in done}
    done_subjects = {(i.speaker_id, i.requested_scope, i.submission_id) for i in done}
    return [
        item
        for item in logged
        if item.status == "completed"
        and item.id not in done_ids
        and (item.speaker_id, item.requested_scope, item.submission_id) not in done_subjects
    ]


def check_originals(
    originals: Sequence[tuple[uuid.UUID, str, str]], store: ObjectStore
) -> list[str]:
    """Problems with (recording id, object key, expected sha256) originals; empty when all match."""
    problems: list[str] = []
    for recording_id, key, expected in originals:
        if store.head(Bucket.ORIGINALS, key) is None:
            problems.append(f"recording {recording_id}: original missing from storage")
        elif store.sha256_of(Bucket.ORIGINALS, key) != expected:
            problems.append(f"recording {recording_id}: original does not match its checksum")
    return problems


def _covered(
    speaker_id: uuid.UUID, submission_id: uuid.UUID, redo: Iterable[LoggedWithdrawal]
) -> bool:
    return any(
        (item.requested_scope == "full" and item.speaker_id == speaker_id)
        or (item.requested_scope == "specific_items" and item.submission_id == submission_id)
        for item in redo
    )


def check_restore(
    db: Session,
    store: ObjectStore,
    *,
    sample: int,
    withdrawal_log: Path | None,
    rng: random.Random | None = None,
) -> RestoreReport:
    revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    counts = {
        table: int(db.scalar(text(f"SELECT count(*) FROM {table}")) or 0)  # noqa: S608
        for table in COUNTED_TABLES
    }
    report = RestoreReport(
        schema_revision=revision,
        expected_revision=expected_revision(),
        counts=counts,
        data_as_of=db.scalar(select(func.max(AuditEvent.occurred_at))),
    )
    if withdrawal_log is not None:
        restored = [
            LoggedWithdrawal(*row)
            for row in db.execute(
                text(
                    "SELECT id, speaker_id, submission_id, requested_scope, status "
                    "FROM withdrawal_requests"
                )
            )
        ]
        report.withdrawals_to_redo = withdrawals_to_redo(
            read_withdrawal_log(withdrawal_log), restored
        )
    promoted = db.execute(
        select(
            Recording.id,
            Recording.original_object_key,
            Recording.sha256_original,
            Submission.speaker_id,
            Submission.id,
        )
        .join(Submission, Submission.id == Recording.submission_id)
        .where(Recording.upload_status == "promoted")
    ).all()
    expected = [
        (recording_id, key, sha256)
        for recording_id, key, sha256, speaker_id, submission_id in promoted
        if not _covered(speaker_id, submission_id, report.withdrawals_to_redo)
    ]
    report.originals_withdrawn_after_backup = len(promoted) - len(expected)
    rng = rng or random.Random()  # noqa: S311 - choosing a sample, not a secret
    chosen = rng.sample(expected, min(sample, len(expected)))
    report.originals_checked = len(chosen)
    report.originals_problems = check_originals(chosen, store)
    return report
