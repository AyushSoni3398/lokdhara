"""Contract tests: the local and S3 adapters must behave identically (ROADMAP M2)."""

import hashlib
import io
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.config import Settings, get_settings
from app.main import create_app
from app.object_store import (
    Bucket,
    IntegrityError,
    LocalObjectStore,
    ObjectExists,
    ObjectNotFound,
    ObjectStore,
    ObjectTooLarge,
    S3ObjectStore,
    get_object_store,
    new_key,
)

NAMES = {bucket: f"test-{bucket.value.replace('_', '-')}" for bucket in Bucket}
SECRET = "test-secret-key-not-for-real-use"


@pytest.fixture(params=["local", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ObjectStore]:
    if request.param == "local":
        yield LocalObjectStore(tmp_path, NAMES, "http://testserver", SECRET)
        return
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        for name in NAMES.values():
            client.create_bucket(
                Bucket=name, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
            )
        yield S3ObjectStore(client, NAMES)


def _read(store: ObjectStore, bucket: Bucket, key: str) -> bytes:
    return b"".join(store.open(bucket, key))


def test_put_reports_size_and_checksum_and_reads_back(store: ObjectStore) -> None:
    data = os.urandom(3 * 1024 * 1024 + 7)  # spans several chunks
    key = new_key("recordings", uuid.uuid4(), suffix=".webm")
    stored = store.put(Bucket.QUARANTINE, key, io.BytesIO(data), content_type="audio/webm")
    assert stored.size_bytes == len(data)
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert store.head(Bucket.QUARANTINE, key) == len(data)
    assert _read(store, Bucket.QUARANTINE, key) == data
    assert store.sha256_of(Bucket.QUARANTINE, key) == stored.sha256


def test_missing_objects(store: ObjectStore) -> None:
    assert store.head(Bucket.DERIVED, "nothing/here") is None
    with pytest.raises(ObjectNotFound):
        store.open(Bucket.DERIVED, "nothing/here")
    store.delete(Bucket.DERIVED, "nothing/here")  # deleting a missing key is not an error


def test_size_cap_stores_nothing(store: ObjectStore) -> None:
    with pytest.raises(ObjectTooLarge):
        store.put(Bucket.QUARANTINE, "big/one", io.BytesIO(b"x" * 2048), max_bytes=1024)
    assert store.head(Bucket.QUARANTINE, "big/one") is None


@pytest.mark.parametrize("bucket", [Bucket.ORIGINALS, Bucket.CONSENT_EVIDENCE])
def test_write_once_buckets_refuse_overwrite(store: ObjectStore, bucket: Bucket) -> None:
    store.put(bucket, "a/b", io.BytesIO(b"first"))
    with pytest.raises(ObjectExists):
        store.put(bucket, "a/b", io.BytesIO(b"second"))
    assert _read(store, bucket, "a/b") == b"first"


def test_erase_removes_the_object_but_not_its_neighbours(store: ObjectStore) -> None:
    store.put(Bucket.ORIGINALS, "a/b.webm", io.BytesIO(b"voice"))
    store.put(Bucket.ORIGINALS, "a/b.webm2", io.BytesIO(b"other"))
    store.erase(Bucket.ORIGINALS, "a/b.webm")
    store.erase(Bucket.ORIGINALS, "a/b.webm")  # erasing again is not an error
    assert store.head(Bucket.ORIGINALS, "a/b.webm") is None
    assert _read(store, Bucket.ORIGINALS, "a/b.webm2") == b"other"


def test_erase_removes_every_version_in_a_versioned_bucket() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        name = NAMES[Bucket.DERIVED]
        client.create_bucket(
            Bucket=name, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
        store = S3ObjectStore(client, NAMES)
        store.put(Bucket.DERIVED, "a/b", io.BytesIO(b"first"))
        store.put(Bucket.DERIVED, "a/b", io.BytesIO(b"second"))
        store.delete(Bucket.DERIVED, "a/b")  # only hides it behind a delete marker
        store.put(Bucket.DERIVED, "a/bc", io.BytesIO(b"neighbour"))
        store.erase(Bucket.DERIVED, "a/b")
        left = client.list_object_versions(Bucket=name)
        keys = {v["Key"] for v in [*left.get("Versions", []), *left.get("DeleteMarkers", [])]}
        assert keys == {"a/bc"}


def test_derived_files_can_be_regenerated(store: ObjectStore) -> None:
    store.put(Bucket.DERIVED, "a/b", io.BytesIO(b"first"))
    store.put(Bucket.DERIVED, "a/b", io.BytesIO(b"second"))
    assert _read(store, Bucket.DERIVED, "a/b") == b"second"


@pytest.mark.parametrize(
    "key", ["../escape", "a/../../b", "/absolute", "Has Space", "Upper/Case", "", "a//b"]
)
def test_unsafe_keys_are_rejected(store: ObjectStore, key: str) -> None:
    with pytest.raises(ValueError, match="invalid object key"):
        store.put(Bucket.DERIVED, key, io.BytesIO(b"x"))


def test_promotion_copies_byte_identical(store: ObjectStore) -> None:
    data = b"synthetic audio bytes"
    stored = store.put(Bucket.QUARANTINE, "q/1", io.BytesIO(data))
    copy = store.copy_verified(Bucket.QUARANTINE, "q/1", Bucket.ORIGINALS, "o/1", stored.sha256)
    assert copy.sha256 == stored.sha256
    assert _read(store, Bucket.ORIGINALS, "o/1") == data


def test_promotion_refuses_a_changed_source(store: ObjectStore) -> None:
    store.put(Bucket.QUARANTINE, "q/1", io.BytesIO(b"bytes"))
    with pytest.raises(IntegrityError):
        store.copy_verified(Bucket.QUARANTINE, "q/1", Bucket.ORIGINALS, "o/1", "0" * 64)
    assert store.head(Bucket.ORIGINALS, "o/1") is None


@pytest.mark.parametrize("bucket", [Bucket.ORIGINALS, Bucket.QUARANTINE, Bucket.CONSENT_EVIDENCE])
def test_sensitive_buckets_never_get_signed_urls(store: ObjectStore, bucket: Bucket) -> None:
    with pytest.raises(ValueError, match="never handed out"):
        store.signed_url(bucket, "a/b", ttl_seconds=60, content_type="audio/webm")


def test_signed_urls_expire(store: ObjectStore) -> None:
    url = store.signed_url(Bucket.DERIVED, "a/b", ttl_seconds=600, content_type="audio/ogg")
    query = parse_qs(urlsplit(url).query)
    if isinstance(store, S3ObjectStore):
        assert query["X-Amz-Expires"] == ["600"]
    else:
        assert int(query["expires"][0]) <= time.time() + 600
    assert "test-originals" not in url


def test_reachable(store: ObjectStore) -> None:
    assert store.is_reachable()


def test_new_key_contains_only_safe_parts() -> None:
    rid = uuid.uuid4()
    assert new_key("recordings", rid, suffix=".webm") == f"recordings/{rid}.webm"
    with pytest.raises(ValueError):
        new_key("Asha's story")


# ------------------------------------------------- local signed download route


@pytest.fixture
def local_client(tmp_path: Path) -> Iterator[tuple[LocalObjectStore, TestClient]]:
    settings = Settings(_env_file=None, env="test", secret_key=SECRET, local_storage_dir=tmp_path)
    store = LocalObjectStore(tmp_path, NAMES, "http://testserver", SECRET)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_object_store] = lambda: store
    with TestClient(app) as client:
        yield store, client


def test_local_signed_url_downloads_once_valid(
    local_client: tuple[LocalObjectStore, TestClient],
) -> None:
    store, client = local_client
    store.put(Bucket.DERIVED, "play/1.ogg", io.BytesIO(b"opus bytes"))
    url = store.signed_url(Bucket.DERIVED, "play/1.ogg", ttl_seconds=60, content_type="audio/ogg")
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"opus bytes"
    assert response.headers["content-type"].startswith("audio/ogg")


def test_local_signed_url_rejects_tampering_and_expiry(
    local_client: tuple[LocalObjectStore, TestClient],
) -> None:
    store, client = local_client
    store.put(Bucket.DERIVED, "play/1.ogg", io.BytesIO(b"opus bytes"))
    store.put(Bucket.ORIGINALS, "play/1.ogg", io.BytesIO(b"original"))
    url = store.signed_url(Bucket.DERIVED, "play/1.ogg", ttl_seconds=60, content_type="audio/ogg")
    tampered = url.replace("sig=", "sig=0")
    other_bucket = url.replace("/derived/", "/originals/")
    expired = url.replace("expires=", "expires=1")  # a timestamp far in the past
    for bad in (tampered, other_bucket, expired):
        response = client.get(bad)
        assert response.status_code == 403
        assert response.json()["code"] == "signed_url_invalid"
