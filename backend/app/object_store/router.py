"""Serves signed downloads for the local storage adapter (development only).

In staging and production the S3 provider serves signed URLs directly; this route is not mounted.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.errors import ApiError
from app.object_store import Bucket, ObjectNotFound, ObjectStore, get_object_store
from app.object_store.base import attachment_header
from app.object_store.local import LocalObjectStore

router = APIRouter(tags=["dev-storage"], include_in_schema=False)


@router.get("/local-storage/{bucket}/{key:path}")
def download(
    bucket: Bucket,
    key: str,
    store: Annotated[ObjectStore, Depends(get_object_store)],
    expires: Annotated[int, Query()],
    ct: Annotated[str, Query(max_length=100)],
    sig: Annotated[str, Query(max_length=128)],
    dl: Annotated[str, Query(max_length=100)] = "",
) -> StreamingResponse:
    invalid = ApiError(403, "signed_url_invalid", "This link is not valid or has expired.")
    if not isinstance(store, LocalObjectStore):
        raise invalid
    try:
        valid = store.verify_signed(bucket, key, expires, ct, sig, dl)
    except ValueError:
        valid = False
    if not valid:
        raise invalid
    try:
        chunks = store.open(bucket, key)
    except ObjectNotFound:
        raise ApiError(404, "object_not_found", "File not found.") from None
    headers = {"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"}
    if dl:
        headers["Content-Disposition"] = attachment_header(dl)
    return StreamingResponse(chunks, media_type=ct, headers=headers)
