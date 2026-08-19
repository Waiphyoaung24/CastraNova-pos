"""m037 product delete grant

The superuser-only DELETE /products/{id} removes a never-stocked product,
so the least-privilege castranova_app role needs DELETE on product --
m026's DEFAULT PRIVILEGES only cover SELECT, INSERT, UPDATE. Without this
the endpoint fails at commit with InsufficientPrivilege. Mirrors m034's
`GRANT DELETE ON telegramconnectcode` precedent for the same role.

Only product. pricechange is one of m026's LEDGERS and is guarded by
m021's reject_ledger_mutation trigger, so its rows cannot be deleted at
all -- which is why the endpoint refuses (409) to delete a product that
has any price history, rather than trying to cascade.

No schema change: grants only.

Revision ID: a1b2c3d4e5f7
Revises: c4d5e6f7a8b9
Create Date: 2026-08-08 00:00:00.000000

"""
import os
import re

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None

TABLES = ("product",)


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
    for table in TABLES:
        op.execute(f"GRANT DELETE ON {table} TO {q}")


def downgrade():
    q = _role()
    if q is None:
        return
    for table in TABLES:
        op.execute(f"REVOKE DELETE ON {table} FROM {q}")
