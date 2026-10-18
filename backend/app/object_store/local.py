"""Filesystem adapter for development and tests. One directory per bucket."""

import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlencode

from app.object_store.base import (
    CHUNK_SIZE,
    SIGNABLE,
    WRITE_ONCE,
    Bucket,
    ObjectExists,
    ObjectNotFound,
    ObjectStore,
    Readable,
    StoredObject,
    _HashingReader,
    attachment_header,
    validate_key,
)
from app.security import constant_time_equals, keyed_hash

LOCAL_URL_PATH = "/api/v1/local-storage"


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path, bucket_names: dict[Bucket, str], base_url: str, secret: str):
        self._root = root.resolve()
        self._names = bucket_names
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        for name in bucket_names.values():
            (self._root / name).mkdir(parents=True, exist_ok=True)
        (self._root / ".tmp").mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: Bucket, key: str) -> Path:
        base = self._root / self._names[bucket]
        path = (base / validate_key(key)).resolve()
        if not path.is_relative_to(base):  # defence in depth; validate_key already forbids ".."
            raise ValueError("invalid object key")
        return path

    def put(
        self,
        bucket: Bucket,
        key: str,
        stream: Readable,
        *,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> StoredObject:
        path = self._path(bucket, key)
        if bucket in WRITE_ONCE and path.exists():
            raise ObjectExists(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        reader = _HashingReader(stream, max_bytes)
        fd, tmp_name = tempfile.mkstemp(dir=self._root / ".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := reader.read(CHUNK_SIZE):
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if bucket in WRITE_ONCE:
                try:
                    os.link(tmp, path)  # fails if the key appeared meanwhile
                except FileExistsError:
                    raise ObjectExists(key) from None
            else:
                os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return StoredObject(key=key, size_bytes=reader.size, sha256=reader.sha256)

    def open(self, bucket: Bucket, key: str) -> Iterator[bytes]:
        path = self._path(bucket, key)
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            raise ObjectNotFound(key) from None
        return self._iterate(handle)

    @staticmethod
    def _iterate(handle: BinaryIO) -> Iterator[bytes]:
        with handle:
            while chunk := handle.read(CHUNK_SIZE):
                yield chunk

    def head(self, bucket: Bucket, key: str) -> int | None:
        path = self._path(bucket, key)
        return path.stat().st_size if path.is_file() else None

    def delete(self, bucket: Bucket, key: str) -> None:
        self._path(bucket, key).unlink(missing_ok=True)

    def erase(self, bucket: Bucket, key: str) -> None:
        self.delete(bucket, key)  # the local store keeps no earlier versions

    def _signature(
        self, bucket: Bucket, key: str, expires: int, content_type: str, download_name: str
    ) -> str:
        return keyed_hash(
            self._secret, "local-url", f"{bucket}:{key}:{expires}:{content_type}:{download_name}"
        )

    def signed_url(
        self,
        bucket: Bucket,
        key: str,
        *,
        ttl_seconds: int,
        content_type: str,
        download_name: str | None = None,
    ) -> str:
        if bucket not in SIGNABLE:
            raise ValueError(f"{bucket} objects are never handed out as URLs")
        validate_key(key)
        if download_name is not None:
            attachment_header(download_name)  # rejects unsafe names
        expires = int(time.time()) + ttl_seconds
        params: dict[str, str | int] = {"expires": expires, "ct": content_type}
        if download_name is not None:
            params["dl"] = download_name
        params["sig"] = self._signature(bucket, key, expires, content_type, download_name or "")
        query = urlencode(params)
        return f"{self._base_url}{LOCAL_URL_PATH}/{bucket}/{key}?{query}"

    def verify_signed(
        self,
        bucket: Bucket,
        key: str,
        expires: int,
        content_type: str,
        signature: str,
        download_name: str = "",
    ) -> bool:
        if bucket not in SIGNABLE or expires < time.time():
            return False
        expected = self._signature(bucket, key, expires, content_type, download_name)
        return constant_time_equals(signature, expected)

    def is_reachable(self) -> bool:
        return all(os.access(self._root / name, os.W_OK) for name in self._names.values())
