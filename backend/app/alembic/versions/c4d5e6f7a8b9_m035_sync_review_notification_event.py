"""m035 sync review notification event

Revision ID: c4d5e6f7a8b9
Revises: f1a2b3c4d5e6
Create Date: 2026-07-29 00:00:00.000000

Adds SYNC_REVIEW_PENDING to the notificationevent enum so admins can be
pushed an alert when an offline mutation lands in the sync-review queue
(M020). Additive only — no table, column, or constraint changes.

Asymmetric downgrade (deliberate, mirroring m030): PostgreSQL cannot drop a
value from an enum without recreating the type and rewriting every dependent
column (notificationlog.event_type, notificationpreference.event_type), so
the downgrade LEAVES the value in place. Harmless — it is simply unreferenced
once no producer emits it.

PG 12+ permits ALTER TYPE ... ADD VALUE inside a transaction block; the new
value may not be *used* in that same transaction, which this migration does
not do.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b9'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notificationevent ADD VALUE IF NOT EXISTS 'SYNC_REVIEW_PENDING'"
    )


def downgrade() -> None:
    # 'SYNC_REVIEW_PENDING' intentionally left in the notificationevent enum
    # — see module docstring.
    pass
