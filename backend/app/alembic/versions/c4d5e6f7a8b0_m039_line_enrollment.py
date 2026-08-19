"""m039 line enrollment

Self-service LINE connect flow:
- lineconnectcode -- the one-time-code table binding a LINE chat message back
  to the user who requested it. See the LineConnectCode model docstring: the
  webhook has no session, so the code alone is the identity. The DB only
  enforces uniqueness; unguessability, single use and the TTL are enforced at
  the application layer.
- UNIQUE(user.line_user_id) -- a LINE account can only ever be bound to one
  POS user. This is a security requirement, not a nicety: without it two staff
  can bind the same LINE account and cross-feed each other's stock and pricing
  notifications. Safe to add outright because nothing has ever written the
  column -- every row is NULL -- and it only gets riskier the longer it waits.
  Multiple NULLs are unaffected; Postgres UNIQUE never treats NULL = NULL.
- GRANT DELETE on lineconnectcode. create_line_connect_code reaps the caller's
  prior codes, and m026's DEFAULT PRIVILEGES only cover SELECT, INSERT, UPDATE.
  m034 had to add exactly this for telegramconnectcode after the fact; doing it
  in the same migration that creates the table avoids repeating that miss.

Revision ID: c4d5e6f7a8b0
Revises: b2c3d4e5f6a8
Create Date: 2026-08-12 00:00:00.000000

"""
import os
import re

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b0'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def _role():
    """Return the quoted app role if configured and existing, else None.

    Copied from m034/m037 -- these migrations are standalone by convention and
    deliberately do not import from each other.
    """
    role = os.environ.get("POSTGRES_APP_USER", "")
    if not role:
        return None  # role not configured — grant is a no-op (e.g. CI without env)
    # The role name is interpolated into the GRANT statement below —
    # guard against injection via a malicious/typo'd env value.
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", role):
        raise RuntimeError("POSTGRES_APP_USER must match [a-z][a-z0-9_]{0,62}")
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
    ).scalar()
    if not exists:
        return None
    return f'"{role}"'


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_user_line_user_id', 'user', ['line_user_id']
    )
    op.create_table(
        'lineconnectcode',
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
        op.f('ix_lineconnectcode_user_id'),
        'lineconnectcode',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_lineconnectcode_code'),
        'lineconnectcode',
        ['code'],
        unique=True,
    )
    q = _role()
    if q is not None:
        op.execute(f"GRANT DELETE ON lineconnectcode TO {q}")


def downgrade() -> None:
    op.drop_index(
        op.f('ix_lineconnectcode_code'), table_name='lineconnectcode'
    )
    op.drop_index(
        op.f('ix_lineconnectcode_user_id'), table_name='lineconnectcode'
    )
    op.drop_table('lineconnectcode')
    op.drop_constraint('uq_user_line_user_id', 'user', type_='unique')
