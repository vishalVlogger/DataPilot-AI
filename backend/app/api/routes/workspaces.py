from fastapi import APIRouter, Depends

from app.core.auth import Principal, authenticated_user, require_auth
from app.core.config import get_settings
from app.core.database import session_scope
from app.repositories import WorkspaceRepository
from app.schemas.saas import WorkspaceCreateRequest, WorkspaceResponse, WorkspaceUpdateRequest

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


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
    with session_scope() as session: item = WorkspaceRepository(session).update(workspace_id, user.id, **payload.model_dump(exclude_none=True))
    return WorkspaceResponse.model_validate(item)
