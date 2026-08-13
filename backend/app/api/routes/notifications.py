from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.auth import Principal, require_auth
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import Notification
from app.services.admin_metrics import model_dict

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(limit: int = Query(20, ge=1, le=100), unread_only: bool = False, principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        scope = (Notification.user_id == principal.user_id, Notification.workspace_id == principal.workspace_id)
        query = select(Notification).where(*scope)
        if unread_only: query = query.where(Notification.read_at.is_(None))
        items = [model_dict(item) for item in session.scalars(query.order_by(Notification.created_at.desc()).limit(limit)).all()]
        unread_count = int(session.scalar(select(func.count()).select_from(Notification).where(*scope, Notification.read_at.is_(None))) or 0)
        return {"items": items, "unread_count": unread_count}


@router.patch("/{notification_id}/read")
async def read_notification(notification_id: str, principal: Principal = Depends(require_auth)) -> dict:
    with session_scope() as session:
        item = session.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == principal.user_id, Notification.workspace_id == principal.workspace_id))
        if item is None: raise AppError("Notification not found.", "NOTIFICATION_NOT_FOUND", 404)
        if item.read_at is None: item.read_at = datetime.now(timezone.utc); session.commit()
        return {"id": item.id, "read_at": item.read_at}
