"""SaaS authentication, tenancy, usage, and activity metadata.

Revision 0001 used live model metadata. This migration is introspective so fresh
installs and legacy databases stamped at 0001 both upgrade safely.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings
from app.models import ActivityLog, Base, RefreshSession, UsageEvent, User, Workspace, WorkspaceMember

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_TABLES = {
    "datasets": ["workspace_id", "uploader_user_id", "storage_bytes"],
    "dataset_versions": ["workspace_id"],
    "analysis_sessions": ["workspace_id", "user_id"],
    "analysis_runs": ["workspace_id", "user_id"],
    "saved_analyses": ["workspace_id", "user_id"],
    "jobs": ["workspace_id", "user_id"],
}


def _columns(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for model in (User, Workspace, WorkspaceMember, RefreshSession, UsageEvent, ActivityLog):
        model.__table__.create(bind, checkfirst=True)

    for table, columns in TENANT_TABLES.items():
        existing = _columns(bind, table)
        with op.batch_alter_table(table) as batch:
            for name in columns:
                if name in existing:
                    continue
                if name == "workspace_id":
                    batch.add_column(sa.Column(name, sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE", name=f"fk_{table}_workspace_id"), nullable=True))
                elif name in {"user_id", "uploader_user_id"}:
                    batch.add_column(sa.Column(name, sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL", name=f"fk_{table}_{name}"), nullable=True))
                else:
                    batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))

    settings = get_settings(); now = datetime.now(timezone.utc)
    users = User.__table__; workspaces = Workspace.__table__; members = WorkspaceMember.__table__
    if bind.execute(sa.select(users.c.id).where(users.c.id == settings.legacy_user_id)).scalar() is None:
        bind.execute(users.insert().values(id=settings.legacy_user_id, email="legacy-local@datapilot.invalid", normalized_email="legacy-local@datapilot.invalid", password_hash="!", display_name="Legacy Local User", is_active=False, created_at=now, updated_at=now))
    if bind.execute(sa.select(workspaces.c.id).where(workspaces.c.id == settings.legacy_workspace_id)).scalar() is None:
        bind.execute(workspaces.insert().values(id=settings.legacy_workspace_id, name="Legacy Local Workspace", slug=f"legacy-local-{settings.legacy_workspace_id[-8:]}", owner_user_id=settings.legacy_user_id, plan_code=settings.default_plan, created_at=now, updated_at=now))
    if bind.execute(sa.select(members.c.workspace_id).where(members.c.workspace_id == settings.legacy_workspace_id, members.c.user_id == settings.legacy_user_id)).scalar() is None:
        bind.execute(members.insert().values(workspace_id=settings.legacy_workspace_id, user_id=settings.legacy_user_id, role="owner", joined_at=now))

    for table in TENANT_TABLES:
        bind.execute(sa.text(f"UPDATE {table} SET workspace_id = :workspace_id WHERE workspace_id IS NULL"), {"workspace_id": settings.legacy_workspace_id})
        column = next(item for item in sa.inspect(bind).get_columns(table) if item["name"] == "workspace_id")
        if column.get("nullable", True):
            with op.batch_alter_table(table) as batch: batch.alter_column("workspace_id", existing_type=sa.String(36), nullable=False)

    for table in Base.metadata.sorted_tables:
        for index in table.indexes: index.create(bind, checkfirst=True)


def downgrade() -> None:
    # Removing tenancy merges security boundaries; use a pre-migration backup.
    pass
