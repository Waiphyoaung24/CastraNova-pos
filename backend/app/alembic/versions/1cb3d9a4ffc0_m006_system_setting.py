"""M006 system_setting

Revision ID: 1cb3d9a4ffc0
Revises: 96111552847e
Create Date: 2026-06-05 14:34:50.758309

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1cb3d9a4ffc0'
down_revision = '96111552847e'
branch_labels = None
depends_on = None


def upgrade():
    # Only create system_setting (M006). The autogenerate diff also surfaced
    # pre-existing drift (notificationlog index name + project_pull_id FK/index
    # on the movement ledgers) that predates this task — intentionally omitted
    # here so M006 stays scoped to its own table.
    op.create_table('systemsetting',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_systemsetting_key'), 'systemsetting', ['key'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_systemsetting_key'), table_name='systemsetting')
    op.drop_table('systemsetting')
