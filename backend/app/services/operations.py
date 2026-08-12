from __future__ import annotations

import json
import logging
import smtplib
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import session_scope
from app.models import Dataset, DatasetVersion
from app.services.jobs.executor import queue_diagnostics
from app.services.object_storage import LocalObjectStorage, S3ObjectStorage, get_object_storage, sha256_bytes

logger = logging.getLogger("datapilot.operations")


def test_database() -> dict:
    settings = get_settings(); engine = settings.database_url.split(":", 1)[0]
    with session_scope() as session:
        session.execute(text("SELECT 1")); transaction = session.begin_nested(); session.execute(text("SELECT 1")); transaction.rollback()
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    config = Config(str(Path(__file__).parents[2] / "alembic.ini")); script = ScriptDirectory.from_config(config)
    with session_scope() as session: current = MigrationContext.configure(session.connection()).get_current_revision()
    return {"status": "pass" if current == script.get_current_head() else "fail", "engine": engine, "migration": current, "head": script.get_current_head()}


def test_redis() -> dict:
    settings = get_settings()
    if not settings.redis_url: return {"status": "skip", "reason": "REDIS_URL is not configured"}
    from redis import Redis
    redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1); prefix = f"datapilot:test:{uuid4()}"
    try:
        redis.ping(); redis.incr(f"{prefix}:counter"); redis.rpush(f"{prefix}:queue", "probe"); assert redis.lpop(f"{prefix}:queue") == "probe"
        return {"status": "pass"}
    finally:
        for key in redis.scan_iter(f"{prefix}:*"): redis.delete(key)


def test_storage() -> dict:
    storage = get_object_storage(); key = f"system-tests/{uuid4()}.txt"; content = b"DataPilot storage validation"
    try:
        checksum = storage.put(key, content, "text/plain"); loaded = storage.get(key)
        return {"status": "pass" if loaded == content and checksum == sha256_bytes(content) else "fail", "backend": storage.backend, "checksum": checksum}
    finally: storage.delete(key)


def verify_storage(check_checksums: bool = True) -> dict:
    objects = get_object_storage(); missing = []; mismatches = []; checked = 0
    with session_scope() as session: versions = session.scalars(select(DatasetVersion)).all()
    for version in versions:
        checked += 1
        if not objects.exists(version.storage_key): missing.append({"dataset_id": version.dataset_id, "version": version.version}); continue
        if check_checksums and version.checksum_sha256 and sha256_bytes(objects.get(version.storage_key)) != version.checksum_sha256: mismatches.append({"dataset_id": version.dataset_id, "version": version.version})
    return {"status": "pass" if not missing and not mismatches else "fail", "checked": checked, "missing": missing, "checksum_mismatches": mismatches}


def migrate_local_to_s3(dry_run: bool = True) -> dict:
    settings = get_settings(); local = LocalObjectStorage(settings.storage_root); remote = S3ObjectStorage(settings); copied = skipped = failed = 0; failures = []
    with session_scope() as session: versions = session.scalars(select(DatasetVersion)).all()
    for version in versions:
        target = f"workspaces/{version.workspace_id}/datasets/{version.dataset_id}/versions/{version.version}.parquet"
        try:
            content = local.get(version.storage_key); checksum = sha256_bytes(content)
            already_present = remote.exists(target) and sha256_bytes(remote.get(target)) == checksum
            if already_present: skipped += 1
            else:
                if not dry_run: remote.put(target, content, "application/vnd.apache.parquet")
                copied += 1
            if not dry_run:
                with session_scope() as update_session:
                    current = update_session.get(DatasetVersion, version.id); current.storage_key = target; current.checksum_sha256 = checksum
                    if current.is_current:
                        dataset = update_session.get(Dataset, current.dataset_id)
                        if dataset: dataset.storage_key = target
                    update_session.commit()
        except Exception as exc: failed += 1; failures.append({"dataset_id": version.dataset_id, "version": version.version, "error": str(exc)[:200]})
    return {"dry_run": dry_run, "copied": copied, "skipped": skipped, "failed": failed, "failures": failures}


def backup_manifest() -> dict:
    settings = get_settings()
    with session_scope() as session:
        datasets = int(session.scalar(select(func.count()).select_from(Dataset)) or 0); versions = int(session.scalar(select(func.count()).select_from(DatasetVersion)) or 0)
    return {"backup_id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), "app_version": settings.app_version, "database": settings.database_url.split(":", 1)[0], "storage_backend": settings.dataset_storage_backend, "dataset_count": datasets, "version_count": versions, "note": "Manifest only; no database backup was created."}


def production_readiness() -> dict:
    settings = get_settings(); checks = {"configuration": settings.readiness_errors()}
    try: checks["database"] = test_database()
    except Exception as exc: checks["database"] = {"status": "fail", "reason": str(exc)}
    try: checks["storage"] = test_storage()
    except Exception as exc: checks["storage"] = {"status": "fail", "reason": str(exc)}
    if settings.job_execution_mode == "redis" or settings.rate_limit_backend == "redis":
        try: checks["redis"] = test_redis()
        except Exception as exc: checks["redis"] = {"status": "fail", "reason": str(exc)}
    failed = bool(checks["configuration"]) or any(value.get("status") == "fail" for value in checks.values() if isinstance(value, dict))
    return {"status": "fail" if failed else "pass", "checks": checks}


def infrastructure_status() -> dict:
    settings = get_settings(); result = {"database": "ok", "storage": "ok", "redis": "not configured", "worker": queue_diagnostics()}
    try: test_database()
    except Exception: result["database"] = "unavailable"
    try:
        storage = get_object_storage(); result["storage"] = {"status": "ok", "backend": storage.backend}
    except Exception: result["storage"] = {"status": "unavailable", "backend": settings.dataset_storage_backend}
    redis_required = settings.job_execution_mode.casefold() == "redis" or settings.rate_limit_backend.casefold() == "redis"
    if redis_required:
        try: result["redis"] = "ok" if test_redis()["status"] == "pass" else "unavailable"
        except Exception: result["redis"] = "unavailable"
    return result


class LogAlertProvider:
    def send_alert(self, code: str, message: str, details: dict | None = None) -> None:
        logger.error("operational_alert", extra={"error_code": code, "safe_message": message, "details": details or {}})


_local_alerts: dict[str, float] = {}


def send_operational_alert(code: str, message: str, details: dict | None = None) -> bool:
    """Emit a privacy-safe alert once per configured cooldown window."""
    settings = get_settings(); signature = hashlib.sha256(f"{code}:{message}".encode()).hexdigest(); now = time.monotonic()
    allowed = False
    if settings.redis_url:
        try:
            from redis import Redis
            allowed = bool(Redis.from_url(settings.redis_url).set(f"datapilot:alert:{signature}", "1", nx=True, ex=settings.alert_cooldown_seconds))
        except Exception: allowed = now >= _local_alerts.get(signature, 0)
    else: allowed = now >= _local_alerts.get(signature, 0)
    if not allowed: return False
    _local_alerts[signature] = now + settings.alert_cooldown_seconds
    LogAlertProvider().send_alert(code, message, details)
    return True
