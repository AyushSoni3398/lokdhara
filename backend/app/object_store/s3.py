"""S3-compatible adapter for staging and production (ADR-006)."""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.object_store.base import (
    CHUNK_SIZE,
    SIGNABLE,
    WRITE_ONCE,
    Bucket,
    ObjectExists,
    ObjectNotFound,
    ObjectStore,
    Readable,
    StorageError,
    StoredObject,
    _HashingReader,
    attachment_header,
    validate_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef


def _is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound"}


class S3ObjectStore(ObjectStore):
    def __init__(self, client: "S3Client", bucket_names: dict[Bucket, str]) -> None:
        self._client = client
        self._names = bucket_names

    @classmethod
    def from_settings(
        cls, bucket_names: dict[Bucket, str], **client_options: Any
    ) -> "S3ObjectStore":
        path_style = client_options.pop("force_path_style", False)
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        client = boto3.client("s3", config=config, **client_options)
        return cls(client, bucket_names)

    def put(
        self,
        bucket: Bucket,
        key: str,
        stream: Readable,
        *,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> StoredObject:
        validate_key(key)
        # Bucket versioning (and object lock where offered) protects originals too;
        # this check stops the application from overwriting them.
        if bucket in WRITE_ONCE and self.head(bucket, key) is not None:
            raise ObjectExists(key)
        reader = _HashingReader(stream, max_bytes)
        # An exception raised by the reader (e.g. ObjectTooLarge) aborts the upload.
        self._client.upload_fileobj(
            reader,  # type: ignore[arg-type]
            self._names[bucket],
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return StoredObject(key=key, size_bytes=reader.size, sha256=reader.sha256)

    def open(self, bucket: Bucket, key: str) -> Iterator[bytes]:
        try:
            response = self._client.get_object(Bucket=self._names[bucket], Key=validate_key(key))
        except ClientError as error:
            if _is_not_found(error):
                raise ObjectNotFound(key) from None
            raise
        return response["Body"].iter_chunks(CHUNK_SIZE)

    def head(self, bucket: Bucket, key: str) -> int | None:
        try:
            response = self._client.head_object(Bucket=self._names[bucket], Key=validate_key(key))
        except ClientError as error:
            if _is_not_found(error):
                return None
            raise
        return response["ContentLength"]

    def delete(self, bucket: Bucket, key: str) -> None:
        self._client.delete_object(Bucket=self._names[bucket], Key=validate_key(key))

    def erase(self, bucket: Bucket, key: str) -> None:
        """Deleting a key in a versioned bucket only adds a delete marker, so every version
        and marker of exactly this key is deleted by its version ID."""
        name = self._names[bucket]
        validate_key(key)
        paginator = self._client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=name, Prefix=key):
            found = [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
            versions: list[ObjectIdentifierTypeDef] = [
                {"Key": key, "VersionId": v["VersionId"]} for v in found if v.get("Key") == key
            ]
            if versions:
                result = self._client.delete_objects(
                    Bucket=name, Delete={"Objects": versions, "Quiet": True}
                )
                if result.get("Errors"):
                    raise StorageError("some versions could not be deleted")
        self.delete(bucket, key)  # unversioned buckets list nothing above

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
        params = {
            "Bucket": self._names[bucket],
            "Key": validate_key(key),
            "ResponseContentType": content_type,
        }
        if download_name is not None:
            params["ResponseContentDisposition"] = attachment_header(download_name)
        return self._client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=ttl_seconds
        )

    def is_reachable(self) -> bool:
        try:
            for name in self._names.values():
                self._client.head_bucket(Bucket=name)
        except (ClientError, BotoCoreError):
            return False
        return True
