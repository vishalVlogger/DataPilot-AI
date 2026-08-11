"""Beta readiness account, collaboration, feedback, and job metadata."""
import sqlalchemy as sa
from alembic import op

from app.models import AccountToken, Feedback, WorkspaceInvitation

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for model in (AccountToken, WorkspaceInvitation, Feedback):
        model.__table__.create(bind, checkfirst=True)
    additions = {
        "users": [
            sa.Column("is_system_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("beta_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        ],
        "workspaces": [sa.Column("external_ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true())],
        "jobs": [
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("last_error", sa.String(500), nullable=True),
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payload", sa.JSON(), nullable=True),
        ],
    }
    for table, columns in additions.items():
        existing = _columns(bind, table)
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    for table in (AccountToken.__table__, WorkspaceInvitation.__table__, Feedback.__table__):
        for index in table.indexes:
            index.create(bind, checkfirst=True)


def downgrade() -> None:
    pass
