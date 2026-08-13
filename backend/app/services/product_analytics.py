"""Privacy-safe product telemetry and derived beta activation metrics."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.models import ActivityLog, AnalysisFeedback, AnalysisRun, BetaUserNote, Dataset, Feedback, ProductEvent, User, WorkspaceMember

logger = logging.getLogger("datapilot.product")


class ProductEvents:
    REGISTERED = "account_registered"
    EMAIL_VERIFIED = "email_verified"
    LOGGED_IN = "user_logged_in"
    SAMPLE_LOADED = "sample_dataset_loaded"
    DATASET_UPLOADED = "dataset_uploaded"
    ANALYSIS_SUCCEEDED = "analysis_succeeded"
    ANALYSIS_FAILED = "analysis_failed"
    INSIGHTS_VIEWED = "insights_viewed"
    CHART_CREATED = "chart_created"
    REPORT_REQUESTED = "report_requested"
    REPORT_DOWNLOADED = "report_downloaded"
    EXPORT_DOWNLOADED = "export_downloaded"
    CLEANING_PREVIEWED = "cleaning_previewed"
    CLEANING_APPLIED = "cleaning_applied"
    DATASET_RESTORED = "dataset_restored"
    ANALYSIS_SAVED = "analysis_saved"
    INVITATION_SENT = "invitation_sent"
    INVITATION_ACCEPTED = "invitation_accepted"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    RESULT_RATED = "analysis_result_rated"
    ONBOARDING_DISMISSED = "onboarding_dismissed"


EVENT_FEATURE = {
    ProductEvents.DATASET_UPLOADED: "datasets", ProductEvents.SAMPLE_LOADED: "datasets",
    ProductEvents.ANALYSIS_SUCCEEDED: "analysis", ProductEvents.ANALYSIS_FAILED: "analysis",
    ProductEvents.INSIGHTS_VIEWED: "insights", ProductEvents.CHART_CREATED: "charts",
    ProductEvents.REPORT_REQUESTED: "reports", ProductEvents.REPORT_DOWNLOADED: "reports",
    ProductEvents.EXPORT_DOWNLOADED: "exports", ProductEvents.CLEANING_PREVIEWED: "cleaning",
    ProductEvents.CLEANING_APPLIED: "cleaning", ProductEvents.DATASET_RESTORED: "versions",
    ProductEvents.ANALYSIS_SAVED: "saved_analysis", ProductEvents.INVITATION_SENT: "collaboration",
    ProductEvents.INVITATION_ACCEPTED: "collaboration", ProductEvents.FEEDBACK_SUBMITTED: "feedback",
    ProductEvents.RESULT_RATED: "feedback",
}

# Explicitly excludes questions, filenames, dataset values, result rows, and arbitrary browser context.
SAFE_PROPERTIES = {
    "source_type", "rows_bucket", "operation", "engine", "fallback", "cached", "chart_type",
    "report_format", "export_format", "version", "failure_category", "helpful", "severity",
    "feature_area", "acquisition_source", "is_sample",
}


def _safe_properties(properties: dict[str, Any] | None) -> dict[str, Any] | None:
    if not properties: return None
    result: dict[str, Any] = {}
    for key, value in properties.items():
        if key not in SAFE_PROPERTIES or not isinstance(value, (str, int, float, bool)) or value is None: continue
        result[key] = value[:100] if isinstance(value, str) else value
    return result or None


def record_product_event(event_name: str, user_id: str | None = None, workspace_id: str | None = None, resource_type: str | None = None, resource_id: str | None = None, properties: dict[str, Any] | None = None) -> bool:
    """Best-effort recorder: product telemetry must never break a customer request."""
    try:
        with session_scope() as session:
            session.add(ProductEvent(user_id=user_id, workspace_id=workspace_id, event_name=event_name, feature_area=EVENT_FEATURE.get(event_name), resource_type=resource_type, resource_id=resource_id, properties=_safe_properties(properties)))
            session.commit()
        return True
    except Exception as exc:
        logger.warning("product_event_write_failed", extra={"event_name": event_name, "error_type": type(exc).__name__})
        return False


def analysis_failure_category(error_code: str) -> str:
    code = error_code.casefold()
    if "quota" in code or "rate" in code: return "quota_or_rate_limit"
    if "plan" in code or "column" in code or "query" in code or "semantic" in code: return "interpretation_or_validation"
    if "provider" in code or "ai_" in code: return "provider"
    if "dataset" in code or "storage" in code or "parquet" in code: return "dataset_or_storage"
    return "system"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _rate(value: int, total: int) -> float:
    return round(value / total * 100, 1) if total else 0.0


class ProductAnalyticsService:
    FUNNEL = (
        ("registered", ProductEvents.REGISTERED), ("verified", ProductEvents.EMAIL_VERIFIED),
        ("first_login", ProductEvents.LOGGED_IN), ("first_upload", ProductEvents.DATASET_UPLOADED),
        ("first_analysis", ProductEvents.ANALYSIS_SUCCEEDED), ("chart_or_insight", ProductEvents.CHART_CREATED),
        ("report_or_export", ProductEvents.REPORT_DOWNLOADED), ("returned", "returned"),
    )

    def __init__(self, session: Session) -> None: self.session = session

    def _profiles(self, days: int | None) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        query = select(User).order_by(User.created_at.desc())
        if cutoff: query = query.where(User.created_at >= cutoff)
        users = list(self.session.scalars(query).all())
        if not users: return []
        ids = [user.id for user in users]
        events = list(self.session.scalars(select(ProductEvent).where(ProductEvent.user_id.in_(ids)).order_by(ProductEvent.occurred_at)).all())
        activities = list(self.session.scalars(select(ActivityLog).where(ActivityLog.user_id.in_(ids)).order_by(ActivityLog.created_at)).all())
        datasets = list(self.session.scalars(select(Dataset).where(Dataset.uploader_user_id.in_(ids)).order_by(Dataset.created_at)).all())
        runs = list(self.session.scalars(select(AnalysisRun).where(AnalysisRun.user_id.in_(ids)).order_by(AnalysisRun.created_at)).all())
        by_event: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
        active_dates: dict[str, set] = defaultdict(set)
        for item in events:
            by_event[item.user_id][item.event_name].append(item.occurred_at); active_dates[item.user_id].add(item.occurred_at.date())
        for item in activities: active_dates[item.user_id].add(item.created_at.date())
        by_dataset: dict[str, list[Dataset]] = defaultdict(list)
        for item in datasets: by_dataset[item.uploader_user_id].append(item)
        by_run: dict[str, list[AnalysisRun]] = defaultdict(list)
        for item in runs: by_run[item.user_id].append(item)
        profiles = []
        for user in users:
            event_map = by_event[user.id]
            registered = _aware(user.created_at); verified = _aware(user.email_verified_at)
            first_upload = _aware(event_map[ProductEvents.DATASET_UPLOADED][0]) if event_map[ProductEvents.DATASET_UPLOADED] else (_aware(by_dataset[user.id][0].created_at) if by_dataset[user.id] else None)
            successful = [item for item in by_run[user.id] if item.success]
            first_analysis = _aware(event_map[ProductEvents.ANALYSIS_SUCCEEDED][0]) if event_map[ProductEvents.ANALYSIS_SUCCEEDED] else (_aware(successful[0].created_at) if successful else None)
            first_login = _aware(event_map[ProductEvents.LOGGED_IN][0]) if event_map[ProductEvents.LOGGED_IN] else _aware(user.last_login_at)
            chart = min((_aware(value) for value in event_map[ProductEvents.CHART_CREATED] + event_map[ProductEvents.INSIGHTS_VIEWED]), default=None)
            report = min((_aware(value) for value in event_map[ProductEvents.REPORT_DOWNLOADED] + event_map[ProductEvents.EXPORT_DOWNLOADED] + event_map[ProductEvents.REPORT_REQUESTED]), default=None)
            activity_days = sorted(active_dates[user.id] | ({registered.date()} if registered else set()))
            returned = next((day for day in activity_days if registered and day > registered.date()), None)
            activated_at = max(filter(None, [verified, first_upload, first_analysis]), default=None) if verified and first_upload and first_analysis else None
            candidates = [_aware(user.last_login_at), *[_aware(item.occurred_at) for item in events if item.user_id == user.id], *[_aware(item.created_at) for item in activities if item.user_id == user.id]]
            last_active = max(filter(None, candidates), default=registered)
            profiles.append({"id": user.id, "email": user.email, "display_name": user.display_name, "registered": registered, "verified": verified, "first_login": first_login, "first_upload": first_upload, "first_analysis": first_analysis, "chart_or_insight": chart, "report_or_export": report, "returned": returned, "activated_at": activated_at, "activated_24h": bool(activated_at and registered and activated_at <= registered + timedelta(hours=24)), "last_active": last_active, "beta_status": user.beta_status, "acquisition_source": user.acquisition_source})
        return profiles

    def dashboard(self, days: int | None = 30) -> dict[str, Any]:
        profiles = self._profiles(days); total = len(profiles)
        funnel = []
        previous = total
        for key, _ in self.FUNNEL:
            count = sum(bool(item[key]) for item in profiles)
            funnel.append({"step": key, "users": count, "conversion": _rate(count, total), "step_conversion": _rate(count, previous)})
            previous = count
        activated = sum(bool(item["activated_at"]) for item in profiles)
        activated_24h = sum(item["activated_24h"] for item in profiles)
        event_query = select(ProductEvent)
        if days: event_query = event_query.where(ProductEvent.occurred_at >= datetime.now(timezone.utc) - timedelta(days=days))
        events = list(self.session.scalars(event_query).all())
        feature_users: dict[str, set[str]] = defaultdict(set)
        for event in events:
            if event.feature_area and event.user_id: feature_users[event.feature_area].add(event.user_id)
        failures = Counter(str((event.properties or {}).get("failure_category", "unknown")) for event in events if event.event_name == ProductEvents.ANALYSIS_FAILED)
        feedback = list(self.session.scalars(select(AnalysisFeedback)).all())
        helpful = sum(item.helpful for item in feedback)
        now = datetime.now(timezone.utc).date()
        d1_eligible = [item for item in profiles if (now - item["registered"].date()).days >= 1]
        d7_eligible = [item for item in profiles if (now - item["registered"].date()).days >= 7]
        d1 = sum(bool(item["returned"] and (item["returned"] - item["registered"].date()).days <= 1) for item in d1_eligible)
        d7 = sum(bool(item["returned"] and (item["returned"] - item["registered"].date()).days <= 7) for item in d7_eligible)
        user_rows = []
        for item in profiles:
            if not item["verified"]: follow_up = "Verify email"
            elif not item["first_upload"]: follow_up = "Offer sample dataset"
            elif not item["first_analysis"]: follow_up = "Suggest a starter question"
            elif not item["returned"]: follow_up = "Check in after first value"
            else: follow_up = "No follow-up needed"
            user_rows.append({**{key: (_iso(value) if isinstance(value, datetime) else value.isoformat() if hasattr(value, "isoformat") else value) for key, value in item.items()}, "recommended_follow_up": follow_up})
        return {
            "range_days": days, "summary": {"signups": total, "verified": sum(bool(item["verified"]) for item in profiles), "activated": activated, "activation_rate": _rate(activated, total), "activated_within_24h": activated_24h, "returning_users": sum(bool(item["returned"]) for item in profiles)},
            "funnel": funnel, "retention": {"d1": _rate(d1, len(d1_eligible)), "d7": _rate(d7, len(d7_eligible)), "d1_eligible": len(d1_eligible), "d7_eligible": len(d7_eligible)},
            "feature_adoption": [{"feature": key, "users": len(value), "adoption": _rate(len(value), total)} for key, value in sorted(feature_users.items())],
            "analysis": {"successful": sum(item.event_name == ProductEvents.ANALYSIS_SUCCEEDED for item in events), "failed": sum(item.event_name == ProductEvents.ANALYSIS_FAILED for item in events), "fallback_used": sum(item.event_name == ProductEvents.ANALYSIS_SUCCEEDED and bool((item.properties or {}).get("fallback")) for item in events), "cached": sum(item.event_name == ProductEvents.ANALYSIS_SUCCEEDED and bool((item.properties or {}).get("cached")) for item in events), "failure_categories": [{"category": key, "count": value} for key, value in failures.most_common()], "ratings": len(feedback), "helpful_rate": _rate(helpful, len(feedback))},
            "users": user_rows,
        }


def onboarding_state(session: Session, user: User, workspace_id: str) -> dict[str, Any]:
    uploads = int(session.scalar(select(func.count()).select_from(Dataset).where(Dataset.workspace_id == workspace_id)) or 0)
    analyses = int(session.scalar(select(func.count()).select_from(AnalysisRun).where(AnalysisRun.workspace_id == workspace_id, AnalysisRun.user_id == user.id, AnalysisRun.success.is_(True))) or 0)
    event_names = set(session.scalars(select(ProductEvent.event_name).where(ProductEvent.user_id == user.id, ProductEvent.workspace_id == workspace_id)).all())
    steps = [
        {"key": "verify", "label": "Verify your email", "complete": user.email_verified_at is not None},
        {"key": "upload", "label": "Upload or try sample data", "complete": uploads > 0},
        {"key": "analyze", "label": "Run your first analysis", "complete": analyses > 0},
        {"key": "visualize", "label": "View insights or create a chart", "complete": bool(event_names & {ProductEvents.INSIGHTS_VIEWED, ProductEvents.CHART_CREATED})},
        {"key": "share", "label": "Generate a report or export", "complete": bool(event_names & {ProductEvents.REPORT_REQUESTED, ProductEvents.REPORT_DOWNLOADED, ProductEvents.EXPORT_DOWNLOADED})},
    ]
    return {"steps": steps, "completed": sum(item["complete"] for item in steps), "total": len(steps), "dismissed": user.onboarding_dismissed_at is not None, "complete": all(item["complete"] for item in steps), "welcome": "Welcome to DataPilot. Start with your own file or a safe sample, then ask a plain-language question."}
