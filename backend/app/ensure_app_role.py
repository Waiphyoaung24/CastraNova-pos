"""Idempotently ensure the least-privilege runtime role exists (prestart step).

Runs on the admin connection BEFORE `alembic upgrade head` so the grants
migration (M026) can reference the role. No-op when POSTGRES_APP_USER is unset.
Secrets stay in env — never in migrations.
"""

import logging
import re

from sqlalchemy import create_engine, text

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,62}")


def main() -> None:
    if not settings.POSTGRES_APP_USER:
        logger.info("POSTGRES_APP_USER unset — skipping app-role creation")
        return
    if not ROLE_NAME_RE.fullmatch(settings.POSTGRES_APP_USER):
        raise ValueError("POSTGRES_APP_USER must match [a-z][a-z0-9_]{0,62}")
    if not settings.POSTGRES_APP_PASSWORD:
        raise ValueError(
            "POSTGRES_APP_PASSWORD must be set when POSTGRES_APP_USER is set"
        )
    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": settings.POSTGRES_APP_USER},
        ).scalar()
        # CREATE/ALTER ROLE are utility statements — they accept no
        # wire-protocol bind parameters, so the name (regex-guarded above)
        # and password (single quotes doubled) must be interpolated.
        # SET LOCAL log_statement = 'none' (superuser-only; we run on the
        # admin connection) keeps the password literal out of the Postgres
        # statement log for the rest of this transaction. Residual exposure:
        # the statement is transiently visible in pg_stat_activity while it
        # executes — acceptable for our dev/preprod single-host deploy.
        conn.execute(text("SET LOCAL log_statement = 'none'"))
        pw = settings.POSTGRES_APP_PASSWORD.replace("'", "''")
        if not exists:
            conn.execute(
                text(
                    f'CREATE ROLE "{settings.POSTGRES_APP_USER}" '
                    f"NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                    f"NOREPLICATION NOBYPASSRLS LOGIN PASSWORD '{pw}'"
                )
            )
            logger.info("created role %s", settings.POSTGRES_APP_USER)
        else:
            conn.execute(
                text(
                    f'ALTER ROLE "{settings.POSTGRES_APP_USER}" '
                    f"LOGIN PASSWORD '{pw}'"
                )
            )
            logger.info("role %s exists — password refreshed", settings.POSTGRES_APP_USER)


if __name__ == "__main__":
    main()
