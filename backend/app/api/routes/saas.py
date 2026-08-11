from fastapi import APIRouter, Depends, Query

from app.core.auth import Principal, require_auth
from app.core.database import session_scope
from app.repositories import ActivityRepository, DatasetRepository
from app.schemas.saas import ActivityResponse, DashboardResponse, UsageSummaryResponse
from app.services.saas import UsageService

router = APIRouter(tags=["saas"])


@router.get("/usage", response_model=UsageSummaryResponse)
async def usage(principal: Principal = Depends(require_auth)) -> UsageSummaryResponse:
    return UsageSummaryResponse.model_validate(UsageService(principal.workspace_id).summary())


@router.get("/activity", response_model=list[ActivityResponse])
async def activity(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), principal: Principal = Depends(require_auth)) -> list[ActivityResponse]:
    with session_scope() as session: items = ActivityRepository(session, principal.workspace_id).list(limit, offset)
    return [ActivityResponse.model_validate(item) for item in items]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(principal: Principal = Depends(require_auth)) -> DashboardResponse:
    with session_scope() as session:
        datasets = DatasetRepository(session, principal.workspace_id).list(limit=5)
        activities = ActivityRepository(session, principal.workspace_id).list(limit=8)
    recent = [{"id": item["id"], "name": item["name"], "rows": item["row_count"], "columns": item["column_count"], "created_at": item["created_at"], "last_analyzed_at": item["last_analyzed_at"], "storage_bytes": item["storage_bytes"]} for item in datasets]
    return DashboardResponse(usage=UsageService(principal.workspace_id).summary(), recent_datasets=recent, recent_activity=[ActivityResponse.model_validate(item) for item in activities])
