from fastapi import APIRouter

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.operations import infrastructure_status

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "DataPilot AI", "version": get_settings().app_version}


@router.get("/ready")
async def readiness() -> dict:
    status = infrastructure_status(); settings = get_settings(); storage_ok = isinstance(status["storage"], dict) and status["storage"].get("status") == "ok"
    redis_required = settings.rate_limit_backend == "redis" or settings.job_execution_mode == "redis"
    if status["database"] != "ok" or not storage_ok or (redis_required and status["redis"] != "ok"):
        raise AppError("A required service is unavailable.", "SERVICE_NOT_READY", 503)
    return {"status": "ready", **status}
