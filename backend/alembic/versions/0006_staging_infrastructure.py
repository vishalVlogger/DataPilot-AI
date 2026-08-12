"""Durable infrastructure metadata and deletion scheduling."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "deletion_requested_at" not in _columns("users"):
        op.add_column("users", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
    workspace_columns = _columns("workspaces")
    if "deletion_requested_at" not in workspace_columns: op.add_column("workspaces", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
    if "deletion_scheduled_for" not in workspace_columns: op.add_column("workspaces", sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True))
    if "ix_workspaces_deletion_scheduled_for" not in _indexes("workspaces"): op.create_index("ix_workspaces_deletion_scheduled_for", "workspaces", ["deletion_scheduled_for"])
    if "checksum_sha256" not in _columns("dataset_versions"): op.add_column("dataset_versions", sa.Column("checksum_sha256", sa.String(64), nullable=True))
    job_columns = _columns("jobs")
    if "idempotency_key" not in job_columns: op.add_column("jobs", sa.Column("idempotency_key", sa.String(64), nullable=True))
    if "next_attempt_at" not in job_columns: op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    job_indexes = _indexes("jobs")
    if "ix_jobs_idempotency_key" not in job_indexes: op.create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"])
    if "ix_jobs_next_attempt_at" not in job_indexes: op.create_index("ix_jobs_next_attempt_at", "jobs", ["next_attempt_at"])


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_next_attempt_at"); batch.drop_index("ix_jobs_idempotency_key")
        batch.drop_column("next_attempt_at"); batch.drop_column("idempotency_key")
    with op.batch_alter_table("dataset_versions") as batch: batch.drop_column("checksum_sha256")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_index("ix_workspaces_deletion_scheduled_for")
        batch.drop_column("deletion_scheduled_for"); batch.drop_column("deletion_requested_at")
    with op.batch_alter_table("users") as batch: batch.drop_column("deletion_requested_at")
