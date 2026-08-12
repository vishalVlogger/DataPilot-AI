"""System-admin operations metadata."""
from alembic import op
import sqlalchemy as sa

from app.models import SystemAdminAudit, SystemError

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("feedback")}
    if "priority" not in columns:
        with op.batch_alter_table("feedback") as batch:
            batch.add_column(sa.Column("priority", sa.String(20), nullable=False, server_default="medium"))
    for table in (SystemError.__table__, SystemAdminAudit.__table__):
        table.create(bind, checkfirst=True)
        for index in table.indexes:
            index.create(bind, checkfirst=True)


def downgrade() -> None:
    SystemAdminAudit.__table__.drop(op.get_bind(), checkfirst=True)
    SystemError.__table__.drop(op.get_bind(), checkfirst=True)
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("feedback")}
    if "priority" in columns:
        with op.batch_alter_table("feedback") as batch:
            batch.drop_column("priority")
