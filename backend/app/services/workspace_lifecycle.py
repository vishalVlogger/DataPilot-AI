from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import ActivityLog, Dataset, SavedAnalysis, UsageEvent, User, Workspace, WorkspaceMember
from app.services.object_storage import get_object_storage


def _json(items) -> bytes:
    def value(item): return {column.name: getattr(item, column.name) for column in item.__table__.columns}
    return json.dumps([value(item) for item in items], default=str, indent=2).encode()


def build_workspace_export(workspace_id: str, include_raw: bool = False) -> bytes:
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id)
        if not workspace: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        datasets = session.scalars(select(Dataset).where(Dataset.workspace_id == workspace_id)).all()
        members = session.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)).all()
        analyses = session.scalars(select(SavedAnalysis).where(SavedAnalysis.workspace_id == workspace_id)).all()
        activity = session.scalars(select(ActivityLog).where(ActivityLog.workspace_id == workspace_id).order_by(ActivityLog.created_at.desc()).limit(10000)).all()
        usage = session.scalars(select(UsageEvent).where(UsageEvent.workspace_id == workspace_id).order_by(UsageEvent.created_at.desc()).limit(10000)).all()
        workspace_safe = {"id": workspace.id, "name": workspace.name, "slug": workspace.slug, "plan_code": workspace.plan_code, "created_at": workspace.created_at}
    output = io.BytesIO(); manifest = {"format": 1, "workspace_id": workspace_id, "created_at": datetime.now(timezone.utc).isoformat(), "app_version": get_settings().app_version, "includes_raw_datasets": include_raw, "dataset_count": len(datasets)}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2)); archive.writestr("workspace.json", json.dumps(workspace_safe, default=str, indent=2))
        archive.writestr("datasets.json", _json(datasets)); archive.writestr("members.json", _json(members)); archive.writestr("saved_analyses.json", _json(analyses)); archive.writestr("activity.json", _json(activity)); archive.writestr("usage.json", _json(usage))
        if include_raw:
            objects = get_object_storage()
            for dataset in datasets:
                if objects.exists(dataset.storage_key): archive.writestr(f"datasets/{dataset.id}/current.parquet", objects.get(dataset.storage_key))
    return output.getvalue()


def schedule_workspace_deletion(workspace_id: str, owner_user_id: str, confirmation: str) -> dict:
    now = datetime.now(timezone.utc); scheduled = now + timedelta(days=get_settings().deletion_grace_days)
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id)
        if not workspace or workspace.owner_user_id != owner_user_id: raise AppError("Workspace owner access is required.", "WORKSPACE_OWNER_REQUIRED", 403)
        if confirmation != workspace.name: raise AppError("Type the exact workspace name to confirm deletion.", "DELETION_CONFIRMATION_INVALID", 400)
        workspace.deletion_requested_at = now; workspace.deletion_scheduled_for = scheduled; session.commit()
        return {"workspace_id": workspace.id, "deletion_requested_at": now, "deletion_scheduled_for": scheduled, "mode": "read_only"}


def cancel_workspace_deletion(workspace_id: str, owner_user_id: str) -> dict:
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id)
        if not workspace or workspace.owner_user_id != owner_user_id: raise AppError("Workspace owner access is required.", "WORKSPACE_OWNER_REQUIRED", 403)
        workspace.deletion_requested_at = None; workspace.deletion_scheduled_for = None; session.commit(); return {"workspace_id": workspace.id, "cancelled": True}


def ensure_workspace_writable(workspace_id: str) -> None:
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id)
        if workspace and workspace.deletion_scheduled_for: raise AppError("This workspace is read-only while deletion is scheduled.", "WORKSPACE_DELETION_PENDING", 409)


def process_due_deletions(now: datetime | None = None) -> dict[str, int]:
    """Permanently remove due workspaces and owner-free accounts after the grace period."""
    now = now or datetime.now(timezone.utc); objects = get_object_storage(); deleted_workspaces = deleted_accounts = 0
    with session_scope() as session:
        due = session.scalars(select(Workspace).where(Workspace.deletion_scheduled_for.is_not(None), Workspace.deletion_scheduled_for <= now)).all()
        for workspace in due:
            prefix = f"workspaces/{workspace.id}"
            for key in list(objects.list(prefix)): objects.delete(key)
            session.delete(workspace); deleted_workspaces += 1
        session.flush()
        account_cutoff = now - timedelta(days=get_settings().deletion_grace_days)
        users = session.scalars(select(User).where(User.deletion_requested_at.is_not(None), User.deletion_requested_at <= account_cutoff)).all()
        for user in users:
            owns_workspace = session.scalar(select(Workspace.id).where(Workspace.owner_user_id == user.id).limit(1))
            if owns_workspace is None:
                session.delete(user); deleted_accounts += 1
        session.commit()
    return {"workspaces_deleted": deleted_workspaces, "accounts_deleted": deleted_accounts}
