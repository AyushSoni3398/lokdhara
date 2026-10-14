"""Background worker entrypoint. Run with: uv run python -m app.worker

Claims jobs from the PostgreSQL queue (ADR-019) one at a time; run more processes for more
throughput. Between jobs it queues periodic jobs that are due (app.modules.processing.schedule).
Stops cleanly on SIGINT/SIGTERM after the current job.
"""

import argparse
import logging
import os
import signal
import socket
import threading
from collections.abc import Callable
from types import FrameType

from app.config import get_settings
from app.db import get_engine
from app.modules.processing import handlers  # noqa: F401 - registers job handlers
from app.modules.processing.queue import process_one
from app.modules.processing.schedule import Scheduler

logger = logging.getLogger("lokdhara.worker")


def run(
    stop: threading.Event,
    process: Callable[[], bool],
    poll_seconds: float,
    max_iterations: int | None = None,
) -> int:
    """Processes jobs until `stop` is set, sleeping when the queue is empty.

    Returns the number of loop iterations (each either ran one job or found none).
    """
    iterations = 0
    while not stop.is_set():
        iterations += 1
        try:
            did_work = process()
        except Exception:
            # Database unreachable or similar: back off rather than crash-loop.
            logger.exception("worker iteration failed")
            did_work = False
        if max_iterations is not None and iterations >= max_iterations:
            break
        if not did_work:
            stop.wait(poll_seconds)
    return iterations


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokdhara background worker")
    parser.add_argument("--once", action="store_true", help="run one iteration and exit")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    stop = threading.Event()

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("worker stopping", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    engine = get_engine()
    me = worker_id()
    scheduler = Scheduler(engine)
    logger.info("worker started", extra={"worker_id": me})

    def process() -> bool:
        scheduler.tick()
        return process_one(engine, me, settings.worker_lease_seconds)

    run(
        stop,
        process,
        settings.worker_poll_seconds,
        max_iterations=1 if args.once else None,
    )


if __name__ == "__main__":
    main()
