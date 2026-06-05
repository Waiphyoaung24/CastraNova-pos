"""M022 rename notificationlog target_user_id index

Revision ID: 682dcec90af9
Revises: 3f69da45b448
Create Date: 2026-06-05 18:03:40.374460

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '682dcec90af9'
down_revision = '3f69da45b448'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_notification_log_target_user_id", table_name="notificationlog")
    op.create_index(
        op.f("ix_notificationlog_target_user_id"),
        "notificationlog", ["target_user_id"], unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_notificationlog_target_user_id"), table_name="notificationlog")
    op.create_index(
        "ix_notification_log_target_user_id",
        "notificationlog", ["target_user_id"], unique=False,
    )
