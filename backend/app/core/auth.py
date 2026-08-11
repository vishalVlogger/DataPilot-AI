from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import session_scope
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.repositories import UserRepository, WorkspaceRepository

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str


_principal: ContextVar[Principal | None] = ContextVar("principal", default=None)


def current_principal() -> Principal:
    value = _principal.get()
    if value is None: raise AppError("Authentication is required.", "AUTH_REQUIRED", 401)
    return value


async def authenticated_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None or credentials.scheme.casefold() != "bearer": raise AppError("Authentication is required.", "AUTH_REQUIRED", 401)
    payload = decode_access_token(credentials.credentials)
    with session_scope() as session:
        user = UserRepository(session).get(payload["sub"])
        if not user.is_active: raise AppError("Authentication is required.", "ACCOUNT_DISABLED", 403)
        return user


async def require_system_admin(user=Depends(authenticated_user)):
    if not user.is_system_admin: raise AppError("System administrator access is required.", "SYSTEM_ADMIN_REQUIRED", 403)
    return user


async def require_auth(request: Request, user=Depends(authenticated_user), x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID")) -> Principal:
    with session_scope() as session:
        workspaces = WorkspaceRepository(session)
        accessible = workspaces.list_for_user(user.id)
        if not accessible: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        selected = workspaces.get_for_user(x_workspace_id, user.id) if x_workspace_id else accessible[0]
    principal = Principal(user_id=user.id, workspace_id=selected["id"], role=selected["role"]); _principal.set(principal); request.state.user_id = user.id; request.state.workspace_id = selected["id"]; return principal
