from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from app.core.config import Settings, get_settings
from app.core.errors import AppError


def safe_object_key(key: str) -> str:
    normalized = key.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise AppError("Storage key is invalid.", "STORAGE_KEY_INVALID", 400)
    return normalized


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ObjectStorage(ABC):
    backend: str

    @abstractmethod
    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str: ...
    @abstractmethod
    def get(self, key: str) -> bytes: ...
    @abstractmethod
    def exists(self, key: str) -> bool: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    def list(self, prefix: str) -> Iterable[str]: ...


class LocalObjectStorage(ObjectStorage):
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(); self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        target = (self.root / safe_object_key(key)).resolve()
        if self.root not in target.parents: raise AppError("Storage key is invalid.", "STORAGE_KEY_INVALID", 400)
        return target

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        target = self.path(key); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content); return sha256_bytes(content)

    def get(self, key: str) -> bytes:
        target = self.path(key)
        if not target.is_file(): raise AppError("Stored object is unavailable.", "STORAGE_OBJECT_NOT_FOUND", 404)
        return target.read_bytes()

    def exists(self, key: str) -> bool: return self.path(key).is_file()
    def delete(self, key: str) -> None: self.path(key).unlink(missing_ok=True)
    def list(self, prefix: str) -> Iterable[str]:
        base = self.path(prefix)
        if not base.exists(): return []
        return [str(item.relative_to(self.root)).replace("\\", "/") for item in base.rglob("*") if item.is_file()]


class S3ObjectStorage(ObjectStorage):
    backend = "s3"

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        if not settings.s3_bucket: raise AppError("S3_BUCKET is required.", "STORAGE_BACKEND_INVALID", 503)
        try:
            import boto3
            self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region or "us-east-1", aws_access_key_id=settings.s3_access_key_id, aws_secret_access_key=settings.s3_secret_access_key, use_ssl=settings.s3_use_ssl)
        except Exception as exc: raise AppError("Unable to configure object storage.", "STORAGE_BACKEND_INVALID", 503) from exc
        self.bucket = settings.s3_bucket

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        key = safe_object_key(key); checksum = sha256_bytes(content)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type, Metadata={"sha256": checksum})
        return checksum

    def get(self, key: str) -> bytes:
        try: return self.client.get_object(Bucket=self.bucket, Key=safe_object_key(key))["Body"].read()
        except Exception as exc: raise AppError("Stored object is unavailable.", "STORAGE_OBJECT_NOT_FOUND", 404) from exc

    def exists(self, key: str) -> bool:
        try: self.client.head_object(Bucket=self.bucket, Key=safe_object_key(key)); return True
        except Exception: return False

    def delete(self, key: str) -> None: self.client.delete_object(Bucket=self.bucket, Key=safe_object_key(key))
    def list(self, prefix: str) -> Iterable[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        return [item["Key"] for page in paginator.paginate(Bucket=self.bucket, Prefix=safe_object_key(prefix)) for item in page.get("Contents", [])]


def get_object_storage(backend: str | None = None) -> ObjectStorage:
    settings = get_settings(); selected = (backend or settings.dataset_storage_backend).casefold()
    if selected == "local": return LocalObjectStorage(settings.storage_root)
    if selected == "s3": return S3ObjectStorage(settings)
    raise AppError("Configured storage backend is unavailable.", "STORAGE_BACKEND_UNAVAILABLE", 503)
