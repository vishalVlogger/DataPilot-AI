from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, or_

from app.core.config import get_settings
from app.core.database import session_scope
from app.models import AccountToken, ActivityLog, Job, RefreshSession, WorkspaceInvitation


class CleanupService:
    def run(self, now: datetime | None = None) -> dict[str, int]:
        settings = get_settings(); now = now or datetime.now(timezone.utc); counts: dict[str, int] = {}
        with session_scope() as session:
            statements = {
                "account_tokens": delete(AccountToken).where(AccountToken.expires_at < now),
                "expired_invitations": delete(WorkspaceInvitation).where(WorkspaceInvitation.expires_at < now, WorkspaceInvitation.accepted_at.is_(None)),
                "refresh_sessions": delete(RefreshSession).where(RefreshSession.revoked_at.is_not(None), RefreshSession.revoked_at < now - timedelta(days=settings.refresh_session_retention_days)),
                "jobs": delete(Job).where(Job.status.in_(["completed", "failed", "cancelled"]), Job.completed_at < now - timedelta(days=settings.job_retention_days)),
                "activity": delete(ActivityLog).where(ActivityLog.created_at < now - timedelta(days=settings.activity_retention_days)),
            }
            for name, statement in statements.items(): counts[name] = int(session.execute(statement).rowcount or 0)
            session.commit()
        counts["files"] = self._cleanup_files(settings.storage_root, now, settings.report_retention_days)
        return counts

    def _cleanup_files(self, root: Path, now: datetime, report_days: int) -> int:
        if not root.exists(): return 0
        removed = 0; report_cutoff = now.timestamp() - report_days * 86400; temp_cutoff = now.timestamp() - 86400
        for path in root.rglob("*"):
            if not path.is_file(): continue
            is_old_report = path.parent.name == "reports" and path.stat().st_mtime < report_cutoff
            is_stale_temp = path.suffix == ".tmp" and path.stat().st_mtime < temp_cutoff
            if is_old_report or is_stale_temp: path.unlink(); removed += 1
        return removed
