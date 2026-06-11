"""Idempotently ensure the least-privilege runtime role exists (prestart step).

Runs on the admin connection BEFORE `alembic upgrade head` so the grants
migration (M026) can reference the role. No-op when POSTGRES_APP_USER is unset.
Secrets stay in env — never in migrations.
"""

import logging

from sqlalchemy import create_engine, text

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    if not settings.POSTGRES_APP_USER:
        logger.info("POSTGRES_APP_USER unset — skipping app-role creation")
        return
    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": settings.POSTGRES_APP_USER},
        ).scalar()
        # Role names can't be bound params; the name/password come from our env.
        pw = settings.POSTGRES_APP_PASSWORD.replace("'", "''")
        if not exists:
            conn.execute(
                text(
                    f'CREATE ROLE "{settings.POSTGRES_APP_USER}" '
                    f"LOGIN PASSWORD '{pw}'"
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
