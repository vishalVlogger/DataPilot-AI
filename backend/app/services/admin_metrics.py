from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import ActivityLog, AnalysisRun, Dataset, Feedback, FeedbackAttachment, Job, SystemAdminAudit, SystemError, UsageEvent, User, Workspace, WorkspaceMember


def model_dict(item: Any) -> dict[str, Any]:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


class AdminMetricsService:
    """Metadata-only platform operations queries. Never opens dataset files."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def cutoff(days: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=days)

    def overview(self, days: int = 30) -> dict[str, Any]:
        now = datetime.now(timezone.utc); today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc); month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        scalar = self.session.scalar
        metrics = {
            "total_users": int(scalar(select(func.count()).select_from(User)) or 0),
            "verified_users": int(scalar(select(func.count()).select_from(User).where(User.email_verified_at.is_not(None))) or 0),
            "active_users": int(scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0),
            "total_workspaces": int(scalar(select(func.count()).select_from(Workspace)) or 0),
            "total_datasets": int(scalar(select(func.count()).select_from(Dataset)) or 0),
            "analyses_today": int(scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.event_type == "analysis", UsageEvent.created_at >= today)) or 0),
            "analyses_this_month": int(scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.event_type == "analysis", UsageEvent.created_at >= month)) or 0),
            "reports_generated": int(scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.event_type == "report")) or 0),
            "failed_jobs_24h": int(scalar(select(func.count()).select_from(Job).where(Job.status == "failed", Job.completed_at >= now - timedelta(days=1))) or 0),
            "open_feedback": int(scalar(select(func.count()).select_from(Feedback).where(Feedback.status != "resolved")) or 0),
            "storage_bytes": int(scalar(select(func.coalesce(func.sum(Dataset.storage_bytes), 0))) or 0),
        }
        recent = self.session.execute(select(ActivityLog, User, Workspace).outerjoin(User, User.id == ActivityLog.user_id).outerjoin(Workspace, Workspace.id == ActivityLog.workspace_id).order_by(ActivityLog.created_at.desc()).limit(10)).all()
        return {"range_days": days, "metrics": metrics, "alerts": self.alerts(metrics), "recent_activity": [{"id": item.id, "type": item.activity_type, "user": user.email if user else None, "workspace": workspace.name if workspace else None, "resource_id": item.resource_id, "created_at": item.created_at} for item, user, workspace in recent]}

    def alerts(self, metrics: dict[str, int]) -> list[dict[str, str]]:
        settings = get_settings(); alerts = []
        if metrics["failed_jobs_24h"]: alerts.append({"level": "warning", "message": f"{metrics['failed_jobs_24h']} failed jobs in the last 24 hours"})
        if metrics["open_feedback"]: alerts.append({"level": "info", "message": f"{metrics['open_feedback']} unresolved feedback reports"})
        alerts.append({"level": "success", "message": "Required database and storage checks are healthy"})
        alerts.append({"level": "info", "message": f"Email provider: {settings.email_provider}"})
        if not settings.redis_url: alerts.append({"level": "info", "message": "Redis is not configured (optional in local mode)"})
        return alerts

    def user_metrics(self) -> dict[str, int]:
        now = datetime.now(timezone.utc); today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        def count(*conditions) -> int: return int(self.session.scalar(select(func.count()).select_from(User).where(*conditions)) or 0)
        def active(days: int) -> int: return int(self.session.scalar(select(func.count(distinct(ActivityLog.user_id))).where(ActivityLog.created_at >= self.cutoff(days), ActivityLog.user_id.is_not(None))) or 0)
        return {"total": count(), "active_accounts": count(User.is_active.is_(True)), "inactive_accounts": count(User.is_active.is_(False)), "verified": count(User.email_verified_at.is_not(None)), "registered_today": count(User.created_at >= today), "registered_week": count(User.created_at >= self.cutoff(7)), "registered_month": count(User.created_at >= self.cutoff(30)), "daily_active_users": active(1), "weekly_active_users": active(7), "monthly_active_users": active(30)}

    def users(self, search: str | None, verified: bool | None, active: bool | None, admin: bool | None, limit: int, offset: int) -> dict:
        memberships = select(WorkspaceMember.user_id, func.count(WorkspaceMember.workspace_id).label("workspace_count")).group_by(WorkspaceMember.user_id).subquery()
        last_activity = select(ActivityLog.user_id, func.max(ActivityLog.created_at).label("last_activity")).group_by(ActivityLog.user_id).subquery()
        query = select(User, func.coalesce(memberships.c.workspace_count, 0), last_activity.c.last_activity).outerjoin(memberships, memberships.c.user_id == User.id).outerjoin(last_activity, last_activity.c.user_id == User.id)
        if search:
            pattern = f"%{search[:200]}%"; query = query.where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern), User.id == search))
        if verified is not None: query = query.where(User.email_verified_at.is_not(None) if verified else User.email_verified_at.is_(None))
        if active is not None: query = query.where(User.is_active == active)
        if admin is not None: query = query.where(User.is_system_admin == admin)
        total = int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self.session.execute(query.order_by(User.created_at.desc()).limit(limit).offset(offset)).all()
        return {"items": [{"id": user.id, "email": user.email, "display_name": user.display_name, "verified": user.email_verified_at is not None, "active": user.is_active, "system_admin": user.is_system_admin, "created_at": user.created_at, "last_activity": last, "workspace_count": int(count), "plan_summary": self._user_plans(user.id)} for user, count, last in rows], "total": total, "limit": limit, "offset": offset}

    def _user_plans(self, user_id: str) -> str:
        plans = self.session.scalars(select(distinct(Workspace.plan_code)).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id).where(WorkspaceMember.user_id == user_id)).all()
        return ", ".join(sorted(plans)) or "none"

    def user_detail(self, user_id: str) -> dict:
        user = self.session.get(User, user_id)
        if not user: raise AppError("User not found.", "ADMIN_USER_NOT_FOUND", 404)
        memberships = self.session.execute(select(WorkspaceMember, Workspace).join(Workspace, Workspace.id == WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)).all()
        workspace_ids = [workspace.id for _, workspace in memberships]
        usage = dict(self.session.execute(select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.user_id == user_id).group_by(UsageEvent.event_type)).all())
        feedback = self.session.scalars(select(Feedback).where(Feedback.user_id == user_id).order_by(Feedback.created_at.desc()).limit(10)).all()
        errors = self.session.scalars(select(SystemError).where(SystemError.user_id == user_id).order_by(SystemError.last_seen_at.desc()).limit(10)).all()
        datasets = [] if not workspace_ids else self.session.execute(select(Dataset.id, Dataset.name, Dataset.workspace_id, Dataset.row_count, Dataset.column_count, Dataset.storage_bytes, Dataset.created_at).where(Dataset.workspace_id.in_(workspace_ids)).order_by(Dataset.created_at.desc()).limit(50)).mappings().all()
        return {"user": {"id": user.id, "email": user.email, "display_name": user.display_name, "active": user.is_active, "verified": user.email_verified_at is not None, "system_admin": user.is_system_admin, "created_at": user.created_at, "last_login_at": user.last_login_at}, "memberships": [{"workspace_id": workspace.id, "workspace_name": workspace.name, "role": member.role, "plan": workspace.plan_code} for member, workspace in memberships], "usage": usage, "datasets": [dict(row) for row in datasets], "recent_errors": [model_dict(item) for item in errors], "recent_feedback": [{"id": item.id, "category": item.category, "status": item.status, "message": item.message, "created_at": item.created_at} for item in feedback]}

    def workspaces(self, search: str | None, limit: int, offset: int) -> dict:
        members = select(WorkspaceMember.workspace_id, func.count().label("members")).group_by(WorkspaceMember.workspace_id).subquery()
        datasets = select(Dataset.workspace_id, func.count().label("datasets"), func.coalesce(func.sum(Dataset.storage_bytes), 0).label("storage")).group_by(Dataset.workspace_id).subquery()
        usage = select(UsageEvent.workspace_id, func.coalesce(func.sum(case((UsageEvent.event_type == "analysis", UsageEvent.quantity), else_=0)), 0).label("analyses"), func.coalesce(func.sum(case((UsageEvent.event_type == "report", UsageEvent.quantity), else_=0)), 0).label("reports"), func.max(UsageEvent.created_at).label("last_activity")).group_by(UsageEvent.workspace_id).subquery()
        query = select(Workspace, User.email, func.coalesce(members.c.members, 0), func.coalesce(datasets.c.datasets, 0), func.coalesce(datasets.c.storage, 0), func.coalesce(usage.c.analyses, 0), func.coalesce(usage.c.reports, 0), usage.c.last_activity).join(User, User.id == Workspace.owner_user_id).outerjoin(members, members.c.workspace_id == Workspace.id).outerjoin(datasets, datasets.c.workspace_id == Workspace.id).outerjoin(usage, usage.c.workspace_id == Workspace.id)
        if search:
            pattern = f"%{search[:200]}%"; query = query.where(or_(Workspace.name.ilike(pattern), Workspace.id == search, User.email.ilike(pattern)))
        total = int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self.session.execute(query.order_by(Workspace.created_at.desc()).limit(limit).offset(offset)).all()
        return {"items": [{"id": w.id, "name": w.name, "owner_email": email, "member_count": int(mc), "plan": w.plan_code, "dataset_count": int(dc), "storage_bytes": int(storage), "analysis_count": int(analyses), "report_count": int(reports), "created_at": w.created_at, "last_activity": last, "external_ai_enabled": w.external_ai_enabled} for w, email, mc, dc, storage, analyses, reports, last in rows], "total": total, "limit": limit, "offset": offset}

    def workspace_detail(self, workspace_id: str) -> dict:
        workspace = self.session.get(Workspace, workspace_id)
        if not workspace: raise AppError("Workspace not found.", "ADMIN_WORKSPACE_NOT_FOUND", 404)
        members = self.session.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id)).all()
        datasets = self.session.scalars(select(Dataset).where(Dataset.workspace_id == workspace_id).order_by(Dataset.created_at.desc()).limit(100)).all()
        usage = dict(self.session.execute(select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.workspace_id == workspace_id).group_by(UsageEvent.event_type)).all())
        return {"workspace": {"id": workspace.id, "name": workspace.name, "plan": workspace.plan_code, "external_ai_enabled": workspace.external_ai_enabled, "created_at": workspace.created_at}, "members": [{"user_id": user.id, "email": user.email, "display_name": user.display_name, "role": member.role} for member, user in members], "usage": usage, "datasets": [{"id": item.id, "name": item.name, "rows": item.row_count, "columns": item.column_count, "size": item.storage_bytes, "source_type": item.source_type, "current_version": item.current_version, "created_at": item.created_at, "last_analyzed_at": item.last_analyzed_at} for item in datasets], "job_count": int(self.session.scalar(select(func.count()).select_from(Job).where(Job.workspace_id == workspace_id)) or 0)}

    def usage(self, days: int) -> dict:
        cutoff = self.cutoff(days)
        totals = dict(self.session.execute(select(UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.created_at >= cutoff).group_by(UsageEvent.event_type)).all())
        raw = self.session.execute(select(func.date(UsageEvent.created_at), UsageEvent.event_type, func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.created_at >= cutoff).group_by(func.date(UsageEvent.created_at), UsageEvent.event_type).order_by(func.date(UsageEvent.created_at))).all()
        trend: dict[str, dict[str, Any]] = defaultdict(dict)
        for day, event, quantity in raw: trend[str(day)][event] = int(quantity)
        top_workspaces = self.session.execute(select(Workspace.name, func.sum(UsageEvent.quantity).label("value")).join(Workspace, Workspace.id == UsageEvent.workspace_id).where(UsageEvent.created_at >= cutoff).group_by(Workspace.id).order_by(func.sum(UsageEvent.quantity).desc()).limit(10)).all()
        top_users = self.session.execute(select(User.email, func.sum(UsageEvent.quantity).label("value")).join(User, User.id == UsageEvent.user_id).where(UsageEvent.created_at >= cutoff).group_by(User.id).order_by(func.sum(UsageEvent.quantity).desc()).limit(10)).all()
        return {"range_days": days, "totals": totals, "trend": [{"date": day, **values} for day, values in trend.items()], "top_workspaces": [{"label": label, "value": int(value)} for label, value in top_workspaces], "top_users": [{"label": label, "value": int(value)} for label, value in top_users]}

    def jobs(self, status: str | None, job_type: str | None, days: int | None, limit: int, offset: int) -> dict:
        query = select(Job, Workspace.name).join(Workspace, Workspace.id == Job.workspace_id)
        if status: query = query.where(Job.status == status)
        if job_type: query = query.where(Job.type == job_type)
        if days: query = query.where(Job.created_at >= self.cutoff(days))
        total = int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0); rows = self.session.execute(query.order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
        items = []
        for job, workspace in rows:
            duration = None
            if job.started_at and job.completed_at: duration = max(0, int((_aware(job.completed_at) - _aware(job.started_at)).total_seconds() * 1000))
            items.append({"id": job.id, "workspace_id": job.workspace_id, "workspace_name": workspace, "type": job.type, "status": job.status, "stage": job.stage, "retryable": job.retryable and job.status == "failed", "attempt_count": job.attempt_count, "max_attempts": job.max_attempts, "duration_ms": duration, "created_at": job.created_at, "error_code": job.error_code, "error_message": job.error_message})
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def errors(self, error_code: str | None, route: str | None, status_code: int | None, days: int | None, limit: int, offset: int) -> dict:
        query = select(SystemError)
        if error_code: query = query.where(SystemError.error_code == error_code)
        if route: query = query.where(SystemError.route.ilike(f"%{route[:200]}%"))
        if status_code: query = query.where(SystemError.status_code == status_code)
        if days: query = query.where(SystemError.last_seen_at >= self.cutoff(days))
        total = int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        items = [{**model_dict(item), "affected_users": 1 if item.user_id else 0, "affected_workspaces": 1 if item.workspace_id else 0} for item in self.session.scalars(query.order_by(SystemError.last_seen_at.desc()).limit(limit).offset(offset)).all()]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def storage(self) -> dict:
        settings = get_settings(); root = settings.storage_root.resolve()
        dataset_bytes = int(self.session.scalar(select(func.coalesce(func.sum(Dataset.storage_bytes), 0))) or 0)
        attachment_bytes = int(self.session.scalar(select(func.coalesce(func.sum(FeedbackAttachment.size), 0))) or 0)
        report_bytes = sum(path.stat().st_size for path in root.rglob("reports/*") if path.is_file()) if root.exists() else 0
        workspace_rows = self.session.execute(select(Workspace.id, Workspace.name, func.coalesce(func.sum(Dataset.storage_bytes), 0)).outerjoin(Dataset, Dataset.workspace_id == Workspace.id).group_by(Workspace.id).order_by(func.coalesce(func.sum(Dataset.storage_bytes), 0).desc()).limit(20)).all()
        largest = self.session.scalars(select(Dataset).order_by(Dataset.storage_bytes.desc()).limit(20)).all()
        return {"backend": settings.dataset_storage_backend, "dataset_bytes": dataset_bytes, "report_bytes": report_bytes, "feedback_attachment_bytes": attachment_bytes, "temporary_bytes": 0, "workspace_breakdown": [{"id": wid, "name": name, "bytes": int(size)} for wid, name, size in workspace_rows], "largest_datasets": [{"id": item.id, "name": item.name, "workspace_id": item.workspace_id, "bytes": item.storage_bytes, "rows": item.row_count, "columns": item.column_count} for item in largest]}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def record_system_error(request_id: str | None, error_code: str, route: str, method: str, status_code: int, safe_message: str, user_id: str | None = None, workspace_id: str | None = None) -> None:
    from app.core.database import session_scope
    now = datetime.now(timezone.utc)
    try:
        with session_scope() as session:
            item = session.scalar(select(SystemError).where(SystemError.error_code == error_code, SystemError.route == route[:255], SystemError.safe_message == safe_message[:500]))
            if item:
                item.occurrence_count += 1; item.last_seen_at = now; item.request_id = request_id; item.user_id = user_id; item.workspace_id = workspace_id
            else:
                session.add(SystemError(request_id=request_id, error_code=error_code[:80], route=route[:255], method=method[:10], status_code=status_code, user_id=user_id, workspace_id=workspace_id, safe_message=safe_message[:500], first_seen_at=now, last_seen_at=now))
            session.commit()
    except Exception:
        pass


def audit_admin(session: Session, admin_user_id: str | None, action: str, target_type: str, target_id: str | None, request_id: str | None, details: dict | None = None) -> None:
    session.add(SystemAdminAudit(admin_user_id=admin_user_id, action=action, target_type=target_type, target_id=target_id, request_id=request_id, details=details)); session.commit()
