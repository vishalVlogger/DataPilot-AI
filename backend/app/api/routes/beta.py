from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from app.core.auth import Principal, authenticated_user, require_auth, require_system_admin
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.core.security import hash_one_time_token
from app.repositories import AdminRepository, FeedbackRepository, InvitationRepository, UserRepository, WorkspaceRepository
from app.schemas.beta import AdminDiagnosticsResponse, AdminSummaryResponse, FeedbackRequest, FeedbackResponse, InvitationResponse, SupportLookupResponse
from app.services.cleanup import CleanupService

router = APIRouter(tags=["beta"])


@router.post("/invitations/{token}/accept", response_model=InvitationResponse)
async def accept_invitation(token: str, user=Depends(authenticated_user)) -> InvitationResponse:
    with session_scope() as session: item = InvitationRepository(session).accept(hash_one_time_token(token), user)
    return InvitationResponse.model_validate(item)


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(payload: FeedbackRequest, request: Request, principal: Principal = Depends(require_auth)) -> FeedbackResponse:
    context = None
    if payload.include_technical_context:
        context = {"app_version": get_settings().app_version, "request_id": payload.request_id, "route": payload.route or str(request.url.path), "error_code": payload.error_code, "user_agent": (payload.user_agent or request.headers.get("user-agent", ""))[:500]}
    with session_scope() as session:
        item = FeedbackRepository(session).create(user_id=principal.user_id, workspace_id=principal.workspace_id, category=payload.category, message=payload.message, current_page=payload.current_page, dataset_id=payload.dataset_id, technical_context=context)
    return FeedbackResponse.model_validate(item)


@router.get("/ai/provider-status")
async def provider_status(principal: Principal = Depends(require_auth)) -> dict:
    settings = get_settings()
    with session_scope() as session:
        workspace = WorkspaceRepository(session).get_for_user(principal.workspace_id, principal.user_id)
        user = UserRepository(session).get(principal.user_id)
    external_configured = settings.ai_provider == "openai"
    external_allowed = settings.feature_external_ai and workspace.get("external_ai_enabled", True) and user.email_verified_at is not None
    effective = settings.ai_provider if not external_configured or external_allowed else "mock"
    return {"app_version": settings.app_version, "configured_provider": settings.ai_provider, "effective_provider": effective, "external_ai_enabled": workspace.get("external_ai_enabled", True), "external_ai_allowed": external_allowed, "email_verified": user.email_verified_at is not None, "privacy_notice": "External AI receives the question, schema metadata, validated plan, and calculated result summary—not full dataset rows by default."}


@router.get("/admin/feedback")
async def admin_feedback(limit: int = Query(100, ge=1, le=500), _=Depends(require_system_admin)) -> list[dict]:
    with session_scope() as session: return FeedbackRepository(session).list_all(limit)


@router.get("/admin/summary", response_model=AdminSummaryResponse)
async def admin_summary(_=Depends(require_system_admin)) -> AdminSummaryResponse:
    with session_scope() as session: return AdminSummaryResponse.model_validate(AdminRepository(session).summary())


@router.get("/admin/support", response_model=SupportLookupResponse)
async def support_lookup(q: str = Query(min_length=2, max_length=320), _=Depends(require_system_admin)) -> SupportLookupResponse:
    with session_scope() as session: return SupportLookupResponse(results=AdminRepository(session).support_lookup(q))


@router.get("/admin/diagnostics", response_model=AdminDiagnosticsResponse)
async def admin_diagnostics(_=Depends(require_system_admin)) -> AdminDiagnosticsResponse:
    settings = get_settings(); database = storage = "ok"
    try:
        with session_scope() as session: session.execute(text("SELECT 1"))
        root: Path = settings.storage_root.resolve(); root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir(): raise OSError()
    except Exception: database = storage = "unavailable"
    return AdminDiagnosticsResponse(app_version=settings.app_version, database=database, storage=storage, queue=settings.job_execution_mode, rate_limit_backend=settings.rate_limit_backend, storage_backend=settings.dataset_storage_backend)


@router.post("/admin/cleanup")
async def admin_cleanup(_=Depends(require_system_admin)) -> dict[str, int]:
    return CleanupService().run()
