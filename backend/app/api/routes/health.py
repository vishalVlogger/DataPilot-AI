from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "DataPilot AI"}


@router.get("/ready")
async def readiness() -> dict[str, str]:
    try:
        with session_scope() as session: session.execute(text("SELECT 1"))
        root: Path = get_settings().storage_root.resolve(); root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir(): raise OSError("storage root is not a directory")
    except Exception as exc:
        raise AppError("A required service is unavailable.", "SERVICE_NOT_READY", 503) from exc
    return {"status": "ready", "database": "ok", "storage": "ok"}
