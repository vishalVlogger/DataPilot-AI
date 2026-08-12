from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.core.auth import authenticated_user
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.core.rate_limit import rate_limiter
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_one_time_token, hash_password, hash_refresh_token, new_one_time_token, new_refresh_token, normalize_email, verify_password
from app.models import User, Workspace
from app.repositories import AccountTokenRepository, InvitationRepository, RefreshSessionRepository, UserRepository, WorkspaceRepository
from app.schemas.saas import AuthResponse, BetaAcknowledgementRequest, CurrentUserResponse, EmailRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, TokenRequest, UserResponse, UserUpdateRequest, WorkspaceResponse
from app.services.email import send_transactional_email

router = APIRouter(prefix="/auth", tags=["authentication"])


class AccountDeletionRequest(BaseModel):
    password: str


async def _send_account_token(user: User, purpose: str) -> tuple[str, str | None]:
    settings = get_settings(); token, token_hash = new_one_time_token()
    duration = timedelta(hours=settings.email_verification_expire_hours) if purpose == "verify_email" else timedelta(minutes=settings.password_reset_expire_minutes)
    with session_scope() as session: AccountTokenRepository(session).create(user.id, purpose, token_hash, datetime.now(timezone.utc) + duration)
    route = "verify-email" if purpose == "verify_email" else "reset-password"
    label = "Verify your DataPilot email" if purpose == "verify_email" else "Reset your DataPilot password"
    link = f"{settings.frontend_url}/{route}?token={token}"
    delivery = await send_transactional_email(user.email, label, f"{label}: {link}\nThis one-time link expires soon.", purpose)
    development_link = link if purpose == "verify_email" and settings.expose_development_email_links else None
    return delivery.status, development_link


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings(); response.set_cookie(settings.refresh_cookie_name, token, max_age=settings.refresh_token_expire_days * 86400, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/api/auth")


def _issue(user, response: Response, request: Request) -> AuthResponse:
    settings = get_settings(); access, expires_in = create_access_token(user.id); refresh, token_hash = new_refresh_token()
    with session_scope() as session:
        RefreshSessionRepository(session).create(user.id, token_hash, datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days), request.headers.get("user-agent"))
        workspaces = WorkspaceRepository(session).list_for_user(user.id)
    _set_refresh_cookie(response, refresh)
    return AuthResponse(access_token=access, expires_in=expires_in, user=UserResponse.model_validate(user, from_attributes=True), workspaces=[WorkspaceResponse.model_validate(item) for item in workspaces])


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(payload: RegisterRequest, request: Request, response: Response) -> AuthResponse:
    rate_limiter.check(f"register:{request.client.host if request.client else 'unknown'}", 5, 300); normalized = normalize_email(str(payload.email))
    settings = get_settings()
    if not settings.beta_registration_enabled: raise AppError("Registration is currently closed.", "REGISTRATION_DISABLED", 403)
    with session_scope() as session:
        users = UserRepository(session)
        if users.by_email(normalized): raise AppError("An account with this email already exists.", "AUTH_EMAIL_EXISTS", 409)
        if settings.beta_max_users is not None and int(session.scalar(select(func.count()).select_from(User)) or 0) >= settings.beta_max_users: raise AppError("The beta user limit has been reached.", "BETA_USER_LIMIT_REACHED", 403)
        if settings.registration_mode == "invite_only":
            if not payload.invitation_token: raise AppError("A valid invitation is required.", "INVITATION_REQUIRED", 403)
            InvitationRepository(session).validate_for_registration(hash_one_time_token(payload.invitation_token), normalized)
        user = users.create(str(payload.email), normalized, hash_password(payload.password), payload.display_name.strip())
        if payload.beta_acknowledged: users.acknowledge_beta(user)
        WorkspaceRepository(session).create(user.id, f"{user.display_name}'s Workspace", get_settings().default_plan)
    delivery_status, development_link = await _send_account_token(user, "verify_email")
    issued = _issue(user, response, request); issued.email_delivery_status = delivery_status; issued.development_verification_url = development_link
    return issued


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthResponse:
    rate_limiter.check(f"login:{request.client.host if request.client else 'unknown'}", 10, 300)
    with session_scope() as session:
        users = UserRepository(session); user = users.by_email(normalize_email(str(payload.email)))
        if user is None or not user.is_active or not verify_password(user.password_hash, payload.password): raise AppError("Invalid email or password.", "AUTH_INVALID_CREDENTIALS", 401)
        users.touch_login(user)
    return _issue(user, response, request)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(request: Request, response: Response) -> AuthResponse:
    token = request.cookies.get(get_settings().refresh_cookie_name)
    if not token: raise AppError("Authentication is required.", "AUTH_REFRESH_INVALID", 401)
    with session_scope() as session:
        repository = RefreshSessionRepository(session); item = repository.active(hash_refresh_token(token))
        if item is None: raise AppError("Authentication is required.", "AUTH_REFRESH_INVALID", 401)
        user = UserRepository(session).get(item.user_id)
        if not user.is_active: raise AppError("Authentication is required.", "ACCOUNT_DISABLED", 403)
        repository.revoke(item)
    return _issue(user, response, request)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(get_settings().refresh_cookie_name)
    if token:
        with session_scope() as session: RefreshSessionRepository(session).revoke_hash(hash_refresh_token(token))
    response.delete_cookie(get_settings().refresh_cookie_name, path="/api/auth")


@router.get("/me", response_model=CurrentUserResponse)
async def me(user=Depends(authenticated_user)) -> CurrentUserResponse:
    with session_scope() as session: workspaces = WorkspaceRepository(session).list_for_user(user.id)
    return CurrentUserResponse(user=UserResponse.model_validate(user, from_attributes=True), workspaces=[WorkspaceResponse.model_validate(item) for item in workspaces])


@router.patch("/me", response_model=UserResponse)
async def update_me(payload: UserUpdateRequest, user=Depends(authenticated_user)) -> UserResponse:
    with session_scope() as session: updated = UserRepository(session).update_name(UserRepository(session).get(user.id), payload.display_name.strip())
    return UserResponse.model_validate(updated, from_attributes=True)


@router.post("/verify-email")
async def verify_email(payload: TokenRequest) -> dict[str, str]:
    with session_scope() as session:
        token = AccountTokenRepository(session).consume(hash_one_time_token(payload.token), "verify_email")
        UserRepository(session).verify_email(UserRepository(session).get(token.user_id))
    return {"message": "Email verified successfully."}


@router.post("/resend-verification")
async def resend_verification(request: Request, user=Depends(authenticated_user)) -> dict[str, str | None]:
    rate_limiter.check(f"verify-resend:user:{user.id}", 3, 3600); rate_limiter.check(f"verify-resend:ip:{request.client.host if request.client else 'unknown'}", 10, 3600)
    if user.email_verified_at is not None: return {"message": "Your email is already verified.", "delivery_status": None, "development_verification_url": None}
    delivery_status, development_link = await _send_account_token(user, "verify_email")
    return {"message": "Verification email requested.", "delivery_status": delivery_status, "development_verification_url": development_link}


@router.post("/forgot-password")
async def forgot_password(payload: EmailRequest, request: Request) -> dict[str, str]:
    normalized = normalize_email(str(payload.email)); host = request.client.host if request.client else "unknown"
    rate_limiter.check(f"password-reset:ip:{host}", 10, 3600); rate_limiter.check(f"password-reset:email:{hash_one_time_token(normalized)}", 3, 3600)
    with session_scope() as session: user = UserRepository(session).by_email(normalized)
    if user and user.is_active: await _send_account_token(user, "reset_password")
    return {"message": "If an account exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest) -> dict[str, str]:
    with session_scope() as session:
        item = AccountTokenRepository(session).consume(hash_one_time_token(payload.token), "reset_password")
        user = UserRepository(session).get(item.user_id); UserRepository(session).update_password(user, hash_password(payload.new_password)); RefreshSessionRepository(session).revoke_all(user.id)
    return {"message": "Password reset successfully. Please sign in again."}


@router.post("/acknowledge-beta", response_model=UserResponse)
async def acknowledge_beta(payload: BetaAcknowledgementRequest, user=Depends(authenticated_user)) -> UserResponse:
    if not payload.acknowledged: raise AppError("Beta acknowledgement is required.", "BETA_ACKNOWLEDGEMENT_REQUIRED", 400)
    with session_scope() as session: updated = UserRepository(session).acknowledge_beta(UserRepository(session).get(user.id))
    return UserResponse.model_validate(updated, from_attributes=True)


@router.post("/deletion-request", status_code=202)
async def request_account_deletion(payload: AccountDeletionRequest, user=Depends(authenticated_user)) -> dict:
    with session_scope() as session:
        current = UserRepository(session).get(user.id)
        if not verify_password(current.password_hash, payload.password): raise AppError("Password confirmation is invalid.", "PASSWORD_CONFIRMATION_INVALID", 403)
        owned = session.scalars(select(Workspace).where(Workspace.owner_user_id == user.id, Workspace.deletion_scheduled_for.is_(None))).all()
        if owned: raise AppError("Transfer ownership or schedule deletion for owned workspaces first.", "OWNED_WORKSPACES_REMAIN", 409)
        current.deletion_requested_at = datetime.now(timezone.utc); current.is_active = False; RefreshSessionRepository(session).revoke_all(user.id)
        return {"status": "scheduled", "requested_at": current.deletion_requested_at}
