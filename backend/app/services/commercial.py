from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import Subscription, Workspace, WorkspaceMember
from app.repositories import ActivityRepository, UsageRepository


@dataclass(frozen=True, init=False)
class PlanDefinition:
    code: str
    name: str
    description: str
    limits: dict[str, int]
    features: frozenset[str]
    trial_eligible: bool
    upgrade_order: int
    active: bool = True

    def __init__(self, *args, **kwargs) -> None:
        # Preserve the Milestone 5 test/extension constructor while exposing the richer catalog shape.
        if len(args) == 7 and isinstance(args[0], int) and not kwargs:
            datasets, storage, upload, rows, analyses, reports, ai = args
            values = {"code": "custom", "name": "Custom", "description": "Compatibility plan", "limits": {"datasets": datasets, "workspace_members": 3, "storage_bytes": storage, "upload_bytes": upload, "rows_per_dataset": rows, "max_columns": 500, "analyses_per_month": analyses, "reports_per_month": reports, "external_ai_calls_per_month": ai, "exports_per_month": 20}, "features": frozenset({"external_ai", "pdf_reports", "saved_analyses", "workspace_export", "advanced_cleaning", "workspace_collaboration"}), "trial_eligible": False, "upgrade_order": 0, "active": True}
        else:
            names = ("code", "name", "description", "limits", "features", "trial_eligible", "upgrade_order", "active")
            values = {name: value for name, value in zip(names, args)}; values.update(kwargs); values.setdefault("active", True)
        for name in ("code", "name", "description", "limits", "features", "trial_eligible", "upgrade_order", "active"): object.__setattr__(self, name, values[name])

    @property
    def datasets(self) -> int: return self.limits["datasets"]
    @property
    def storage_bytes(self) -> int: return self.limits["storage_bytes"]
    @property
    def upload_bytes(self) -> int: return self.limits["upload_bytes"]
    @property
    def rows_per_dataset(self) -> int: return self.limits["rows_per_dataset"]
    @property
    def max_columns(self) -> int: return self.limits["max_columns"]
    @property
    def analyses_per_month(self) -> int: return self.limits["analyses_per_month"]
    @property
    def reports_per_month(self) -> int: return self.limits["reports_per_month"]
    @property
    def ai_requests_per_month(self) -> int: return self.limits["external_ai_calls_per_month"]


DEFAULT_PLANS: dict[str, PlanDefinition] = {
    "free": PlanDefinition("free", "Free", "For individual evaluation and deterministic analysis.", {
        "datasets": 5, "workspace_members": 3, "upload_bytes": 25 * 1024 * 1024, "rows_per_dataset": 100_000,
        "max_columns": 500, "storage_bytes": 100 * 1024 * 1024, "analyses_per_month": 50,
        "external_ai_calls_per_month": 0, "reports_per_month": 5, "exports_per_month": 20,
    }, frozenset({"pdf_reports", "saved_analyses", "workspace_export", "advanced_cleaning", "workspace_collaboration"}), True, 0),
    "pro": PlanDefinition("pro", "Pro", "For professionals who need larger datasets and external AI.", {
        "datasets": 50, "workspace_members": 10, "upload_bytes": 100 * 1024 * 1024, "rows_per_dataset": 1_000_000,
        "max_columns": 500, "storage_bytes": 5 * 1024 * 1024 * 1024, "analyses_per_month": 2_000,
        "external_ai_calls_per_month": 2_000, "reports_per_month": 200, "exports_per_month": 500,
    }, frozenset({"external_ai", "pdf_reports", "saved_analyses", "workspace_export", "advanced_cleaning", "workspace_collaboration"}), True, 1),
    "business": PlanDefinition("business", "Business", "For teams that need collaboration, scale, and priority processing.", {
        "datasets": 500, "workspace_members": 50, "upload_bytes": 500 * 1024 * 1024, "rows_per_dataset": 5_000_000,
        "max_columns": 500, "storage_bytes": 100 * 1024 * 1024 * 1024, "analyses_per_month": 20_000,
        "external_ai_calls_per_month": 20_000, "reports_per_month": 2_000, "exports_per_month": 5_000,
    }, frozenset({"external_ai", "pdf_reports", "saved_analyses", "workspace_export", "advanced_cleaning", "workspace_collaboration", "priority_jobs"}), False, 2),
}


def _configured_catalog() -> dict[str, PlanDefinition]:
    catalog = dict(DEFAULT_PLANS); raw = get_settings().plan_catalog_json
    if not raw: return catalog
    try: overrides = json.loads(raw)
    except (TypeError, ValueError): return catalog
    if not isinstance(overrides, dict): return catalog
    for code, values in overrides.items():
        if code not in catalog or not isinstance(values, dict): continue
        current = catalog[code]; limits = dict(current.limits)
        if isinstance(values.get("limits"), dict): limits.update({key: int(value) for key, value in values["limits"].items() if key in limits and isinstance(value, (int, float)) and value >= 0})
        features = frozenset(values.get("features", current.features)) if isinstance(values.get("features", list(current.features)), (list, tuple, set, frozenset)) else current.features
        catalog[code] = replace(current, name=str(values.get("name", current.name))[:80], description=str(values.get("description", current.description))[:300], limits=limits, features=features, trial_eligible=bool(values.get("trial_eligible", current.trial_eligible)), upgrade_order=int(values.get("upgrade_order", current.upgrade_order)), active=bool(values.get("active", current.active)))
    return catalog


def plan_catalog() -> dict[str, PlanDefinition]: return _configured_catalog()


def billing_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    start = datetime(current.year, current.month, 1, tzinfo=timezone.utc)
    end = datetime(current.year + (1 if current.month == 12 else 0), 1 if current.month == 12 else current.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _aware(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def price_for(code: str) -> float | None:
    settings = get_settings()
    return {"free": settings.free_price_monthly, "pro": settings.pro_price_monthly, "business": settings.business_price_monthly}.get(code)


def public_plan(plan: PlanDefinition) -> dict[str, Any]:
    price = price_for(plan.code); settings = get_settings()
    return {"code": plan.code, "name": plan.name, "description": plan.description, "limits": dict(plan.limits), "features": sorted(plan.features), "trial_available": settings.pro_trial_enabled and plan.code == "pro" and plan.trial_eligible, "upgrade_order": plan.upgrade_order, "active": plan.active, "price": {"monthly": price, "currency": settings.pricing_currency, "configured": price is not None}}


class EntitlementService:
    def __init__(self, workspace_id: str, now: datetime | None = None) -> None:
        self.workspace_id = workspace_id; self.now = now or datetime.now(timezone.utc)

    def resolution(self) -> dict[str, Any]:
        catalog = plan_catalog()
        trial_expired_now = False
        with session_scope() as session:
            workspace = session.get(Workspace, self.workspace_id)
            if workspace is None: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
            subscription = session.scalar(select(Subscription).where(Subscription.workspace_id == self.workspace_id))
            if subscription and subscription.status == "active" and subscription.current_period_end is not None and _aware(subscription.current_period_end) <= self.now:
                subscription.status = "expired"; session.commit()
            if subscription and subscription.status == "active" and (subscription.current_period_end is None or _aware(subscription.current_period_end) > self.now):
                code, source = subscription.plan_code, "subscription"
            elif workspace.trial_status == "active" and workspace.trial_plan and _aware(workspace.trial_ends_at) and _aware(workspace.trial_ends_at) > self.now:
                code, source = workspace.trial_plan, "trial"
            else: code, source = workspace.plan_code, "base"
            if code not in catalog or not catalog[code].active: code = "free"
            if workspace.trial_started_at and workspace.trial_status == "active" and (_aware(workspace.trial_ends_at) or self.now) <= self.now:
                workspace.trial_status = "expired"; session.commit(); trial_expired_now = True
            result = {"workspace": workspace, "subscription": subscription, "plan_code": code, "plan": catalog[code], "source": source, "trial_status": workspace.trial_status}
        if trial_expired_now:
            from app.services.product_analytics import ProductEvents, record_product_event
            record_product_event(ProductEvents.TRIAL_EXPIRED, workspace.owner_user_id, workspace.id, "workspace", workspace.id, {"plan_code": workspace.trial_plan or "pro"})
        return result

    def plan(self) -> tuple[str, PlanDefinition]:
        found = self.resolution(); return found["plan_code"], found["plan"]

    def has(self, feature: str) -> bool: return feature in self.plan()[1].features

    def enforce_feature(self, feature: str, message: str | None = None) -> None:
        if self.has(feature): return
        code, _ = self.plan()
        raise AppError(message or f"{feature.replace('_', ' ').title()} is not included in the {code.title()} plan.", "PLAN_FEATURE_UNAVAILABLE", 403, {"resource": feature, "effective_plan": code, "upgrade_recommended": True})

    def _limit_error(self, resource: str, used: int, limit: int, message: str) -> None:
        code, _ = self.plan()
        legacy = "QUOTA_DATASET_LIMIT" if resource == "datasets" else "QUOTA_ANALYSIS_LIMIT" if resource == "analyses_per_month" else "QUOTA_REPORT_LIMIT" if resource == "reports_per_month" else "QUOTA_AI_LIMIT" if resource == "external_ai_calls_per_month" else "QUOTA_STORAGE_LIMIT" if resource in {"storage_bytes", "upload_bytes", "rows_per_dataset", "max_columns"} else "PLAN_LIMIT_REACHED"
        raise AppError(message, legacy, 403, {"code": "PLAN_LIMIT_REACHED", "resource": resource, "used": used, "limit": limit, "effective_plan": code, "upgrade_recommended": True})

    def _counts(self) -> dict[str, int]:
        start, _ = billing_period(self.now)
        with session_scope() as session:
            usage = UsageRepository(session, self.workspace_id)
            return {"datasets": usage.dataset_count(), "storage_bytes": usage.storage_bytes(), "workspace_members": int(session.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == self.workspace_id)) or 0), "analyses_per_month": usage.total("analysis", start), "external_ai_calls_per_month": usage.total("external_ai_call", start), "reports_per_month": usage.total("report", start), "exports_per_month": usage.total("export", start), "rows_uploaded_per_month": usage.total("rows_uploaded", start)}

    def summary(self) -> dict[str, Any]:
        resolution = self.resolution(); plan: PlanDefinition = resolution["plan"]; counts = self._counts(); settings = get_settings(); start, end = billing_period(self.now)
        resources: dict[str, dict[str, Any]] = {}
        for key in ("datasets", "storage_bytes", "workspace_members", "analyses_per_month", "external_ai_calls_per_month", "reports_per_month", "exports_per_month"):
            used, limit = counts[key], plan.limits[key]; percent = round(used / limit * 100, 1) if limit else (100.0 if used else 0.0)
            level = "limit" if percent >= 100 else "critical" if percent >= settings.plan_limit_critical_percent else "warning" if percent >= settings.plan_limit_warning_percent else "normal"
            resources[key] = {"used": used, "limit": limit, "percent": percent, "level": level}
        workspace: Workspace = resolution["workspace"]
        return {"plan_code": resolution["plan_code"], "base_plan_code": workspace.plan_code, "plan_source": resolution["source"], "period": {"type": "calendar_month", "start": start, "end": end}, "usage": resources, "limits": dict(plan.limits), "features": sorted(plan.features), "datasets": counts["datasets"], "storage_bytes": counts["storage_bytes"], "analyses_this_month": counts["analyses_per_month"], "ai_requests_this_month": counts["external_ai_calls_per_month"], "reports_this_month": counts["reports_per_month"], "exports_this_month": counts["exports_per_month"], "members": counts["workspace_members"], "rows_this_month": counts["rows_uploaded_per_month"], "percentages": {"datasets": resources["datasets"]["percent"], "storage": resources["storage_bytes"]["percent"], "analyses": resources["analyses_per_month"]["percent"], "reports": resources["reports_per_month"]["percent"]}, "over_limit": any(item["level"] == "limit" for item in resources.values())}

    def enforce_upload(self, content_bytes: int, rows: int | None = None, columns: int | None = None) -> None:
        _, plan = self.plan(); counts = self._counts()
        if counts["datasets"] >= plan.limits["datasets"]: self._limit_error("datasets", counts["datasets"], plan.limits["datasets"], "Your plan's dataset limit has been reached.")
        if content_bytes > plan.limits["upload_bytes"]: self._limit_error("upload_bytes", content_bytes, plan.limits["upload_bytes"], "This upload exceeds your plan's file-size limit.")
        if counts["storage_bytes"] + content_bytes > plan.limits["storage_bytes"]: self._limit_error("storage_bytes", counts["storage_bytes"], plan.limits["storage_bytes"], "Your workspace storage limit has been reached.")
        if rows is not None and rows > plan.limits["rows_per_dataset"]: self._limit_error("rows_per_dataset", rows, plan.limits["rows_per_dataset"], "This dataset exceeds your plan's row limit.")
        if columns is not None and columns > plan.limits["max_columns"]: self._limit_error("max_columns", columns, plan.limits["max_columns"], "This dataset exceeds your plan's column limit.")

    def enforce_monthly(self, resource: str, event_type: str) -> None:
        _, plan = self.plan(); start, _ = billing_period(self.now)
        with session_scope() as session: used = UsageRepository(session, self.workspace_id).total(event_type, start)
        limit = plan.limits[resource]
        if used >= limit: self._limit_error(resource, used, limit, f"Your monthly {resource.replace('_per_month', '').replace('_', ' ')} limit has been reached.")

    def enforce_analysis(self) -> None: self.enforce_monthly("analyses_per_month", "analysis")
    def enforce_report(self) -> None: self.enforce_monthly("reports_per_month", "report")
    def enforce_export(self) -> None: self.enforce_monthly("exports_per_month", "export")
    def enforce_ai(self) -> None: self.enforce_monthly("external_ai_calls_per_month", "external_ai_call")
    def enforce_member(self) -> None:
        _, plan = self.plan(); used = self._counts()["workspace_members"]; limit = plan.limits["workspace_members"]
        if used >= limit: self._limit_error("workspace_members", used, limit, "Your plan's workspace member limit has been reached.")
    def enforce_storage_growth(self, estimated_bytes: int) -> None:
        _, plan = self.plan(); used = self._counts()["storage_bytes"]
        if used + max(estimated_bytes, 0) > plan.limits["storage_bytes"]: self._limit_error("storage_bytes", used, plan.limits["storage_bytes"], "Your workspace storage limit has been reached.")

    def record(self, event_type: str, quantity: int, user_id: str | None, resource_id: str | None = None, details: dict | None = None, meter_key: str | None = None) -> bool:
        with session_scope() as session: return UsageRepository(session, self.workspace_id).record(event_type, quantity, user_id, resource_id, details, meter_key)
    def activity(self, activity_type: str, user_id: str | None, resource_id: str | None = None, details: dict | None = None) -> None:
        with session_scope() as session: ActivityRepository(session, self.workspace_id).record(activity_type, user_id, resource_id, details)


def public_catalog() -> list[dict[str, Any]]: return [public_plan(plan) for plan in sorted(plan_catalog().values(), key=lambda item: item.upgrade_order) if plan.active]
