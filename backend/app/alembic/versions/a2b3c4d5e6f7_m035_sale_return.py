"""m035 sale return

Two insert-only tables recording a customer return of sale lines, plus the
RETURNED value on the native `movementtype` enum.

ENUM NOTE: movementtype is a real PostgreSQL enum (created in m008,
79e9c3acbe2f). ALTER TYPE ... ADD VALUE cannot be used in the same
transaction that adds it, so it runs in an autocommit_block. PostgreSQL
offers no way to remove an enum value — the downgrade drops the tables and
deliberately leaves 'RETURNED' on the type.

GRANT NOTE: no explicit grants here. m026's ALTER DEFAULT PRIVILEGES already
gives the app role SELECT/INSERT/UPDATE on tables created by later
migrations. These are NOT append-only ledger tables (m026's REVOKE list is
for unitmovement/partmovement/costline/pricechange/notificationlog), so the
same posture as sale/saleline applies: no trigger, no REVOKE, no update or
delete endpoint.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE movementtype ADD VALUE IF NOT EXISTS 'RETURNED'")

    op.create_table(
        'salereturn',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sale_id', sa.Uuid(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.Uuid(), nullable=False),
        sa.Column(
            'reason', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column(
            'returned_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'total_refund_thb', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.Column(
            'total_cogs_restored_thb',
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sale.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_sale_return_idempotency_key'),
    )
    op.create_index('ix_salereturn_returned_at', 'salereturn', ['returned_at'])
    op.create_index('ix_salereturn_sale_id', 'salereturn', ['sale_id'])
    op.create_index(
        'ix_salereturn_created_by_user_id', 'salereturn', ['created_by_user_id']
    )

    op.create_table(
        'salereturnline',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sale_return_id', sa.Uuid(), nullable=False),
        sa.Column('sale_line_id', sa.Uuid(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column(
            'unit_price_thb', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.Column(
            'cogs_restored_thb', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.CheckConstraint(
            'quantity > 0', name='ck_salereturnline_quantity_positive'
        ),
        sa.CheckConstraint(
            'cogs_restored_thb >= 0', name='ck_salereturnline_cogs_nonneg'
        ),
        sa.ForeignKeyConstraint(['sale_line_id'], ['saleline.id']),
        sa.ForeignKeyConstraint(['sale_return_id'], ['salereturn.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_salereturnline_sale_return_id', 'salereturnline', ['sale_return_id']
    )
    op.create_index(
        'ix_salereturnline_sale_line_id', 'salereturnline', ['sale_line_id']
    )


def downgrade() -> None:
    op.drop_index('ix_salereturnline_sale_line_id', table_name='salereturnline')
    op.drop_index('ix_salereturnline_sale_return_id', table_name='salereturnline')
    op.drop_table('salereturnline')
    op.drop_index('ix_salereturn_created_by_user_id', table_name='salereturn')
    op.drop_index('ix_salereturn_sale_id', table_name='salereturn')
    op.drop_index('ix_salereturn_returned_at', table_name='salereturn')
    op.drop_table('salereturn')
    # 'RETURNED' stays on movementtype: PostgreSQL cannot drop an enum value.
