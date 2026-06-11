"""m024 syncreview submitted_by

Revision ID: 0d75e85a30ef
Revises: 73a2b0eb6de0
Create Date: 2026-06-11 14:32:25.814423

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '0d75e85a30ef'
down_revision = '73a2b0eb6de0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('syncreviewitem', sa.Column('submitted_by_user_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_syncreviewitem_submitted_by_user_id', 'syncreviewitem', 'user', ['submitted_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_syncreviewitem_submitted_by_user_id', 'syncreviewitem', type_='foreignkey')
    op.drop_column('syncreviewitem', 'submitted_by_user_id')
