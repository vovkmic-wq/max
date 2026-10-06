"""Initial persistent editor, scheduler, inbox and outbox schema."""

from alembic import op
from max_channel_agent.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError(
        "Destructive downgrade disabled; use an encrypted backup into a fresh target."
    )
