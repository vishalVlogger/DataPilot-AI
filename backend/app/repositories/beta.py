from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AccountToken, ActivityLog, Dataset, Feedback, Job, UsageEvent, User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.repositories.saas import model_dict


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AccountTokenRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, user_id: str, purpose: str, token_hash: str, expires_at: datetime) -> AccountToken:
        now = datetime.now(timezone.utc)
        for item in self.session.scalars(select(AccountToken).where(AccountToken.user_id == user_id, AccountToken.purpose == purpose, AccountToken.used_at.is_(None))).all(): item.used_at = now
        token = AccountToken(user_id=user_id, purpose=purpose, token_hash=token_hash, expires_at=expires_at); self.session.add(token); self.session.commit(); return token
    def consume(self, token_hash: str, purpose: str) -> AccountToken:
        item = self.session.scalar(select(AccountToken).where(AccountToken.token_hash == token_hash, AccountToken.purpose == purpose, AccountToken.used_at.is_(None)))
        if item is None or _aware(item.expires_at) <= datetime.now(timezone.utc): raise AppError("This link is invalid or has expired.", "ACCOUNT_TOKEN_INVALID", 400)
        item.used_at = datetime.now(timezone.utc); self.session.commit(); return item


class InvitationRepository:
    def __init__(self, session: Session, workspace_id: str | None = None) -> None: self.session = session; self.workspace_id = workspace_id
    def create(self, email: str, normalized_email: str, role: str, token_hash: str, invited_by: str, expires_at: datetime) -> WorkspaceInvitation:
        if not self.workspace_id: raise AppError("Workspace not found.", "WORKSPACE_NOT_FOUND", 404)
        existing_member = self.session.scalar(select(WorkspaceMember).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == self.workspace_id, User.normalized_email == normalized_email))
        if existing_member: raise AppError("This user is already a workspace member.", "WORKSPACE_MEMBER_EXISTS", 409)
        active = self.session.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == self.workspace_id, WorkspaceInvitation.normalized_email == normalized_email, WorkspaceInvitation.accepted_at.is_(None), WorkspaceInvitation.revoked_at.is_(None), WorkspaceInvitation.expires_at > datetime.now(timezone.utc)))
        if active: raise AppError("An active invitation already exists.", "INVITATION_EXISTS", 409)
        item = WorkspaceInvitation(workspace_id=self.workspace_id, email=email, normalized_email=normalized_email, role=role, token_hash=token_hash, invited_by_user_id=invited_by, expires_at=expires_at); self.session.add(item); self.session.commit(); return item
    def list(self) -> list[dict[str, Any]]:
        items = self.session.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == self.workspace_id).order_by(WorkspaceInvitation.created_at.desc())).all()
        return [model_dict(item) for item in items]
    def by_token(self, token_hash: str) -> WorkspaceInvitation:
        item = self.session.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == token_hash))
        if item is None or item.revoked_at is not None or item.accepted_at is not None or _aware(item.expires_at) <= datetime.now(timezone.utc): raise AppError("This invitation is invalid or has expired.", "INVITATION_INVALID", 400)
        return item
    def validate_for_registration(self, token_hash: str, normalized_email: str) -> WorkspaceInvitation:
        item = self.by_token(token_hash)
        if item.normalized_email != normalized_email: raise AppError("This invitation does not match the registration email.", "INVITATION_EMAIL_MISMATCH", 403)
        return item
    def accept(self, token_hash: str, user: User) -> dict[str, Any]:
        item = self.by_token(token_hash)
        if item.normalized_email != user.normalized_email: raise AppError("This invitation belongs to another email address.", "INVITATION_EMAIL_MISMATCH", 403)
        member = self.session.get(WorkspaceMember, (item.workspace_id, user.id))
        if member is None: self.session.add(WorkspaceMember(workspace_id=item.workspace_id, user_id=user.id, role=item.role))
        item.accepted_at = datetime.now(timezone.utc); self.session.commit()
        return model_dict(item)
    def revoke(self, invitation_id: str) -> None:
        item = self.session.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.id == invitation_id, WorkspaceInvitation.workspace_id == self.workspace_id))
        if item is None: raise AppError("Invitation not found.", "INVITATION_NOT_FOUND", 404)
        if item.accepted_at is not None: raise AppError("Accepted invitations cannot be revoked.", "INVITATION_ALREADY_ACCEPTED", 409)
        item.revoked_at = datetime.now(timezone.utc); self.session.commit()


class MemberRepository:
    def __init__(self, session: Session, workspace_id: str) -> None: self.session = session; self.workspace_id = workspace_id
    def list(self) -> list[dict[str, Any]]:
        rows = self.session.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == self.workspace_id).order_by(WorkspaceMember.joined_at)).all()
        return [{"user_id": member.user_id, "email": user.email, "display_name": user.display_name, "role": member.role, "joined_at": member.joined_at} for member, user in rows]
    def change_role(self, user_id: str, role: str) -> dict[str, Any]:
        item = self.session.get(WorkspaceMember, (self.workspace_id, user_id))
        if item is None: raise AppError("Workspace member not found.", "WORKSPACE_MEMBER_NOT_FOUND", 404)
        if item.role == "owner": raise AppError("The workspace owner role cannot be changed.", "WORKSPACE_OWNER_PROTECTED", 409)
        item.role = role; self.session.commit(); return next(row for row in self.list() if row["user_id"] == user_id)
    def remove(self, user_id: str) -> None:
        item = self.session.get(WorkspaceMember, (self.workspace_id, user_id))
        if item is None: raise AppError("Workspace member not found.", "WORKSPACE_MEMBER_NOT_FOUND", 404)
        if item.role == "owner": raise AppError("The workspace owner cannot be removed.", "WORKSPACE_OWNER_PROTECTED", 409)
        self.session.delete(item); self.session.commit()


class FeedbackRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def create(self, **values: Any) -> dict[str, Any]:
        dataset_id, workspace_id = values.get("dataset_id"), values["workspace_id"]
        if dataset_id and not self.session.scalar(select(Dataset.id).where(Dataset.id == dataset_id, Dataset.workspace_id == workspace_id)):
            raise AppError("Dataset not found.", "DATASET_NOT_FOUND", 404)
        item = Feedback(**values); self.session.add(item); self.session.commit(); return model_dict(item)
    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        return [model_dict(item) for item in self.session.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(limit)).all()]


class AdminRepository:
    def __init__(self, session: Session) -> None: self.session = session
    def summary(self) -> dict[str, Any]:
        since = datetime.now(timezone.utc).timestamp() - 86400
        cutoff = datetime.fromtimestamp(since, timezone.utc)
        return {
            "users": int(self.session.scalar(select(func.count()).select_from(User)) or 0),
            "verified_users": int(self.session.scalar(select(func.count()).select_from(User).where(User.email_verified_at.is_not(None))) or 0),
            "workspaces": int(self.session.scalar(select(func.count()).select_from(Workspace)) or 0),
            "datasets": int(self.session.scalar(select(func.count()).select_from(Dataset)) or 0),
            "failed_jobs_24h": int(self.session.scalar(select(func.count()).select_from(Job).where(Job.status == "failed", Job.completed_at >= cutoff)) or 0),
            "feedback": int(self.session.scalar(select(func.count()).select_from(Feedback)) or 0),
            "storage_bytes": int(self.session.scalar(select(func.coalesce(func.sum(Dataset.storage_bytes), 0))) or 0),
        }
    def support_lookup(self, query: str) -> list[dict[str, Any]]:
        pattern = f"%{query.casefold()}%"
        users = self.session.scalars(select(User).where(User.normalized_email.like(pattern)).limit(20)).all()
        workspaces = self.session.scalars(select(Workspace).where(func.lower(Workspace.name).like(pattern)).limit(20)).all()
        datasets = self.session.scalars(select(Dataset).where(Dataset.id == query).limit(1)).all()
        results = []
        for item in users:
            memberships = self.session.execute(select(WorkspaceMember, Workspace).join(Workspace, Workspace.id == WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == item.id)).all()
            results.append({"type": "user", "id": item.id, "email": item.email, "active": item.is_active, "verified": item.email_verified_at is not None, "last_login_at": item.last_login_at, "last_activity_at": self.session.scalar(select(func.max(ActivityLog.created_at)).where(ActivityLog.user_id == item.id)), "usage_events": int(self.session.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.user_id == item.id)) or 0), "memberships": [{"workspace_id": member.workspace_id, "workspace_name": workspace.name, "role": member.role, "plan": workspace.plan_code} for member, workspace in memberships]})
        for item in workspaces:
            results.append({"type": "workspace", "id": item.id, "name": item.name, "plan": item.plan_code, "owner_user_id": item.owner_user_id, "members": int(self.session.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == item.id)) or 0), "datasets": int(self.session.scalar(select(func.count()).select_from(Dataset).where(Dataset.workspace_id == item.id)) or 0), "usage_events": int(self.session.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.workspace_id == item.id)) or 0), "last_activity_at": self.session.scalar(select(func.max(ActivityLog.created_at)).where(ActivityLog.workspace_id == item.id))})
        results += [{"type": "dataset", "id": item.id, "name": item.name, "workspace_id": item.workspace_id, "status": item.status, "rows": item.row_count} for item in datasets]
        return results
