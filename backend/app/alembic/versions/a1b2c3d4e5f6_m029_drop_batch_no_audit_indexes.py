"""m029 drop batch_no audit indexes

Revision ID: a1b2c3d4e5f6
Revises: 7e079a68315d
Create Date: 2026-07-12 00:00:00.000000

The audit log's batch_no filter (FR-019) has been removed, so its two
supporting indexes are dead weight:
- partmovement.part_batch_id (partial, non-null subset)
- partbatch.batch_no (standalone)

ix_unit_product (also added in m028) still serves the sku filter and is
untouched here.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '7e079a68315d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        'ix_partmovement_part_batch_id', table_name='partmovement',
        postgresql_where=sa.text('part_batch_id IS NOT NULL'),
    )
    op.drop_index('ix_part_batch_batch_no', table_name='partbatch')


def downgrade() -> None:
    op.create_index('ix_part_batch_batch_no', 'partbatch', ['batch_no'], unique=False)
    op.create_index(
        'ix_partmovement_part_batch_id', 'partmovement', ['part_batch_id'],
        unique=False, postgresql_where=sa.text('part_batch_id IS NOT NULL'),
    )
