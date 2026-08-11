from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import authenticated_user
from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password, hash_refresh_token, new_refresh_token, normalize_email, verify_password
from app.repositories import RefreshSessionRepository, UserRepository, WorkspaceRepository
from app.schemas.saas import AuthResponse, CurrentUserResponse, LoginRequest, RegisterRequest, UserResponse, UserUpdateRequest, WorkspaceResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


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
    with session_scope() as session:
        users = UserRepository(session)
        if users.by_email(normalized): raise AppError("An account with this email already exists.", "AUTH_EMAIL_EXISTS", 409)
        user = users.create(str(payload.email), normalized, hash_password(payload.password), payload.display_name.strip())
        WorkspaceRepository(session).create(user.id, f"{user.display_name}'s Workspace", get_settings().default_plan)
    return _issue(user, response, request)


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
