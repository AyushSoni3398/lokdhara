"""Samples the job queue while the load test runs, to show whether the worker keeps up.

    uv run --group loadtest python -m loadtest.monitor --out loadtest/results/queue.csv

Writes one CSV row per interval: jobs waiting, running, finished, and failed, and
submissions still being processed. Counts only, never content.
"""

import argparse
import csv
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import get_settings

COLUMNS = ("queued", "running", "succeeded", "failed", "processing", "recordings")
QUERY = text(
    """
    SELECT
      (SELECT count(*) FROM jobs WHERE status = 'queued') AS queued,
      (SELECT count(*) FROM jobs WHERE status = 'running') AS running,
      (SELECT count(*) FROM jobs WHERE status = 'succeeded') AS succeeded,
      (SELECT count(*) FROM jobs WHERE status = 'failed') AS failed,
      (SELECT count(*) FROM submissions WHERE status = 'processing') AS processing,
      (SELECT count(*) FROM recordings) AS recordings
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m loadtest.monitor")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    engine = create_engine(get_settings().database_url)
    with args.out.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["time", *COLUMNS])
        while not stop.is_set():
            with engine.connect() as connection:
                row = connection.execute(QUERY).one()
            writer.writerow([datetime.now(UTC).isoformat(timespec="seconds"), *row])
            file.flush()
            stop.wait(args.interval)


if __name__ == "__main__":
    main()
