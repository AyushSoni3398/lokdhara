"""Periodic jobs (ADR-019 left scheduling to a small loop in the worker).

Every worker calls `Scheduler.tick()` between jobs. At most once a minute it queues each
periodic job whose last run was queued longer ago than its interval. With several workers the
dedupe key keeps it to one pending job of each kind.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.modules.processing.models import Job
from app.modules.processing.queue import enqueue, utcnow

PERIODIC: dict[str, timedelta] = {
    "cleanup.expire_drafts": timedelta(hours=1),
}


def enqueue_due(db: Session, now: datetime | None = None) -> list[str]:
    """Queues the periodic jobs that are due and commits. Returns the job types queued."""
    now = now or utcnow()
    queued = []
    for job_type, every in PERIODIC.items():
        last = db.scalar(select(func.max(Job.created_at)).where(Job.job_type == job_type))
        if last is not None and last > now - every:
            continue
        if enqueue(db, job_type, dedupe_key=job_type) is not None:
            queued.append(job_type)
    db.commit()
    return queued


class Scheduler:
    def __init__(
        self,
        engine: Engine,
        check_every_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._check_every = check_every_seconds
        self._clock = clock
        self._next_check: float | None = None

    def tick(self) -> None:
        if self._next_check is not None and self._clock() < self._next_check:
            return
        self._next_check = self._clock() + self._check_every
        with Session(self._engine) as db:
            enqueue_due(db)
