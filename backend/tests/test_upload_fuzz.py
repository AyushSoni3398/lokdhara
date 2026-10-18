"""Broken uploads end in a clear decision, never a stuck job or a kept file (security review).

Each supported format is cut short, has bytes overwritten, or keeps only its header, then goes
through the same worker checks as a real recording.
"""

import random
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.processing.models import Job
from app.object_store import Bucket, ObjectStore
from tests.audio_fixtures import ENCODINGS, make_audio, requires_ffmpeg
from tests.conftest import requires_postgres
from tests.test_audio_jobs import (  # noqa: F401 - fixtures
    fetch,
    run_jobs,
    speaker_id,
    submit_audio,
    worker_uses_test_storage,
)

pytestmark = [requires_postgres, requires_ffmpeg]

REJECTION_CODES = {"unsupported_format", "corrupt_audio", "out_of_range"}


def _cut(fraction: float) -> Callable[[bytes], bytes]:
    return lambda data: data[: max(16, int(len(data) * fraction))]


def _scramble(data: bytes) -> bytes:
    rng = random.Random(len(data))  # noqa: S311 - repeatable test data
    damaged = bytearray(data)
    for _ in range(64):
        damaged[rng.randrange(64, len(damaged))] = rng.randrange(256)
    return bytes(damaged)


def _header_then_noise(data: bytes) -> bytes:
    rng = random.Random(7)  # noqa: S311 - repeatable test data
    return data[:64] + rng.randbytes(len(data) - 64)


MUTATIONS: dict[str, Callable[[bytes], bytes]] = {
    "cut_to_tenth": _cut(0.1),
    "cut_to_ninety_percent": _cut(0.9),
    "scrambled": _scramble,
    "header_then_noise": _header_then_noise,
}


@pytest.mark.parametrize("mutation", MUTATIONS)
@pytest.mark.parametrize("container", ENCODINGS)
def test_a_broken_upload_is_decided_and_leaves_nothing_in_quarantine(
    client: TestClient,
    speaker_id: str,  # noqa: F811
    engine: Engine,
    db: Session,
    object_store: ObjectStore,
    tmp_path: Path,
    container: str,
    mutation: str,
) -> None:
    rate = 48000 if container in ("webm", "ogg") else 44100
    whole = make_audio(tmp_path / "input", container, seconds=3, rate=rate)
    recording_id = submit_audio(client, speaker_id, MUTATIONS[mutation](whole))
    run_jobs(engine)

    recording, submission = fetch(db, recording_id)
    key = recording.original_object_key
    if recording.upload_status == "promoted":  # some formats still play when cut short
        assert object_store.sha256_of(Bucket.ORIGINALS, key) == recording.sha256_original
    else:
        assert recording.upload_status == "rejected_invalid"
        assert recording.validation_errors is not None
        assert recording.validation_errors["code"] in REJECTION_CODES
        assert submission.status == "rejected_invalid"
        assert object_store.head(Bucket.ORIGINALS, key) is None
    assert object_store.head(Bucket.QUARANTINE, key) is None
    unfinished = db.scalars(select(Job).where(Job.status != "succeeded")).all()
    assert [(job.job_type, job.status, job.last_error_code) for job in unfinished] == []
