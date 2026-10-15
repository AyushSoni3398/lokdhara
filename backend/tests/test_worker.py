import threading

from app.worker import run


def test_worker_runs_requested_iterations() -> None:
    calls: list[int] = []

    def process() -> bool:
        calls.append(1)
        return False

    assert run(threading.Event(), process, poll_seconds=0.01, max_iterations=3) == 3
    assert len(calls) == 3


def test_worker_stops_when_signalled() -> None:
    stop = threading.Event()
    stop.set()
    assert run(stop, lambda: True, poll_seconds=0.01) == 0


def test_worker_survives_a_failing_iteration() -> None:
    def process() -> bool:
        raise ConnectionError("database restarting")

    assert run(threading.Event(), process, poll_seconds=0.01, max_iterations=2) == 2


def test_worker_can_stop_once_the_queue_is_empty() -> None:
    due = [True, True, False, True]

    def process() -> bool:
        return due.pop(0)

    assert run(threading.Event(), process, poll_seconds=0.01, until_idle=True) == 3
    assert due == [True]
