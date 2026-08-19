"""m030 telegram notification channel

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17 00:00:00.000000

Adds Telegram as a third FR-018 push channel alongside LINE and Viber:
- notificationchannel enum gains 'TELEGRAM'
- user.telegram_chat_id — the per-recipient destination, populated
  out-of-band at enrollment (a bot cannot message a user until that user
  has messaged it first). Table-only, like line_user_id / viber_user_id.

Asymmetric downgrade (deliberate): PostgreSQL cannot drop a value from an
enum without recreating the type and rewriting every dependent column, so
the downgrade removes the column but LEAVES 'TELEGRAM' in the enum. That is
harmless — the value is simply unreferenced once _CHANNELS no longer maps it.

PG 12+ permits ALTER TYPE ... ADD VALUE inside a transaction block; the new
value may not be *used* in that same transaction, which this migration does
not do.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationchannel ADD VALUE IF NOT EXISTS 'TELEGRAM'")
    op.add_column(
        'user',
        sa.Column(
            'telegram_chat_id',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('user', 'telegram_chat_id')
    # 'TELEGRAM' intentionally left in the notificationchannel enum — see docstring.
