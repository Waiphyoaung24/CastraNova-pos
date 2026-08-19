"""m034 telegramconnectcode delete grant

create_telegram_connect_code now reaps the caller's prior codes
(session.delete()) when minting a fresh one, so the least-privilege
castranova_app role needs DELETE on telegramconnectcode -- m026's
DEFAULT PRIVILEGES only cover SELECT, INSERT, UPDATE for tables created
after it ran, and telegramconnectcode isn't one of the LEDGERS tables
that reasons about DELETE at all. Mirrors m026's `GRANT DELETE ON "user"`
precedent for the same role.

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-23 00:00:00.000000

"""
import os
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def _role():
    """Return the quoted app role if configured and existing, else None."""
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


def upgrade():
    q = _role()
    if q is None:
        return
    op.execute(f"GRANT DELETE ON telegramconnectcode TO {q}")


def downgrade():
    q = _role()
    if q is None:
        return
    op.execute(f"REVOKE DELETE ON telegramconnectcode FROM {q}")
