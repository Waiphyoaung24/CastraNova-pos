"""Reapply least-privilege app-role grants after Alembic migrations."""

import logging

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.ensure_app_role import ROLE_NAME_RE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    role = settings.POSTGRES_APP_USER
    if not role:
        logger.info("POSTGRES_APP_USER unset — skipping app-role grants")
        return
    if not ROLE_NAME_RE.fullmatch(role):
        raise ValueError("POSTGRES_APP_USER must match [a-z][a-z0-9_]{0,62}")

    quoted_role = f'"{role}"'
    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with engine.begin() as conn:
        for statement in (
            f"GRANT USAGE ON SCHEMA public TO {quoted_role}",
            f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {quoted_role}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}",
            f"REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM {quoted_role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {quoted_role}",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {quoted_role}",
            f'GRANT DELETE ON "user" TO {quoted_role}',
            f"GRANT DELETE ON telegramconnectcode TO {quoted_role}",
            f"REVOKE ALL ON alembic_version FROM {quoted_role}",
        ):
            conn.execute(text(statement))

        ledger_tables = conn.execute(
            text(
                """
                SELECT DISTINCT format('%I.%I', table_ns.nspname, table_rel.relname)
                FROM pg_trigger AS trg
                JOIN pg_class AS table_rel ON table_rel.oid = trg.tgrelid
                JOIN pg_namespace AS table_ns ON table_ns.oid = table_rel.relnamespace
                JOIN pg_proc AS trigger_fn ON trigger_fn.oid = trg.tgfoid
                JOIN pg_namespace AS fn_ns ON fn_ns.oid = trigger_fn.pronamespace
                WHERE NOT trg.tgisinternal
                  AND table_ns.nspname = 'public'
                  AND fn_ns.nspname = 'public'
                  AND trigger_fn.proname = 'reject_ledger_mutation'
                ORDER BY 1
                """
            )
        ).scalars()
        for qualified_table in ledger_tables:
            # PostgreSQL format(%I) produced this identifier from its catalog.
            conn.execute(
                text(
                    f"REVOKE UPDATE, DELETE ON {qualified_table} FROM {quoted_role}"
                )
            )

    logger.info("reconciled privileges for role %s", role)


if __name__ == "__main__":
    main()
