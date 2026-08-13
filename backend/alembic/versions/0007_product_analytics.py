"""Privacy-safe product analytics, onboarding, and beta feedback."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    user_columns = _columns("users")
    if "acquisition_source" not in user_columns: op.add_column("users", sa.Column("acquisition_source", sa.String(80), nullable=False, server_default="open_registration"))
    if "beta_status" not in user_columns: op.add_column("users", sa.Column("beta_status", sa.String(30), nullable=False, server_default="onboarding"))
    if "onboarding_dismissed_at" not in user_columns: op.add_column("users", sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True))
    if "ix_users_beta_status" not in _indexes("users"): op.create_index("ix_users_beta_status", "users", ["beta_status"], unique=False)
    if "is_sample" not in _columns("datasets"): op.add_column("datasets", sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()))
    feedback_columns = _columns("feedback")
    if "feature_area" not in feedback_columns: op.add_column("feedback", sa.Column("feature_area", sa.String(50), nullable=True))
    if "severity" not in feedback_columns: op.add_column("feedback", sa.Column("severity", sa.String(20), nullable=False, server_default="medium"))
    if "affected_flow" not in feedback_columns: op.add_column("feedback", sa.Column("affected_flow", sa.String(80), nullable=True))
    feedback_indexes = _indexes("feedback")
    if "ix_feedback_feature_area" not in feedback_indexes: op.create_index("ix_feedback_feature_area", "feedback", ["feature_area"], unique=False)
    if "ix_feedback_severity" not in feedback_indexes: op.create_index("ix_feedback_severity", "feedback", ["severity"], unique=False)

    if "product_events" not in _tables():
        op.create_table("product_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
            sa.Column("event_name", sa.String(80), nullable=False), sa.Column("feature_area", sa.String(50), nullable=True),
            sa.Column("resource_type", sa.String(40), nullable=True), sa.Column("resource_id", sa.String(36), nullable=True),
            sa.Column("properties", sa.JSON(), nullable=True), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False))
        for column in ("user_id", "workspace_id", "event_name", "feature_area", "resource_id", "occurred_at"):
            name = f"ix_product_events_{column}"
            if name not in _indexes("product_events"): op.create_index(name, "product_events", [column], unique=False)
    if "analysis_feedback" not in _tables():
        op.create_table("analysis_feedback",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("helpful", sa.Boolean(), nullable=False), sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("analysis_run_id", "user_id", name="uq_analysis_feedback_run_user"))
        for column in ("analysis_run_id", "workspace_id", "user_id", "created_at"):
            name = f"ix_analysis_feedback_{column}"
            if name not in _indexes("analysis_feedback"): op.create_index(name, "analysis_feedback", [column], unique=False)
    if "beta_user_notes" not in _tables():
        op.create_table("beta_user_notes",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        for column in ("user_id", "author_user_id", "created_at"):
            name = f"ix_beta_user_notes_{column}"
            if name not in _indexes("beta_user_notes"): op.create_index(name, "beta_user_notes", [column], unique=False)


def downgrade() -> None:
    op.drop_table("beta_user_notes"); op.drop_table("analysis_feedback"); op.drop_table("product_events")
    with op.batch_alter_table("feedback") as batch:
        batch.drop_index("ix_feedback_severity"); batch.drop_index("ix_feedback_feature_area")
        batch.drop_column("affected_flow"); batch.drop_column("severity"); batch.drop_column("feature_area")
    with op.batch_alter_table("datasets") as batch: batch.drop_column("is_sample")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_beta_status"); batch.drop_column("onboarding_dismissed_at"); batch.drop_column("beta_status"); batch.drop_column("acquisition_source")
