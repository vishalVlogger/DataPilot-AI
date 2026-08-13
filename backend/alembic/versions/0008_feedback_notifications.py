"""Feedback resolution timestamps and user notifications."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "resolved_at" not in _columns("feedback"):
        op.add_column("feedback", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    if "notifications" not in _tables():
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(50), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("message", sa.String(500), nullable=False),
            sa.Column("resource_type", sa.String(40), nullable=True),
            sa.Column("resource_id", sa.String(36), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("user_id", "workspace_id", "type", "resource_id", "read_at", "created_at"):
            op.create_index(f"ix_notifications_{column}", "notifications", [column], unique=False)


def downgrade() -> None:
    if "notifications" in _tables():
        op.drop_table("notifications")
    if "resolved_at" in _columns("feedback"):
        op.drop_column("feedback", "resolved_at")
