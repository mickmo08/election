from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from ..auth import Principal, principal, require
from ..config import get_settings
from ..ratelimit import TokenBucket, client_key, enforce

_general = TokenBucket(get_settings().rate_limit_per_minute)
_assistant = TokenBucket(get_settings().assistant_rate_limit_per_minute, burst=5)


def rate_limited(request: Request) -> None:
    enforce(_general, client_key(request))


def assistant_rate_limited(p: Principal = Depends(require("assistant:query"))) -> Principal:
    enforce(_assistant, f"{p.tenant_id}:{p.user_id}")
    return p


async def read_upload(request: Request, file) -> bytes:  # type: ignore[no-untyped-def]
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"upload exceeds {limit} bytes")
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".jsonl", ".json", ".zip")):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "only .csv, .jsonl, .json or .zip uploads")
    if name.endswith(".zip") and not data.startswith(b"PK"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "file content does not match .zip")
    if name.endswith((".csv", ".jsonl", ".json")) and b"\x00" in data[:4096]:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "binary content in a text upload")
    return data


__all__ = ["Principal", "principal", "require", "rate_limited", "assistant_rate_limited", "read_upload"]
