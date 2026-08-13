from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text

from app.core.auth import require_system_admin
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import Feedback, Job, Notification, SystemAdminAudit, SystemError, UsageEvent, User, Workspace
from app.repositories import AdminRepository, FeedbackRepository
from app.services.admin_metrics import AdminMetricsService, audit_admin, model_dict
from app.services.cleanup import CleanupService
from app.services.datasets.storage import DatasetStorage
from app.services.email import email_delivery_diagnostics, send_transactional_email
from app.services.jobs.manager import JobManager
from app.services.jobs.executor import queue_diagnostics
from app.services.operations import infrastructure_status

router = APIRouter(prefix="/admin", tags=["system-admin"], dependencies=[Depends(require_system_admin)])


class UserActionRequest(BaseModel):
    action: Literal["activate", "deactivate", "grant_admin", "revoke_admin"]
    confirmed: bool = False


class FeedbackWorkflowRequest(BaseModel):
    status: Literal["new", "reviewing", "planned", "resolved"]
    priority: Literal["low", "medium", "high"]


def page(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)) -> tuple[int, int]: return limit, offset


@router.get("/overview")
async def overview(days: int = Query(30, ge=1, le=30), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: result = AdminMetricsService(session).overview(days)
    result["app_version"] = get_settings().app_version
    result["platform_status"] = "healthy"
    result["status_rule"] = "Critical when database/storage fails; degraded when a configured optional provider fails; healthy when required services pass."
    return result


@router.get("/users")
async def users(search: str | None = Query(None, max_length=200), verified: bool | None = None, active: bool | None = None, admin: bool | None = None, paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return {"metrics": AdminMetricsService(session).user_metrics(), **AdminMetricsService(session).users(search, verified, active, admin, *paging)}


@router.get("/users/{user_id}")
async def user_detail(user_id: str, _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).user_detail(user_id)


@router.post("/users/{user_id}/actions")
async def user_action(user_id: str, payload: UserActionRequest, request: Request, admin=Depends(require_system_admin)) -> dict:
    if not payload.confirmed: raise AppError("Explicit confirmation is required.", "ADMIN_CONFIRMATION_REQUIRED", 400)
    with session_scope() as session:
        target = session.get(User, user_id)
        if not target: raise AppError("User not found.", "ADMIN_USER_NOT_FOUND", 404)
        if target.id == admin.id and payload.action in {"deactivate", "revoke_admin"}: raise AppError("You cannot deactivate yourself or revoke your own system-admin access.", "ADMIN_SELF_LOCKOUT", 409)
        if payload.action == "revoke_admin" and target.is_system_admin:
            count = int(session.scalar(select(func.count()).select_from(User).where(User.is_system_admin.is_(True), User.is_active.is_(True))) or 0)
            if count <= 1: raise AppError("The last active system administrator cannot be revoked.", "LAST_SYSTEM_ADMIN", 409)
        if payload.action == "activate": target.is_active = True
        elif payload.action == "deactivate": target.is_active = False
        elif payload.action == "grant_admin": target.is_system_admin = True
        elif payload.action == "revoke_admin": target.is_system_admin = False
        audit_admin(session, admin.id, f"user_{payload.action}", "user", target.id, request.state.request_id)
        return {"id": target.id, "active": target.is_active, "system_admin": target.is_system_admin}


@router.get("/workspaces")
async def workspaces(search: str | None = Query(None, max_length=200), paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).workspaces(search, *paging)


@router.get("/workspaces/{workspace_id}")
async def workspace_detail(workspace_id: str, _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).workspace_detail(workspace_id)


@router.get("/usage")
async def usage(days: int = Query(30, ge=1, le=30), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).usage(days)


@router.get("/health")
async def health(_=Depends(require_system_admin)) -> dict:
    settings = get_settings(); diagnostics = email_delivery_diagnostics(); infra = infrastructure_status(); database = infra["database"]; storage = infra["storage"]; redis = infra["redis"]; optional_failed = redis == "unavailable"
    if settings.email_provider == "smtp" and diagnostics.get("status") == "failed": optional_failed = True
    storage_failed = isinstance(storage, dict) and storage.get("status") == "unavailable"
    platform_status = "critical" if database == "unavailable" or storage_failed else "degraded" if optional_failed else "healthy"
    return {"platform_status": platform_status, "api": "ok", "readiness": "ready" if platform_status != "critical" else "not ready", "database": database, "storage": storage, "redis": redis, "worker": infra["worker"], "email": diagnostics.get("status") or "not attempted", "sentry": "configured" if settings.sentry_dsn else "not configured", "ai_provider": settings.ai_provider, "app_version": settings.app_version}


@router.get("/jobs")
async def jobs(status: str | None = Query(None, max_length=20), type: str | None = Query(None, max_length=50), days: int | None = Query(None, ge=1, le=30), paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: result = AdminMetricsService(session).jobs(status, type, days, *paging)
    result["queue"] = queue_diagnostics(); return result


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request, confirmed: bool = False, admin=Depends(require_system_admin)) -> dict:
    if not confirmed: raise AppError("Explicit confirmation is required.", "ADMIN_CONFIRMATION_REQUIRED", 400)
    with session_scope() as session:
        job = session.get(Job, job_id)
        if not job: raise AppError("Background job not found.", "JOB_NOT_FOUND", 404)
        if job.type != "report" or not job.retryable or job.status != "failed": raise AppError("This job is not safe to retry.", "JOB_NOT_RETRYABLE", 409)
        workspace_id, user_id = job.workspace_id, job.user_id
    from app.services.datasets.storage import get_dataset_storage
    settings = get_settings(); store = get_dataset_storage(settings.storage_root, settings.parquet_compression, workspace_id, user_id)
    try: result = JobManager().retry(job_id, store)
    except ValueError as exc: raise AppError(str(exc), "JOB_NOT_RETRYABLE", 409) from exc
    with session_scope() as session: audit_admin(session, admin.id, "job_retry", "job", job_id, request.state.request_id)
    return result


@router.get("/errors")
async def errors(error_code: str | None = Query(None, max_length=80), route: str | None = Query(None, max_length=200), status_code: int | None = None, days: int | None = Query(None, ge=1, le=30), paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).errors(error_code, route, status_code, days, *paging)


@router.get("/storage")
async def storage(_=Depends(require_system_admin)) -> dict:
    with session_scope() as session: return AdminMetricsService(session).storage()


@router.get("/providers")
async def providers(_=Depends(require_system_admin)) -> dict:
    settings = get_settings(); database_type = settings.database_url.split(":", 1)[0]
    return {"email": {"provider": settings.email_provider, "configured": settings.email_provider == "console" or bool(settings.smtp_host and settings.email_from)}, "ai": {"provider": settings.ai_provider, "configured": settings.ai_provider == "mock" or (settings.ai_provider == "openai" and bool(settings.openai_api_key)) or settings.ai_provider == "ollama"}, "redis": {"configured": bool(settings.redis_url), "backend": settings.rate_limit_backend}, "sentry": {"configured": bool(settings.sentry_dsn)}, "storage": {"backend": settings.dataset_storage_backend}, "database": {"type": database_type}}


@router.get("/feedback")
async def feedback(request: Request, category: str | None = Query(None, max_length=30), status: str | None = Query(None, max_length=30), paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)):
    limit, offset = paging
    with session_scope() as session:
        query = select(Feedback)
        if category: query = query.where(Feedback.category == category)
        if status: query = query.where(Feedback.status == status)
        else: query = query.where(Feedback.status != "resolved")
        total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        ids = session.scalars(query.order_by(Feedback.created_at.desc()).limit(limit).offset(offset)).all()
        all_items = {item["id"]: item for item in FeedbackRepository(session).list_all(limit + offset)}
        items = [all_items[item.id] for item in ids]
        # Compatibility for the Milestone 6 support client; the 6.2 console always sends pagination.
        status_counts = {value: int(session.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == value)) or 0) for value in ("new", "reviewing", "planned", "resolved")}
        return items if not request.url.query else {"items": items, "total": total, "limit": limit, "offset": offset, "status_counts": status_counts}


@router.patch("/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, payload: FeedbackWorkflowRequest, request: Request, admin=Depends(require_system_admin)) -> dict:
    recipient = None; created_notification = False
    with session_scope() as session:
        item = session.get(Feedback, feedback_id)
        if not item: raise AppError("Feedback not found.", "FEEDBACK_NOT_FOUND", 404)
        was_resolved = item.status == "resolved"
        item.status = payload.status; item.priority = payload.priority
        item.resolved_at = datetime.now(timezone.utc) if payload.status == "resolved" else None
        if payload.status == "resolved" and not was_resolved:
            session.add(Notification(user_id=item.user_id, workspace_id=item.workspace_id, type="feedback_resolved", title="Your feedback was resolved", message="Thanks for helping improve DataPilot. Your feedback has been reviewed and marked as resolved.", resource_type="feedback", resource_id=item.id))
            target = session.get(User, item.user_id); recipient = target.email if target else None; created_notification = True
        audit_admin(session, admin.id, "feedback_status_change", "feedback", feedback_id, request.state.request_id, {"status": payload.status, "priority": payload.priority, "user_notified": created_notification})
        result = {"id": item.id, "status": item.status, "priority": item.priority, "resolved_at": item.resolved_at, "user_notified": created_notification}
    if recipient and created_notification:
        try:
            await send_transactional_email(recipient, "Your DataPilot feedback was resolved", "Thanks for helping improve DataPilot. Your feedback has been reviewed and marked as resolved. Sign in to view its status.", "feedback_resolved")
        except Exception:
            # The durable in-app notification remains available if email delivery is temporarily unavailable.
            pass
    return result


@router.get("/support")
async def support(q: str = Query(min_length=2, max_length=320), request: Request = None, admin=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        results = AdminRepository(session).support_lookup(q)
        errors = session.scalars(select(SystemError).where(or_(SystemError.request_id == q, SystemError.error_code.ilike(f"%{q}%"))).limit(20)).all()
        results.extend([{"type": "error", **model_dict(item)} for item in errors])
        audit_admin(session, admin.id, "support_lookup", "query", None, request.state.request_id, {"result_count": len(results)})
        return {"results": results}


@router.get("/audit")
async def audit(action: str | None = Query(None, max_length=80), paging: tuple[int, int] = Depends(page), _=Depends(require_system_admin)) -> dict:
    limit, offset = paging
    with session_scope() as session:
        query = select(SystemAdminAudit, User.email).outerjoin(User, User.id == SystemAdminAudit.admin_user_id)
        if action: query = query.where(SystemAdminAudit.action == action)
        total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = session.execute(query.order_by(SystemAdminAudit.created_at.desc()).limit(limit).offset(offset)).all()
        return {"items": [{**model_dict(item), "admin_email": email} for item, email in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/business")
async def business(days: int = Query(30, ge=1, le=30), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        plans = session.execute(select(Workspace.plan_code, func.count()).group_by(Workspace.plan_code)).all()
        calls = int(session.scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.event_type == "ai_request", UsageEvent.created_at >= AdminMetricsService.cutoff(days))) or 0)
        storage = int(AdminMetricsService(session).storage()["dataset_bytes"])
        users = int(session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0)
    return {"range_days": days, "beta_users": users, "plan_distribution": [{"plan": plan, "workspaces": count} for plan, count in plans], "external_ai_calls": calls, "storage_bytes": storage, "estimated_cost": None, "revenue_available": False, "revenue_message": "Revenue metrics unavailable. Billing is not enabled yet. Revenue, MRR, ARR, and profit will appear after payment integration."}


@router.post("/cleanup")
async def cleanup(request: Request, confirmed: bool = False, admin=Depends(require_system_admin)) -> dict[str, int]:
    if not confirmed: raise AppError("Explicit confirmation is required.", "ADMIN_CONFIRMATION_REQUIRED", 400)
    result = CleanupService().run()
    with session_scope() as session: audit_admin(session, admin.id, "retention_cleanup", "platform", None, request.state.request_id, {"deleted_total": sum(result.values())})
    return result
