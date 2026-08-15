from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from app.core.auth import Principal, authenticated_user, require_auth, require_system_admin
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.core.security import hash_one_time_token
from app.repositories import AdminRepository, FeedbackRepository, InvitationRepository, UserRepository, WorkspaceRepository
from app.schemas.beta import AdminDiagnosticsResponse, AdminSummaryResponse, FeedbackAttachmentResponse, FeedbackRequest, FeedbackResponse, InvitationResponse, SupportLookupResponse
from app.services.cleanup import CleanupService
from app.services.email import email_delivery_diagnostics
from app.services.feedback_attachments import FeedbackAttachmentStorage, validate_feedback_attachment
from app.services.product_analytics import ProductEvents, record_product_event
from app.services.saas import UsageService

router = APIRouter(tags=["beta"])


@router.post("/invitations/{token}/accept", response_model=InvitationResponse)
async def accept_invitation(token: str, user=Depends(authenticated_user)) -> InvitationResponse:
    with session_scope() as session: item = InvitationRepository(session).accept(hash_one_time_token(token), user)
    record_product_event(ProductEvents.INVITATION_ACCEPTED, user.id, item["workspace_id"], "invitation", item["id"])
    return InvitationResponse.model_validate({**item, "status": "accepted"})


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(payload: FeedbackRequest, request: Request, principal: Principal = Depends(require_auth)) -> FeedbackResponse:
    context = None
    if payload.include_technical_context:
        context = {"app_version": get_settings().app_version, "request_id": payload.request_id, "route": payload.route or str(request.url.path), "error_code": payload.error_code, "user_agent": (payload.user_agent or request.headers.get("user-agent", ""))[:500]}
    with session_scope() as session:
        item = FeedbackRepository(session).create(user_id=principal.user_id, workspace_id=principal.workspace_id, category=payload.category, message=payload.message, current_page=payload.current_page, dataset_id=payload.dataset_id, technical_context=context, feature_area=payload.feature_area, severity=payload.severity, affected_flow=payload.affected_flow)
    record_product_event(ProductEvents.FEEDBACK_SUBMITTED, principal.user_id, principal.workspace_id, "feedback", item["id"], {"feature_area": payload.feature_area or "other", "severity": payload.severity})
    return FeedbackResponse.model_validate(item)


@router.get("/feedback/config")
async def feedback_config(_: Principal = Depends(require_auth)) -> dict:
    settings = get_settings()
    return {"max_attachments": settings.feedback_max_attachments, "max_attachment_mb": settings.feedback_max_attachment_mb, "accepted_extensions": [".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt", ".log"]}


@router.get("/feedback/mine", response_model=list[FeedbackResponse])
async def my_feedback(limit: int = Query(50, ge=1, le=100), principal: Principal = Depends(require_auth)) -> list[FeedbackResponse]:
    with session_scope() as session:
        return [FeedbackResponse.model_validate(item) for item in FeedbackRepository(session).list_owned(principal.workspace_id, principal.user_id, limit)]


@router.post("/feedback/{feedback_id}/attachments", response_model=list[FeedbackAttachmentResponse], status_code=201)
async def upload_feedback_attachments(feedback_id: str, files: list[UploadFile] = File(...), principal: Principal = Depends(require_auth)) -> list[FeedbackAttachmentResponse]:
    settings = get_settings()
    if not files or len(files) > settings.feedback_max_attachments: raise AppError(f"Attach between 1 and {settings.feedback_max_attachments} files.", "FEEDBACK_ATTACHMENT_COUNT_INVALID", 400)
    with session_scope() as session:
        repository = FeedbackRepository(session); repository.get_owned(feedback_id, principal.workspace_id, principal.user_id)
        if repository.attachment_count(feedback_id) + len(files) > settings.feedback_max_attachments: raise AppError(f"Feedback is limited to {settings.feedback_max_attachments} attachments.", "FEEDBACK_ATTACHMENT_COUNT_INVALID", 400)
    max_bytes = settings.feedback_max_attachment_mb * 1024 * 1024; prepared = []
    for upload in files:
        content = await upload.read(max_bytes + 1)
        original, safe = validate_feedback_attachment(upload.filename or "attachment", upload.content_type, content, max_bytes)
        prepared.append((original, safe, upload.content_type or "application/octet-stream", content))
    storage = FeedbackAttachmentStorage(settings.storage_root); created = []
    for original, safe, content_type, content in prepared:
        attachment_id, storage_key, path = storage.save(principal.workspace_id, feedback_id, safe, content)
        try:
            with session_scope() as session:
                item = FeedbackRepository(session).add_attachment(id=attachment_id, feedback_id=feedback_id, workspace_id=principal.workspace_id, original_filename=original, safe_filename=safe, content_type=content_type, size=len(content), storage_key=storage_key)
        except Exception:
            storage.remove(path); raise
        created.append(FeedbackAttachmentResponse.model_validate(item))
    return created


@router.get("/ai/provider-status")
async def provider_status(principal: Principal = Depends(require_auth)) -> dict:
    settings = get_settings()
    with session_scope() as session:
        workspace = WorkspaceRepository(session).get_for_user(principal.workspace_id, principal.user_id)
        user = UserRepository(session).get(principal.user_id)
    external_configured = settings.ai_provider == "openai"
    plan_external_ai = UsageService(principal.workspace_id).has("external_ai")
    external_allowed = settings.feature_external_ai and workspace.get("external_ai_enabled", True) and user.email_verified_at is not None and plan_external_ai
    effective = settings.ai_provider if not external_configured or external_allowed else "mock"
    return {"app_version": settings.app_version, "configured_provider": settings.ai_provider, "effective_provider": effective, "external_ai_enabled": workspace.get("external_ai_enabled", True), "external_ai_allowed": external_allowed, "external_ai_plan_entitled": plan_external_ai, "email_verified": user.email_verified_at is not None, "privacy_notice": "External AI receives the question, schema metadata, validated plan, and calculated result summary—not full dataset rows by default."}


@router.get("/admin/feedback")
async def admin_feedback(limit: int = Query(100, ge=1, le=500), _=Depends(require_system_admin)) -> list[dict]:
    with session_scope() as session: return FeedbackRepository(session).list_all(limit)


@router.get("/admin/feedback/{feedback_id}/attachments/{attachment_id}")
async def admin_feedback_attachment(feedback_id: str, attachment_id: str, _=Depends(require_system_admin)) -> Response:
    with session_scope() as session: item = FeedbackRepository(session).get_attachment_for_admin(feedback_id, attachment_id)
    content = FeedbackAttachmentStorage(get_settings().storage_root).read(item.storage_key)
    return Response(content, media_type=item.content_type, headers={"Content-Disposition": f'attachment; filename="{item.original_filename}"'})


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
    email = email_delivery_diagnostics(); email_configured = settings.email_provider.casefold() == "console" or bool(settings.smtp_host and settings.email_from)
    return AdminDiagnosticsResponse(app_version=settings.app_version, database=database, storage=storage, queue=settings.job_execution_mode, rate_limit_backend=settings.rate_limit_backend, storage_backend=settings.dataset_storage_backend, email_provider=settings.email_provider, email_configured=email_configured, last_email_status=email.get("status"), last_email_operation=email.get("operation"))


@router.post("/admin/cleanup")
async def admin_cleanup(_=Depends(require_system_admin)) -> dict[str, int]:
    return CleanupService().run()
