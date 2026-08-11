from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.core.database import session_scope
from app.core.errors import AppError
from app.models import Workspace
from app.repositories import ActivityRepository, UsageRepository


@dataclass(frozen=True)
class PlanDefinition:
    datasets: int
    storage_bytes: int
    upload_bytes: int
    rows_per_dataset: int
    analyses_per_month: int
    reports_per_month: int
    ai_requests_per_month: int


PLANS = {
    "free": PlanDefinition(5, 100 * 1024 * 1024, 25 * 1024 * 1024, 100_000, 50, 5, 50),
    "pro": PlanDefinition(50, 5 * 1024 * 1024 * 1024, 100 * 1024 * 1024, 1_000_000, 2_000, 200, 2_000),
    "business": PlanDefinition(500, 100 * 1024 * 1024 * 1024, 500 * 1024 * 1024, 5_000_000, 20_000, 2_000, 20_000),
}


def month_start() -> datetime:
    now = datetime.now(timezone.utc); return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


class UsageService:
    def __init__(self, workspace_id: str) -> None: self.workspace_id = workspace_id
    def plan(self) -> tuple[str, PlanDefinition]:
        with session_scope() as session:
            workspace = session.get(Workspace, self.workspace_id)
            if workspace is None: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
            return workspace.plan_code, PLANS.get(workspace.plan_code, PLANS["free"])
    def summary(self) -> dict:
        plan_code, plan = self.plan(); since = month_start()
        with session_scope() as session:
            usage = UsageRepository(session, self.workspace_id)
            result = {"plan_code": plan_code, "datasets": usage.dataset_count(), "storage_bytes": usage.storage_bytes(), "analyses_this_month": usage.total("analysis", since), "ai_requests_this_month": usage.total("ai_request", since), "reports_this_month": usage.total("report", since), "rows_this_month": usage.total("rows_uploaded", since)}
        limits = asdict(plan); result["limits"] = limits
        result["percentages"] = {"datasets": round(result["datasets"] / plan.datasets * 100, 1), "storage": round(result["storage_bytes"] / plan.storage_bytes * 100, 1), "analyses": round(result["analyses_this_month"] / plan.analyses_per_month * 100, 1), "reports": round(result["reports_this_month"] / plan.reports_per_month * 100, 1)}
        return result
    def enforce_upload(self, content_bytes: int, rows: int | None = None) -> None:
        _, plan = self.plan(); summary = self.summary()
        if summary["datasets"] >= plan.datasets: raise AppError("Your plan's dataset limit has been reached.", "QUOTA_DATASET_LIMIT", 403)
        if content_bytes > plan.upload_bytes: raise AppError("This upload exceeds your plan's file-size limit.", "QUOTA_STORAGE_LIMIT", 403)
        if summary["storage_bytes"] + content_bytes > plan.storage_bytes: raise AppError("Your workspace storage limit has been reached.", "QUOTA_STORAGE_LIMIT", 403)
        if rows is not None and rows > plan.rows_per_dataset: raise AppError("This dataset exceeds your plan's row limit.", "QUOTA_STORAGE_LIMIT", 403)
    def enforce_analysis(self) -> None:
        _, plan = self.plan()
        if self.summary()["analyses_this_month"] >= plan.analyses_per_month: raise AppError("Your monthly analysis limit has been reached.", "QUOTA_ANALYSIS_LIMIT", 403)
    def enforce_storage_growth(self, estimated_bytes: int) -> None:
        _, plan = self.plan()
        if self.summary()["storage_bytes"] + max(estimated_bytes, 0) > plan.storage_bytes: raise AppError("Your workspace storage limit has been reached.", "QUOTA_STORAGE_LIMIT", 403)
    def enforce_report(self) -> None:
        _, plan = self.plan()
        if self.summary()["reports_this_month"] >= plan.reports_per_month: raise AppError("Your monthly report limit has been reached.", "QUOTA_REPORT_LIMIT", 403)
    def enforce_ai(self) -> None:
        _, plan = self.plan()
        if self.summary()["ai_requests_this_month"] >= plan.ai_requests_per_month: raise AppError("Your monthly AI request limit has been reached.", "QUOTA_AI_LIMIT", 403)
    def record(self, event_type: str, quantity: int, user_id: str | None, resource_id: str | None = None, details: dict | None = None) -> None:
        with session_scope() as session: UsageRepository(session, self.workspace_id).record(event_type, quantity, user_id, resource_id, details)
    def activity(self, activity_type: str, user_id: str | None, resource_id: str | None = None, details: dict | None = None) -> None:
        with session_scope() as session: ActivityRepository(session, self.workspace_id).record(activity_type, user_id, resource_id, details)
