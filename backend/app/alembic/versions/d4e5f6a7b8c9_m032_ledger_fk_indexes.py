"""m032 ledger fk indexes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-19 00:00:00.000000

Both unitmovement and partmovement are append-only ledgers that grow on
every sale, receive, and adjustment forever, and neither carries an index
on actor_user_id, sale_id, or stock_adjustment_id:

- (actor_user_id, occurred_at DESC) — list_audit/count_audit
  (backend/app/crud.py) always pair a WHERE actor_user_id = :x filter with
  ORDER BY occurred_at DESC, id DESC and a LIMIT, so a composite index
  serves the filter and the sort together instead of forcing a Sort node
  after an index-only filter scan.
- sale_id (partial, WHERE sale_id IS NOT NULL) — margin_report's
  _product_rows joins *.sale_id -> sale.id from the unindexed side to
  attribute SOLD movements to a sale's date window. Sparse column (only
  set on movements that came from a sale), mirroring the existing
  project_pull_id / service_ticket_id partial indexes.
- stock_adjustment_id (partial, WHERE stock_adjustment_id IS NOT NULL) —
  same unindexed-nullable-FK gap; added for consistency with the other
  optional-origin columns on these ledgers.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_unitmovement_actor_occurred', 'unitmovement',
        ['actor_user_id', sa.text('occurred_at DESC')], unique=False,
    )
    op.create_index(
        'ix_unitmovement_sale_id', 'unitmovement', ['sale_id'],
        unique=False, postgresql_where=sa.text('sale_id IS NOT NULL'),
    )
    op.create_index(
        'ix_unitmovement_stock_adjustment_id', 'unitmovement',
        ['stock_adjustment_id'], unique=False,
        postgresql_where=sa.text('stock_adjustment_id IS NOT NULL'),
    )
    op.create_index(
        'ix_partmovement_actor_occurred', 'partmovement',
        ['actor_user_id', sa.text('occurred_at DESC')], unique=False,
    )
    op.create_index(
        'ix_partmovement_sale_id', 'partmovement', ['sale_id'],
        unique=False, postgresql_where=sa.text('sale_id IS NOT NULL'),
    )
    op.create_index(
        'ix_partmovement_stock_adjustment_id', 'partmovement',
        ['stock_adjustment_id'], unique=False,
        postgresql_where=sa.text('stock_adjustment_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'ix_partmovement_stock_adjustment_id', table_name='partmovement',
        postgresql_where=sa.text('stock_adjustment_id IS NOT NULL'),
    )
    op.drop_index(
        'ix_partmovement_sale_id', table_name='partmovement',
        postgresql_where=sa.text('sale_id IS NOT NULL'),
    )
    op.drop_index('ix_partmovement_actor_occurred', table_name='partmovement')
    op.drop_index(
        'ix_unitmovement_stock_adjustment_id', table_name='unitmovement',
        postgresql_where=sa.text('stock_adjustment_id IS NOT NULL'),
    )
    op.drop_index(
        'ix_unitmovement_sale_id', table_name='unitmovement',
        postgresql_where=sa.text('sale_id IS NOT NULL'),
    )
    op.drop_index('ix_unitmovement_actor_occurred', table_name='unitmovement')
