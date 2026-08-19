"""m031 telegram enrollment

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-19 00:00:00.000000

Self-service Telegram connect flow (FR-018 follow-up):
- user.telegram_username — display-only, captured alongside telegram_chat_id
  at connect time so a stale binding is visible ("Connected as @username")
  instead of a bare, meaningless chat id.
- UNIQUE(user.telegram_chat_id) — a chat can only ever be bound to one
  account; NULL (not-yet-connected) users don't collide with each other,
  since Postgres UNIQUE never treats NULL = NULL.
- telegramconnectcode — the one-time-code table binding a Telegram /start
  deep link back to the user who requested it. This is an authentication
  boundary, not a mere correlation key (see the TelegramConnectCode model
  docstring), so `code` must stay unguessable and single-use at the
  application layer; the DB only enforces uniqueness.

No duplicate telegram_chat_id values existed at authoring time (verified
against the running dev DB), since no code path could set the column before
this migration -- the UNIQUE constraint is safe to add outright.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user',
        sa.Column(
            'telegram_username',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        'uq_user_telegram_chat_id', 'user', ['telegram_chat_id']
    )
    op.create_table(
        'telegramconnectcode',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column(
            'code', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_telegramconnectcode_user_id'),
        'telegramconnectcode',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_telegramconnectcode_code'),
        'telegramconnectcode',
        ['code'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_telegramconnectcode_code'), table_name='telegramconnectcode'
    )
    op.drop_index(
        op.f('ix_telegramconnectcode_user_id'), table_name='telegramconnectcode'
    )
    op.drop_table('telegramconnectcode')
    op.drop_constraint('uq_user_telegram_chat_id', 'user', type_='unique')
    op.drop_column('user', 'telegram_username')
