"""M001 user add role

Revision ID: 3156b9c824d1
Revises: fe56fa70289e
Create Date: 2026-06-04 15:40:54.911227

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '3156b9c824d1'
down_revision = 'fe56fa70289e'
branch_labels = None
depends_on = None


def upgrade():
    # The Postgres ENUM type must be created explicitly before ADD COLUMN —
    # SQLAlchemy only auto-emits CREATE TYPE inside CREATE TABLE, not ALTER.
    userrole = postgresql.ENUM('BKK_ADMIN', 'YGN_STAFF', name='userrole')
    userrole.create(op.get_bind(), checkfirst=True)
    # server_default keeps the existing bootstrap superuser row valid when the
    # NOT NULL column is added; the model default (BKK_ADMIN) governs new rows.
    op.add_column(
        'user',
        sa.Column(
            'role',
            postgresql.ENUM(
                'BKK_ADMIN', 'YGN_STAFF', name='userrole', create_type=False
            ),
            nullable=False,
            server_default='BKK_ADMIN',
        ),
    )


def downgrade():
    op.drop_column('user', 'role')
    postgresql.ENUM(name='userrole').drop(op.get_bind(), checkfirst=True)
