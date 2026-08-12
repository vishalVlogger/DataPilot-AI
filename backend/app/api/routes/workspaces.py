from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.auth import authenticated_user
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.core.rate_limit import rate_limiter
from app.core.security import hash_one_time_token, new_one_time_token, normalize_email
from app.repositories import InvitationRepository, MemberRepository, UserRepository, WorkspaceRepository
from app.schemas.beta import InvitationCreateRequest, InvitationResponse, MemberResponse, MemberRoleRequest
from app.schemas.saas import WorkspaceCreateRequest, WorkspaceResponse, WorkspaceUpdateRequest
from app.services.email import send_transactional_email
from app.services.features import feature_flags
from app.services.jobs.manager import JobManager
from app.services.workspace_lifecycle import cancel_workspace_deletion, ensure_workspace_writable, schedule_workspace_deletion

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceExportRequest(BaseModel):
    include_raw_datasets: bool = False


class WorkspaceDeletionRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=120)
    export_first: bool = False


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(user=Depends(authenticated_user)) -> list[WorkspaceResponse]:
    with session_scope() as session: items = WorkspaceRepository(session).list_for_user(user.id)
    return [WorkspaceResponse.model_validate(item) for item in items]


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(payload: WorkspaceCreateRequest, user=Depends(authenticated_user)) -> WorkspaceResponse:
    with session_scope() as session: item = WorkspaceRepository(session).create(user.id, payload.name.strip(), get_settings().default_plan)
    return WorkspaceResponse.model_validate(item)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, user=Depends(authenticated_user)) -> WorkspaceResponse:
    with session_scope() as session: item = WorkspaceRepository(session).get_for_user(workspace_id, user.id)
    return WorkspaceResponse.model_validate(item)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(workspace_id: str, payload: WorkspaceUpdateRequest, user=Depends(authenticated_user)) -> WorkspaceResponse:
    ensure_workspace_writable(workspace_id)
    with session_scope() as session: item = WorkspaceRepository(session).update(workspace_id, user.id, **payload.model_dump(exclude_none=True))
    return WorkspaceResponse.model_validate(item)


def _manager(session, workspace_id: str, user_id: str, writable: bool = False) -> dict:
    workspace = WorkspaceRepository(session).get_for_user(workspace_id, user_id)
    if workspace["role"] not in {"owner", "admin"}: raise AppError("Workspace administrator access is required.", "WORKSPACE_ADMIN_REQUIRED", 403)
    if writable and workspace.get("deletion_scheduled_for"): raise AppError("This workspace is read-only while deletion is scheduled.", "WORKSPACE_DELETION_PENDING", 409)
    return workspace


async def _deliver_invitation(email: str, token: str) -> tuple[str, str | None]:
    settings = get_settings(); link = f"{settings.frontend_url}/accept-invitation?token={token}"
    result = await send_transactional_email(email, "DataPilot workspace invitation", f"You were invited to DataPilot: {link}\nThis one-time invitation expires in {settings.invitation_expire_days} days.", "workspace_invitation")
    return result.status, link if settings.expose_development_email_links else None


@router.post("/{workspace_id}/invitations", response_model=InvitationResponse, status_code=201)
async def invite_member(workspace_id: str, payload: InvitationCreateRequest, request: Request, user=Depends(authenticated_user)) -> InvitationResponse:
    if not feature_flags.enabled("workspace_invites"): raise AppError("Workspace invitations are disabled.", "FEATURE_DISABLED", 404)
    if user.email_verified_at is None: raise AppError("Verify your email before inviting members.", "EMAIL_VERIFICATION_REQUIRED", 403)
    normalized_email = normalize_email(str(payload.email))
    rate_limiter.check(f"invite:user:{user.id}", 10, 3600); rate_limiter.check(f"invite:ip:{request.client.host if request.client else 'unknown'}", 30, 3600); rate_limiter.check(f"invite:email:{hash_one_time_token(normalized_email)}", 3, 3600)
    token, token_hash = new_one_time_token(); settings = get_settings()
    with session_scope() as session:
        _manager(session, workspace_id, user.id, writable=True)
        item = InvitationRepository(session, workspace_id).create(str(payload.email), normalized_email, payload.role, token_hash, user.id, datetime.now(timezone.utc) + timedelta(days=settings.invitation_expire_days))
        response = InvitationResponse.model_validate(item, from_attributes=True)
    delivery_status, development_link = await _deliver_invitation(str(payload.email), token)
    return response.model_copy(update={"delivery_status": delivery_status, "development_invitation_url": development_link})


@router.get("/{workspace_id}/invitations", response_model=list[InvitationResponse])
async def list_invitations(workspace_id: str, user=Depends(authenticated_user)) -> list[InvitationResponse]:
    with session_scope() as session:
        _manager(session, workspace_id, user.id); items = InvitationRepository(session, workspace_id).list()
    return [InvitationResponse.model_validate(item) for item in items]


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(workspace_id: str, invitation_id: str, user=Depends(authenticated_user)) -> None:
    with session_scope() as session: _manager(session, workspace_id, user.id, writable=True); InvitationRepository(session, workspace_id).revoke(invitation_id)


@router.post("/{workspace_id}/invitations/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(workspace_id: str, invitation_id: str, request: Request, user=Depends(authenticated_user)) -> InvitationResponse:
    if not feature_flags.enabled("workspace_invites"): raise AppError("Workspace invitations are disabled.", "FEATURE_DISABLED", 404)
    if user.email_verified_at is None: raise AppError("Verify your email before inviting members.", "EMAIL_VERIFICATION_REQUIRED", 403)
    rate_limiter.check(f"invite-resend:user:{user.id}", 10, 3600); rate_limiter.check(f"invite-resend:ip:{request.client.host if request.client else 'unknown'}", 30, 3600); rate_limiter.check(f"invite-resend:invitation:{invitation_id}", 3, 3600)
    token, token_hash = new_one_time_token(); settings = get_settings()
    with session_scope() as session:
        _manager(session, workspace_id, user.id, writable=True)
        item = InvitationRepository(session, workspace_id).resend(invitation_id, token_hash, datetime.now(timezone.utc) + timedelta(days=settings.invitation_expire_days))
        response = InvitationResponse.model_validate(item, from_attributes=True)
    delivery_status, development_link = await _deliver_invitation(item.email, token)
    return response.model_copy(update={"delivery_status": delivery_status, "development_invitation_url": development_link, "status": "pending"})


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def list_members(workspace_id: str, user=Depends(authenticated_user)) -> list[MemberResponse]:
    with session_scope() as session: WorkspaceRepository(session).get_for_user(workspace_id, user.id); items = MemberRepository(session, workspace_id).list()
    return [MemberResponse.model_validate(item) for item in items]


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(workspace_id: str, user_id: str, payload: MemberRoleRequest, user=Depends(authenticated_user)) -> MemberResponse:
    with session_scope() as session: _manager(session, workspace_id, user.id, writable=True); item = MemberRepository(session, workspace_id).change_role(user_id, payload.role)
    return MemberResponse.model_validate(item)


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(workspace_id: str, user_id: str, user=Depends(authenticated_user)) -> None:
    with session_scope() as session: _manager(session, workspace_id, user.id, writable=True); MemberRepository(session, workspace_id).remove(user_id)


@router.post("/{workspace_id}/export", status_code=202)
async def export_workspace(workspace_id: str, payload: WorkspaceExportRequest, user=Depends(authenticated_user)) -> dict:
    with session_scope() as session: _manager(session, workspace_id, user.id)
    job = JobManager().create_workspace_export_job(workspace_id, user.id, payload.include_raw_datasets)
    return {"job_id": job["id"], "status": job["status"], "includes_raw_datasets": payload.include_raw_datasets}


@router.post("/{workspace_id}/deletion-request", status_code=202)
async def request_workspace_deletion(workspace_id: str, payload: WorkspaceDeletionRequest, user=Depends(authenticated_user)) -> dict:
    if payload.export_first:
        with session_scope() as session:
            workspace = WorkspaceRepository(session).get_for_user(workspace_id, user.id)
            if workspace["role"] != "owner": raise AppError("Workspace owner access is required.", "WORKSPACE_OWNER_REQUIRED", 403)
        job = JobManager().create_workspace_export_job(workspace_id, user.id, False)
        return {"workspace_id": workspace_id, "export_job_id": job["id"], "deletion_scheduled": False, "message": "Download the completed export, then submit deletion again."}
    return schedule_workspace_deletion(workspace_id, user.id, payload.confirmation)


@router.delete("/{workspace_id}/deletion-request")
async def cancel_deletion(workspace_id: str, user=Depends(authenticated_user)) -> dict:
    return cancel_workspace_deletion(workspace_id, user.id)
