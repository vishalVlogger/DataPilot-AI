from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.database import session_scope
from app.repositories import JobRepository
from app.schemas.dataset import ReportRequest
from app.services.datasets.storage import get_dataset_storage
from app.services.jobs.executor import get_job_executor
from app.services.object_storage import get_object_storage
from app.services.reports import generate_html_report, generate_pdf_report

logger = logging.getLogger("datapilot.jobs")


def _fingerprint(job_type: str, workspace_id: str, dataset_id: str | None, payload: dict) -> str:
    packed = json.dumps({"type": job_type, "workspace": workspace_id, "dataset": dataset_id, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode()).hexdigest()


class JobManager:
    def create_report_job(self, dataset_id: str, options: ReportRequest, store) -> dict:
        payload = options.model_dump(mode="json"); key = _fingerprint("report", store.workspace_id, dataset_id, payload)
        with session_scope() as session:
            repo = JobRepository(session, store.workspace_id); existing = repo.active_by_idempotency(key)
            if existing: return existing
            job = repo.create("report", dataset_id, "queued", store.user_id, status="queued", retryable=True, max_attempts=3, payload=payload, idempotency_key=key)
        self._enqueue(job["id"]); return job

    def create_workspace_export_job(self, workspace_id: str, user_id: str, include_raw: bool = False) -> dict:
        payload = {"include_raw": include_raw}; key = _fingerprint("workspace_export", workspace_id, None, payload)
        with session_scope() as session:
            repo = JobRepository(session, workspace_id); existing = repo.active_by_idempotency(key)
            if existing: return existing
            job = repo.create("workspace_export", None, "queued", user_id, status="queued", retryable=True, max_attempts=3, payload=payload, idempotency_key=key)
        self._enqueue(job["id"]); return job

    def _enqueue(self, job_id: str, delay: int = 0) -> None:
        executor = get_job_executor()
        if delay: executor.retry_later(job_id, delay, self.run_job, job_id)
        else: executor.submit(job_id, self.run_job, job_id)

    def run_job(self, job_id: str) -> None:
        with session_scope() as session:
            from app.models import Job
            model = session.get(Job, job_id)
            if model is None or model.status == "completed": return
            workspace_id = model.workspace_id; job_type = model.type; dataset_id = model.dataset_id; user_id = model.user_id; payload = model.payload or {}
        try:
            current = self.get(job_id, workspace_id); attempt = current.get("attempt_count", 0) + 1
            self._update(job_id, workspace_id, status="running", stage="starting", progress=5, started_at=datetime.now(timezone.utc), attempt_count=attempt, next_attempt_at=None, last_error=None)
            if job_type == "report": self._run_report(job_id, workspace_id, user_id, dataset_id, payload)
            elif job_type == "workspace_export": self._run_workspace_export(job_id, workspace_id, user_id, payload)
            else: raise ValueError("Unsupported durable job type")
            logger.info("job_completed", extra={"job_id": job_id, "dataset_id": dataset_id, "workspace_id": workspace_id})
        except Exception as exc:
            code = getattr(exc, "error_code", "JOB_FAILED"); current = self.get(job_id, workspace_id); error = str(exc)[:500]
            if current.get("retryable") and current.get("attempt_count", 0) < current.get("max_attempts", 1):
                delay = min(300, 2 ** current.get("attempt_count", 1)); next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
                self._update(job_id, workspace_id, status="retrying", stage="retry scheduled", progress=0, error_code=code, error_message=error, last_error=error, next_attempt_at=next_attempt)
                self._enqueue(job_id, delay)
            else:
                self._update(job_id, workspace_id, status="failed", stage="failed", error_code=code, error_message=error, last_error=error, completed_at=datetime.now(timezone.utc))
                from app.services.operations import send_operational_alert
                send_operational_alert("DURABLE_JOB_FAILED", "A durable background job exhausted its retries.", {"job_id": job_id, "job_type": job_type, "workspace_id": workspace_id})
            logger.exception("job_failed", extra={"job_id": job_id, "dataset_id": dataset_id, "workspace_id": workspace_id})

    def _run_report(self, job_id: str, workspace_id: str, user_id: str | None, dataset_id: str | None, payload: dict) -> None:
        if not dataset_id: raise ValueError("Report dataset is missing")
        options = ReportRequest.model_validate(payload); settings = get_settings(); store = get_dataset_storage(settings.storage_root, settings.parquet_compression, workspace_id, user_id)
        self._update(job_id, workspace_id, stage="loading dataset", progress=15); frame = store.load_frame(dataset_id)
        self._update(job_id, workspace_id, stage="rendering report", progress=70); versions = store.list_versions(dataset_id)
        if options.format == "pdf": content = generate_pdf_report(frame, dataset_id, options, versions); content_type = "application/pdf"; suffix = "pdf"
        else: html, _ = generate_html_report(frame, dataset_id, options, versions); content = html.encode(); content_type = "text/html"; suffix = "html"
        key = f"workspaces/{workspace_id}/reports/{job_id}.{suffix}"; get_object_storage().put(key, content, content_type)
        self._update(job_id, workspace_id, status="completed", stage="complete", progress=100, completed_at=datetime.now(timezone.utc), result_reference=key)
        from app.services.saas import UsageService
        usage = UsageService(workspace_id); usage.record("report", 1, user_id, job_id, {"format": options.format, "async": True}, f"report:{job_id}"); usage.activity("report_generated", user_id, dataset_id, {"format": options.format, "async": True})

    def _run_workspace_export(self, job_id: str, workspace_id: str, user_id: str | None, payload: dict) -> None:
        from app.services.workspace_lifecycle import build_workspace_export
        self._update(job_id, workspace_id, stage="collecting metadata", progress=30)
        content = build_workspace_export(workspace_id, bool(payload.get("include_raw")))
        key = f"workspaces/{workspace_id}/exports/{job_id}.zip"; get_object_storage().put(key, content, "application/zip")
        self._update(job_id, workspace_id, status="completed", stage="complete", progress=100, completed_at=datetime.now(timezone.utc), result_reference=key)
        from app.services.saas import UsageService
        UsageService(workspace_id).record("export", 1, user_id, job_id, {"type": "workspace", "include_raw": bool(payload.get("include_raw"))}, f"workspace-export:{job_id}")

    def _update(self, job_id: str, workspace_id: str, **values) -> None:
        with session_scope() as session: JobRepository(session, workspace_id).update(job_id, **values)
    def get(self, job_id: str, workspace_id: str) -> dict:
        with session_scope() as session: return JobRepository(session, workspace_id).get(job_id)
    def retry(self, job_id: str, store) -> dict:
        job = self.get(job_id, store.workspace_id)
        if job["type"] not in {"report", "workspace_export"} or not job.get("retryable"): raise ValueError("This job is not retryable.")
        if job["status"] != "failed": raise ValueError("Only failed jobs can be retried.")
        with session_scope() as session: retried = JobRepository(session, store.workspace_id).update(job_id, status="queued", stage="manual retry queued", progress=0, completed_at=None, error_code=None, error_message=None, attempt_count=0, next_attempt_at=None)
        self._enqueue(job_id); return retried
