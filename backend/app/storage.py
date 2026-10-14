"""Immutable, content-addressed raw file storage (local filesystem or S3-compatible)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

from .config import get_settings


class RawStore(Protocol):
    def put(self, data: bytes, *, source_key: str) -> tuple[str, str]: ...
    def get(self, storage_key: str) -> bytes: ...


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalRawStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put(self, data: bytes, *, source_key: str) -> tuple[str, str]:
        digest = sha256_hex(data)
        key = f"{source_key}/{digest[:2]}/{digest}"
        path = self.root / key
        if not path.exists():  # write-once: an existing object is never overwritten
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            path.chmod(0o444)
        return key, digest

    def get(self, storage_key: str) -> bytes:
        path = (self.root / storage_key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("invalid storage key")
        data = path.read_bytes()
        if sha256_hex(data) != storage_key.rsplit("/", 1)[-1]:
            raise OSError(f"integrity check failed for {storage_key}")
        return data


class S3RawStore:
    """S3 bucket with versioning + Object Lock (governance) configured by IaC."""

    def __init__(self, bucket: str, endpoint: str | None) -> None:
        import boto3  # noqa: PLC0415

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint)

    def put(self, data: bytes, *, source_key: str) -> tuple[str, str]:
        digest = sha256_hex(data)
        key = f"{source_key}/{digest[:2]}/{digest}"
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.ClientError:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ChecksumAlgorithm="SHA256", ServerSideEncryption="aws:kms"
            )
        return key, digest

    def get(self, storage_key: str) -> bytes:
        data = self.client.get_object(Bucket=self.bucket, Key=storage_key)["Body"].read()
        if sha256_hex(data) != storage_key.rsplit("/", 1)[-1]:
            raise OSError(f"integrity check failed for {storage_key}")
        return data


def get_store() -> RawStore:
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.storage_s3_bucket:
            raise RuntimeError("ELECTION_STORAGE_S3_BUCKET is required for the s3 backend")
        return S3RawStore(s.storage_s3_bucket, s.storage_s3_endpoint)
    return LocalRawStore(s.storage_local_path)
