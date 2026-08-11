import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from app.core.database import session_scope
from app.repositories import JobRepository
from app.schemas.dataset import ReportRequest
from app.services.datasets.storage import DatasetStorage
from app.services.reports import generate_html_report, generate_pdf_report

logger = logging.getLogger("datapilot.jobs")


class JobManager:
    def create_report_job(self, dataset_id: str, options: ReportRequest, store: DatasetStorage) -> dict:
        with session_scope() as session: job = JobRepository(session, store.workspace_id).create("report", dataset_id, "queued", store.user_id)
        Thread(target=self._run_report, args=(job["id"], dataset_id, options, store.root, store.compression, store.workspace_id, store.user_id), daemon=True).start()
        return job

    def _run_report(self, job_id: str, dataset_id: str, options: ReportRequest, root: Path, compression: str, workspace_id: str, user_id: str | None) -> None:
        try:
            self._update(job_id, workspace_id, status="running", stage="loading dataset", progress=10, started_at=datetime.now(timezone.utc))
            store = DatasetStorage(root, compression, workspace_id, user_id); frame = store.load_frame(dataset_id)
            self._update(job_id, workspace_id, stage="calculating metrics", progress=35)
            versions = store.list_versions(dataset_id); reports = store._folder(dataset_id) / "reports"; reports.mkdir(exist_ok=True)
            self._update(job_id, workspace_id, stage="rendering report", progress=70)
            if options.format == "pdf": content = generate_pdf_report(frame, dataset_id, options, versions); path = reports / f"{job_id}.pdf"; path.write_bytes(content)
            else: content, _ = generate_html_report(frame, dataset_id, options, versions); path = reports / f"{job_id}.html"; path.write_text(content, encoding="utf-8")
            self._update(job_id, workspace_id, status="completed", stage="complete", progress=100, completed_at=datetime.now(timezone.utc), result_reference=str(path))
            logger.info("job_completed", extra={"job_id": job_id, "dataset_id": dataset_id})
        except Exception as exc:
            code = getattr(exc, "error_code", "JOB_FAILED"); self._update(job_id, workspace_id, status="failed", stage="failed", error_code=code, error_message=str(exc)[:500], completed_at=datetime.now(timezone.utc)); logger.exception("job_failed", extra={"job_id": job_id, "dataset_id": dataset_id})

    def _update(self, job_id: str, workspace_id: str, **values) -> None:
        with session_scope() as session: JobRepository(session, workspace_id).update(job_id, **values)

    def get(self, job_id: str, workspace_id: str) -> dict:
        with session_scope() as session: return JobRepository(session, workspace_id).get(job_id)
