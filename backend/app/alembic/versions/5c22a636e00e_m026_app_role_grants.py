"""m026 app role grants

Least-privilege runtime role grants (hardening spec §4.2.3 / spec §4.6).
The role itself is created by app/ensure_app_role.py (prestart, before
`alembic upgrade head`) — secrets stay in env, never in migrations.

RECOVERY NOTE (bootstrap gap): if this migration ran in an environment WITHOUT
POSTGRES_APP_USER set (e.g. CI), it no-ops but is still stamped as applied.
To apply the grants later: set the env vars, run `python app/ensure_app_role.py`,
then re-execute this revision's grants by stamping back and upgrading:
  alembic stamp 311a921ce5e2 && alembic upgrade head
(Pre-deploy checklist item for Part 5.4.)

Revision ID: 5c22a636e00e
Revises: 311a921ce5e2
Create Date: 2026-06-11 15:53:47.581109

"""
import os
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5c22a636e00e'
down_revision = '311a921ce5e2'
branch_labels = None
depends_on = None

# Append-only ledgers (M021 triggers); spec §4.6 REVOKE now bites because the
# app connects as a non-superuser role.
# syncreviewitem is intentionally excluded: its resolve workflow requires UPDATE.
LEDGERS = ("unitmovement", "partmovement", "costline", "pricechange", "notificationlog")


def _role():
    """Return the quoted app role if configured and existing, else None."""
    role = os.environ.get("POSTGRES_APP_USER", "")
    if not role:
        return None  # role not configured — grants are a no-op (e.g. CI without env)
    # The role name is interpolated into GRANT/REVOKE statements below —
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
    op.execute(f"GRANT USAGE ON SCHEMA public TO {q}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {q}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {q}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {q}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {q}"
    )
    # Spec §4.6: REVOKE on the append-only ledgers — now real (non-superuser role).
    # FUTURE LEDGER NOTE: any ledger table added in a later migration must
    # explicitly REVOKE UPDATE, DELETE from the app role in that migration —
    # the DEFAULT PRIVILEGES above grant UPDATE to new tables by default.
    for t in LEDGERS:
        op.execute(f"REVOKE UPDATE, DELETE ON {t} FROM {q}")
    # Hard-deletes exist only on "user": delete_user_me + delete_user in
    # app/api/routes/users.py (the only session.delete() calls in the codebase;
    # the item table with its CASCADE FK was dropped in 6177c90e7673).
    op.execute(f'GRANT DELETE ON "user" TO {q}')
    # alembic_version stays admin-only (an app role that could UPDATE it could
    # skip future security migrations). No DDL, no table ownership.
    op.execute(f"REVOKE ALL ON alembic_version FROM {q}")


def downgrade():
    q = _role()
    if q is None:
        return
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {q}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {q}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {q}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {q}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {q}")
