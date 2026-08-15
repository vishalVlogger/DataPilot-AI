"""Commercial plans, trials, subscriptions, requests, and idempotent metering."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _tables() -> set[str]: return set(sa.inspect(op.get_bind()).get_table_names())
def _columns(table: str) -> set[str]: return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
def _indexes(table: str) -> set[str]: return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    workspace_columns = _columns("workspaces")
    for name, column in (
        ("trial_started_at", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True)),
        ("trial_ends_at", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True)),
        ("trial_plan", sa.Column("trial_plan", sa.String(30), nullable=True)),
        ("trial_status", sa.Column("trial_status", sa.String(20), nullable=False, server_default="none")),
    ):
        if name not in workspace_columns: op.add_column("workspaces", column)
    for column in ("trial_ends_at", "trial_status"):
        name = f"ix_workspaces_{column}"
        if name not in _indexes("workspaces"): op.create_index(name, "workspaces", [column], unique=False)
    if "meter_key" not in _columns("usage_events"): op.add_column("usage_events", sa.Column("meter_key", sa.String(160), nullable=True))
    if "ix_usage_events_meter_key" not in _indexes("usage_events"): op.create_index("ix_usage_events_meter_key", "usage_events", ["meter_key"], unique=False)
    if "uq_usage_event_workspace_meter_key" not in _indexes("usage_events"): op.create_index("uq_usage_event_workspace_meter_key", "usage_events", ["workspace_id", "meter_key"], unique=True)
    if "subscriptions" not in _tables():
        op.create_table("subscriptions",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_code", sa.String(30), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("billing_provider", sa.String(30), nullable=False),
            sa.Column("provider_customer_id", sa.String(255), nullable=True), sa.Column("provider_subscription_id", sa.String(255), nullable=True),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True), sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workspace_id", name="uq_subscription_workspace"))
        for column in ("workspace_id", "plan_code", "status", "current_period_end"): op.create_index(f"ix_subscriptions_{column}", "subscriptions", [column], unique=False)
    if "upgrade_requests" not in _tables():
        op.create_table("upgrade_requests",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("requested_plan", sa.String(30), nullable=False),
            sa.Column("message", sa.String(1000), nullable=True), sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        for column in ("workspace_id", "user_id", "requested_plan", "status", "created_at"): op.create_index(f"ix_upgrade_requests_{column}", "upgrade_requests", [column], unique=False)


def downgrade() -> None:
    if "upgrade_requests" in _tables(): op.drop_table("upgrade_requests")
    if "subscriptions" in _tables(): op.drop_table("subscriptions")
    if "uq_usage_event_workspace_meter_key" in _indexes("usage_events"): op.drop_index("uq_usage_event_workspace_meter_key", table_name="usage_events")
    if "ix_usage_events_meter_key" in _indexes("usage_events"): op.drop_index("ix_usage_events_meter_key", table_name="usage_events")
    if "meter_key" in _columns("usage_events"): op.drop_column("usage_events", "meter_key")
    with op.batch_alter_table("workspaces") as batch:
        for index in ("ix_workspaces_trial_status", "ix_workspaces_trial_ends_at"):
            if index in _indexes("workspaces"): batch.drop_index(index)
        for column in ("trial_status", "trial_plan", "trial_ends_at", "trial_started_at"):
            if column in _columns("workspaces"): batch.drop_column(column)
