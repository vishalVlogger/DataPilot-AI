"""Tenant-scoped feedback attachment metadata."""
from alembic import op

from app.models import FeedbackAttachment

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    FeedbackAttachment.__table__.create(bind, checkfirst=True)
    for index in FeedbackAttachment.__table__.indexes:
        index.create(bind, checkfirst=True)


def downgrade() -> None:
    FeedbackAttachment.__table__.drop(op.get_bind(), checkfirst=True)
