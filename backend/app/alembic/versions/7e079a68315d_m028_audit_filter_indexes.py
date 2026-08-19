"""m028 audit filter indexes

Revision ID: 7e079a68315d
Revises: 586bc2d1d79d
Create Date: 2026-07-11 15:22:30.173246

Supporting indexes for the audit log's sku/batch_no filters (FR-019):
- unit.product_id: state-agnostic lookup (ix_unit_state_product leads with
  current_state, so it doesn't serve a product_id-only scan).
- partbatch.batch_no: product-agnostic lookup (uq_part_batch_product_no leads
  with product_id, so it doesn't serve a bare batch_no equality).
- partmovement.part_batch_id: partial, since it's only ever set on the
  RECEIVED movement that created a batch (NULL on consumption rows).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7e079a68315d'
down_revision = '586bc2d1d79d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_part_batch_batch_no', 'partbatch', ['batch_no'], unique=False)
    op.create_index(
        'ix_partmovement_part_batch_id', 'partmovement', ['part_batch_id'],
        unique=False, postgresql_where=sa.text('part_batch_id IS NOT NULL'),
    )
    op.create_index('ix_unit_product', 'unit', ['product_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_unit_product', table_name='unit')
    op.drop_index(
        'ix_partmovement_part_batch_id', table_name='partmovement',
        postgresql_where=sa.text('part_batch_id IS NOT NULL'),
    )
    op.drop_index('ix_part_batch_batch_no', table_name='partbatch')
