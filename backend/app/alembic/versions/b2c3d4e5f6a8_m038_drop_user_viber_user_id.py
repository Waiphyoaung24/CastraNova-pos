"""m038 drop user.viber_user_id

Viber is removed as a notification channel. It never had an enrollment
path -- nothing in the codebase ever wrote user.viber_user_id -- so every
value is NULL and dropping the column loses no data.

NotificationChannel.VIBER is deliberately NOT removed from the
`notificationchannel` Postgres enum. Postgres has no `DROP VALUE` (only
`ADD VALUE`, which m030 used for TELEGRAM), so removing it would mean
recreating the type, which in turn requires deleting existing VIBER rows
from notificationlog -- a table guarded by trg_notificationlog_append_only
(m021, BEFORE UPDATE OR DELETE). Keeping a dead-but-legal enum value costs
one comment in models.py; the alternative costs an audit trail.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-08-10 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("user", "viber_user_id")


def downgrade():
    # Nullable on the way back: there is no data to restore, and the column
    # was always nullable anyway.
    op.add_column(
        "user",
        sa.Column("viber_user_id", sa.String(length=128), nullable=True),
    )
