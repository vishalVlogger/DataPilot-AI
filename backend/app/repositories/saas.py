import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import ActivityLog, Dataset, RefreshSession, UsageEvent, User, Workspace, WorkspaceMember


def model_dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def slugify(value: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "workspace")[:100]


class UserRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def get(self, user_id: str) -> User:
        user = self.session.get(User, user_id)
        if user is None: raise AppError("Authentication is required.", "AUTH_REQUIRED", 401)
        return user
    def by_email(self, normalized_email: str) -> User | None:
        return self.session.scalar(select(User).where(User.normalized_email == normalized_email))
    def create(self, email: str, normalized_email: str, password_hash: str, display_name: str) -> User:
        user = User(email=email, normalized_email=normalized_email, password_hash=password_hash, display_name=display_name); self.session.add(user); self.session.commit(); return user
    def touch_login(self, user: User) -> None:
        user.last_login_at = datetime.now(timezone.utc); self.session.commit()
    def update_name(self, user: User, display_name: str) -> User:
        user.display_name = display_name; self.session.commit(); return user


class WorkspaceRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, owner_user_id: str, name: str, plan_code: str, slug: str | None = None) -> dict[str, Any]:
        base = slugify(slug or name); candidate = base
        while self.session.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
            candidate = f"{base[:91]}-{str(uuid4())[:8]}"
        workspace = Workspace(name=name, slug=candidate, owner_user_id=owner_user_id, plan_code=plan_code); self.session.add(workspace); self.session.flush(); self.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner_user_id, role="owner")); self.session.commit()
        return {**model_dict(workspace), "role": "owner"}
    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.session.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id).order_by(Workspace.created_at)).all()
        return [{**model_dict(workspace), "role": role} for workspace, role in rows]
    def get_for_user(self, workspace_id: str, user_id: str) -> dict[str, Any]:
        row = self.session.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id).where(Workspace.id == workspace_id, WorkspaceMember.user_id == user_id)).first()
        if row is None: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        return {**model_dict(row[0]), "role": row[1]}
    def update(self, workspace_id: str, user_id: str, **values: Any) -> dict[str, Any]:
        record = self.get_for_user(workspace_id, user_id)
        if record["role"] not in {"owner", "admin"}: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        workspace = self.session.get(Workspace, workspace_id)
        if values.get("slug") and self.session.scalar(select(Workspace.id).where(Workspace.slug == values["slug"], Workspace.id != workspace_id)):
            raise AppError("That workspace slug is unavailable.", "WORKSPACE_SLUG_EXISTS", 409)
        for key, value in values.items():
            if value is not None: setattr(workspace, key, value)
        self.session.commit(); return {**model_dict(workspace), "role": record["role"]}


class RefreshSessionRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, user_id: str, token_hash: str, expires_at: datetime, user_agent: str | None) -> RefreshSession:
        item = RefreshSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at, user_agent=(user_agent or "")[:255]); self.session.add(item); self.session.commit(); return item
    def active(self, token_hash: str) -> RefreshSession | None:
        item = self.session.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash, RefreshSession.revoked_at.is_(None)))
        if item is None: return None
        expires = item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at
        return item if expires > datetime.now(timezone.utc) else None
    def revoke(self, item: RefreshSession) -> None:
        item.revoked_at = datetime.now(timezone.utc); self.session.commit()
    def revoke_hash(self, token_hash: str) -> None:
        item = self.session.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash, RefreshSession.revoked_at.is_(None)))
        if item: self.revoke(item)


class UsageRepository:
    def __init__(self, session: Session, workspace_id: str) -> None: self.session = session; self.workspace_id = workspace_id
    def record(self, event_type: str, quantity: int = 1, user_id: str | None = None, resource_id: str | None = None, details: dict | None = None) -> None:
        self.session.add(UsageEvent(workspace_id=self.workspace_id, user_id=user_id, event_type=event_type, quantity=quantity, resource_id=resource_id, details=details)); self.session.commit()
    def total(self, event_type: str, since: datetime | None = None) -> int:
        query = select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(UsageEvent.workspace_id == self.workspace_id, UsageEvent.event_type == event_type)
        if since is not None: query = query.where(UsageEvent.created_at >= since)
        return int(self.session.scalar(query) or 0)
    def dataset_count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(Dataset).where(Dataset.workspace_id == self.workspace_id)) or 0)
    def storage_bytes(self) -> int:
        return int(self.session.scalar(select(func.coalesce(func.sum(Dataset.storage_bytes), 0)).where(Dataset.workspace_id == self.workspace_id)) or 0)


class ActivityRepository:
    def __init__(self, session: Session, workspace_id: str) -> None: self.session = session; self.workspace_id = workspace_id
    def record(self, activity_type: str, user_id: str | None = None, resource_id: str | None = None, details: dict | None = None) -> None:
        self.session.add(ActivityLog(workspace_id=self.workspace_id, user_id=user_id, activity_type=activity_type, resource_id=resource_id, details=details)); self.session.commit()
    def list(self, limit: int = 25, offset: int = 0) -> list[dict[str, Any]]:
        items = self.session.scalars(select(ActivityLog).where(ActivityLog.workspace_id == self.workspace_id).order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)).all()
        return [model_dict(item) for item in items]
