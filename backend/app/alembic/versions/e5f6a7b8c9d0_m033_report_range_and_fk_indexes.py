"""m033 report range and fk indexes

Two groups, added for different reasons — the distinction matters if these
are ever revisited.

Range-filter support (the actual margin_report win). Every query in the
margin_report family (backend/app/crud.py, window from _month_window)
closes over [start, end) on exactly one of these columns, and none was
indexed, so each was a full-table scan that degrades as history grows:

- sale.sold_at — crud.py:3415, 3517, 3533, 3549, 3662. The hottest range
  predicate in the file. Plain index; sold_at is NOT NULL.
- serviceticket.closed_at — crud.py:3430, 3441, 3570, 3587, 3680, 3693.
  Partial (WHERE closed_at IS NOT NULL): open tickets are NULL and can
  never satisfy `>= start`, so they are dead weight in the index.
- projectpull.fulfilled_at — crud.py:3453, 3464, 3605, 3622, 3710, 3726,
  3777, 3793. Partial for the same reason. Note the existing
  ix_project_pull_state_created does not serve these queries — none of
  them references state or created_at.

Bare-FK hygiene (NOT a report optimization — deliberately so). These three
columns were flagged as margin_report bottlenecks, but they are not:
saleline.product_id is only ever grouped through the expression
COALESCE(saleline.product_id, unit.product_id) (crud.py:3507, 3518), which
a plain column index cannot serve; saleline.unit_id joins to unit.id, the
primary-key side (crud.py:3516); serviceticketpart.product_id is grouped
over rows already materialized via the indexed service_ticket_id join
(crud.py:3566-3571). The customer-filter joins at crud.py:4580-4593 reach
both tables through sale_id / service_ticket_id and merely project
product_id. They are indexed here only because PostgreSQL scans child
tables when a referenced parent row is deleted, and because m032 set the
precedent of covering these FKs uniformly.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- range-filter support ---
    op.create_index('ix_sale_sold_at', 'sale', ['sold_at'], unique=False)
    op.create_index(
        'ix_serviceticket_closed_at', 'serviceticket', ['closed_at'],
        unique=False, postgresql_where=sa.text('closed_at IS NOT NULL'),
    )
    op.create_index(
        'ix_projectpull_fulfilled_at', 'projectpull', ['fulfilled_at'],
        unique=False, postgresql_where=sa.text('fulfilled_at IS NOT NULL'),
    )
    # --- bare-FK hygiene ---
    op.create_index(
        'ix_saleline_unit_id', 'saleline', ['unit_id'],
        unique=False, postgresql_where=sa.text('unit_id IS NOT NULL'),
    )
    op.create_index(
        'ix_saleline_product_id', 'saleline', ['product_id'],
        unique=False, postgresql_where=sa.text('product_id IS NOT NULL'),
    )
    op.create_index(
        'ix_serviceticketpart_product_id', 'serviceticketpart',
        ['product_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_serviceticketpart_product_id', table_name='serviceticketpart'
    )
    op.drop_index(
        'ix_saleline_product_id', table_name='saleline',
        postgresql_where=sa.text('product_id IS NOT NULL'),
    )
    op.drop_index(
        'ix_saleline_unit_id', table_name='saleline',
        postgresql_where=sa.text('unit_id IS NOT NULL'),
    )
    op.drop_index(
        'ix_projectpull_fulfilled_at', table_name='projectpull',
        postgresql_where=sa.text('fulfilled_at IS NOT NULL'),
    )
    op.drop_index(
        'ix_serviceticket_closed_at', table_name='serviceticket',
        postgresql_where=sa.text('closed_at IS NOT NULL'),
    )
    op.drop_index('ix_sale_sold_at', table_name='sale')
