from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.auth import authenticated_user, require_system_admin
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import Subscription, UpgradeRequest, UsageEvent, User, Workspace
from app.repositories import WorkspaceRepository
from app.services.admin_metrics import audit_admin, model_dict
from app.services.billing import get_billing_provider
from app.services.commercial import EntitlementService, plan_catalog, public_catalog, public_plan
from app.services.email import send_transactional_email
from app.services.product_analytics import ProductEvents, record_product_event

router = APIRouter(tags=["commercial"])


class UpgradeRequestCreate(BaseModel):
    requested_plan: Literal["pro", "business"]
    message: str | None = Field(default=None, max_length=1000)


class UpgradeRequestStatus(BaseModel):
    status: Literal["pending", "contacted", "approved", "declined"]


class ManualPlanRequest(BaseModel):
    plan_code: Literal["pro", "business", "none"]
    expires_at: datetime | None = None
    confirmed: bool = False


def _workspace_access(session, workspace_id: str, user_id: str, owner_only: bool = False) -> dict:
    workspace = WorkspaceRepository(session).get_for_user(workspace_id, user_id)
    allowed = {"owner"} if owner_only else {"owner", "admin", "member"}
    if workspace["role"] not in allowed: raise AppError("Workspace owner access is required.", "WORKSPACE_OWNER_REQUIRED", 403)
    return workspace


@router.get("/plans")
async def plans() -> dict:
    settings = get_settings()
    return {"plans": public_catalog(), "currency": settings.pricing_currency, "billing_provider": settings.billing_provider, "payments_enabled": False, "annual_pricing_available": False}


@router.get("/workspaces/{workspace_id}/subscription")
async def workspace_subscription(workspace_id: str, user=Depends(authenticated_user)) -> dict:
    with session_scope() as session: _workspace_access(session, workspace_id, user.id)
    found = EntitlementService(workspace_id).resolution(); workspace: Workspace = found["workspace"]; subscription: Subscription | None = found["subscription"]
    trial_ends = workspace.trial_ends_at
    days_remaining = max(0, ((trial_ends.replace(tzinfo=timezone.utc) if trial_ends and trial_ends.tzinfo is None else trial_ends) - datetime.now(timezone.utc)).days) if trial_ends and found["trial_status"] == "active" else None
    return {"effective_plan": public_plan(found["plan"]), "base_plan_code": workspace.plan_code, "plan_source": found["source"], "trial": {"eligible": get_settings().pro_trial_enabled and workspace.trial_started_at is None, "status": found["trial_status"], "plan": workspace.trial_plan, "started_at": workspace.trial_started_at, "ends_at": workspace.trial_ends_at, "days_remaining": days_remaining}, "subscription": model_dict(subscription) if subscription else None, "usage": EntitlementService(workspace_id).summary(), "upgrade_options": [item for item in public_catalog() if item["upgrade_order"] > found["plan"].upgrade_order], "data_retention_policy": "Existing data is retained if a plan or trial ends; only new creation may be restricted while over limit."}


@router.post("/workspaces/{workspace_id}/trial/start", status_code=201)
async def start_trial(workspace_id: str, user=Depends(authenticated_user)) -> dict:
    settings = get_settings()
    if not settings.pro_trial_enabled: raise AppError("Pro trials are not currently available.", "TRIAL_DISABLED", 409)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        _workspace_access(session, workspace_id, user.id, owner_only=True); workspace = session.get(Workspace, workspace_id)
        if workspace.trial_started_at is not None: raise AppError("This workspace has already used its trial.", "TRIAL_NOT_ELIGIBLE", 409)
        current = EntitlementService(workspace_id).resolution()
        if current["plan"].upgrade_order >= plan_catalog()["pro"].upgrade_order: raise AppError("This workspace already has Pro or higher access.", "TRIAL_NOT_ELIGIBLE", 409)
        workspace.trial_started_at = now; workspace.trial_ends_at = now + timedelta(days=settings.pro_trial_days); workspace.trial_plan = "pro"; workspace.trial_status = "active"; session.commit()
    EntitlementService(workspace_id).activity("trial_started", user.id, workspace_id, {"plan": "pro", "days": settings.pro_trial_days})
    record_product_event(ProductEvents.TRIAL_STARTED, user.id, workspace_id, "workspace", workspace_id, {"plan_code": "pro"})
    try: await send_transactional_email(user.email, "Your DataPilot Pro trial has started", f"Your {settings.pro_trial_days}-day Pro trial is active. Existing data will remain available when the trial ends.", "trial_started")
    except Exception: pass
    return {"workspace_id": workspace_id, "trial_plan": "pro", "status": "active", "started_at": now, "ends_at": now + timedelta(days=settings.pro_trial_days), "effective_plan": "pro"}


@router.post("/workspaces/{workspace_id}/upgrade-request", status_code=201)
async def request_upgrade(workspace_id: str, payload: UpgradeRequestCreate, user=Depends(authenticated_user)) -> dict:
    with session_scope() as session:
        _workspace_access(session, workspace_id, user.id, owner_only=True)
        existing = session.scalar(select(UpgradeRequest).where(UpgradeRequest.workspace_id == workspace_id, UpgradeRequest.status.in_(["pending", "contacted"])))
        if existing: raise AppError("An upgrade request is already being reviewed.", "UPGRADE_REQUEST_EXISTS", 409)
        item = UpgradeRequest(workspace_id=workspace_id, user_id=user.id, requested_plan=payload.requested_plan, message=payload.message, status="pending"); session.add(item); session.commit(); result = model_dict(item)
    EntitlementService(workspace_id).activity("upgrade_requested", user.id, item.id, {"plan": payload.requested_plan})
    record_product_event(ProductEvents.UPGRADE_REQUESTED, user.id, workspace_id, "upgrade_request", item.id, {"plan_code": payload.requested_plan})
    return result


@router.get("/admin/commercial/summary")
async def commercial_summary(_=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        workspaces = session.scalars(select(Workspace)).all(); requests = session.scalars(select(UpgradeRequest)).all(); subscriptions = session.scalars(select(Subscription).where(Subscription.status == "active")).all()
        external_rows = session.execute(select(UsageEvent.workspace_id, func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.event_type == "external_ai_call").group_by(UsageEvent.workspace_id)).all()
    distribution = {code: 0 for code in plan_catalog()}; over_limit = []; active_trials = 0; expiring_trials = 0; now = datetime.now(timezone.utc)
    workspace_plans = {}
    for workspace in workspaces:
        service = EntitlementService(workspace.id); found = service.resolution(); code = found["plan_code"]; workspace_plans[workspace.id] = code; distribution[code] = distribution.get(code, 0) + 1
        summary = service.summary()
        if summary["over_limit"]: over_limit.append({"workspace_id": workspace.id, "workspace_name": workspace.name, "plan": code, "resources": [key for key, value in summary["usage"].items() if value["level"] == "limit"]})
        if found["source"] == "trial":
            active_trials += 1
            if workspace.trial_ends_at and (workspace.trial_ends_at.replace(tzinfo=timezone.utc) if workspace.trial_ends_at.tzinfo is None else workspace.trial_ends_at) <= now + timedelta(days=5): expiring_trials += 1
    external_by_plan: dict[str, int] = {}
    for workspace_id, quantity in external_rows: external_by_plan[workspace_plans.get(workspace_id, "free")] = external_by_plan.get(workspace_plans.get(workspace_id, "free"), 0) + int(quantity)
    return {"plan_distribution": [{"plan": code, "workspaces": count} for code, count in distribution.items()], "active_trials": active_trials, "trials_expiring_5_days": expiring_trials, "upgrade_requests": {status: sum(1 for item in requests if item.status == status) for status in ("pending", "contacted", "approved", "declined")}, "manual_subscriptions": sum(1 for item in subscriptions if item.billing_provider == "manual"), "workspaces_over_limit": over_limit, "external_ai_usage_by_plan": [{"plan": code, "calls": count} for code, count in external_by_plan.items()], "commercial_funnel": {"free_workspaces": distribution.get("free", 0), "trial_workspaces": active_trials, "upgrade_requests": len(requests), "manually_upgraded": sum(1 for item in subscriptions if item.billing_provider == "manual")}, "revenue_available": False, "revenue_message": "Revenue unavailable: manual subscription assignments do not represent money received.", "profit_available": False, "profit_message": "Profit unavailable until billing and cost accounting are enabled."}


@router.get("/admin/commercial/trials")
async def commercial_trials(limit: int = Query(100, ge=1, le=500), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        rows = session.scalars(select(Workspace).where(Workspace.trial_started_at.is_not(None)).order_by(Workspace.trial_ends_at.desc()).limit(limit)).all()
        return {"items": [{"workspace_id": item.id, "workspace_name": item.name, "base_plan": item.plan_code, "trial_plan": item.trial_plan, "trial_status": EntitlementService(item.id).resolution()["trial_status"], "trial_started_at": item.trial_started_at, "trial_ends_at": item.trial_ends_at} for item in rows]}


@router.get("/admin/commercial/upgrade-requests")
async def commercial_requests(status: str | None = None, limit: int = Query(100, ge=1, le=500), _=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        query = select(UpgradeRequest, User.email, Workspace.name).join(User, User.id == UpgradeRequest.user_id).join(Workspace, Workspace.id == UpgradeRequest.workspace_id)
        if status: query = query.where(UpgradeRequest.status == status)
        rows = session.execute(query.order_by(UpgradeRequest.created_at.desc()).limit(limit)).all()
        return {"items": [{**model_dict(item), "user_email": email, "workspace_name": workspace_name} for item, email, workspace_name in rows]}


@router.post("/admin/commercial/upgrade-requests/{request_id}/status")
async def update_request_status(request_id: str, payload: UpgradeRequestStatus, request: Request, admin=Depends(require_system_admin)) -> dict:
    with session_scope() as session:
        item = session.get(UpgradeRequest, request_id)
        if item is None: raise AppError("Upgrade request not found.", "UPGRADE_REQUEST_NOT_FOUND", 404)
        item.status = payload.status
        audit_admin(session, admin.id, "commercial_request_status_changed", "upgrade_request", item.id, request.state.request_id, {"status": payload.status})
        return model_dict(item)


@router.post("/admin/commercial/workspaces/{workspace_id}/manual-plan")
async def manual_plan(workspace_id: str, payload: ManualPlanRequest, request: Request, admin=Depends(require_system_admin)) -> dict:
    if not payload.confirmed: raise AppError("Explicit confirmation is required.", "ADMIN_CONFIRMATION_REQUIRED", 400)
    with session_scope() as session:
        provider = get_billing_provider(for_admin=True)
        item = provider.remove(session, workspace_id) if payload.plan_code == "none" else provider.assign(session, workspace_id, payload.plan_code, payload.expires_at)
        action = "manual_plan_removed" if payload.plan_code == "none" else "manual_plan_assigned"
        audit_admin(session, admin.id, action, "workspace", workspace_id, request.state.request_id, {"plan_code": payload.plan_code, "expires_at": payload.expires_at.isoformat() if payload.expires_at else None})
    record_product_event(ProductEvents.SUBSCRIPTION_ACTIVATED, admin.id, workspace_id, "workspace", workspace_id, {"plan_code": payload.plan_code, "assignment_type": "manual"})
    return {"workspace_id": workspace_id, "effective_plan": EntitlementService(workspace_id).plan()[0], "subscription": model_dict(item) if item else None, "revenue_recorded": False}
