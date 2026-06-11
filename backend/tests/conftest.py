from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as _create_engine
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import UserRole
from tests.utils.user import (
    authentication_token_from_email,
    authentication_token_from_email_with_role,
)
from tests.utils.utils import get_superuser_token_headers

# TRUNCATE teardown needs the admin connection: the app role deliberately
# cannot TRUNCATE the append-only ledgers (hardening spec §4.2.3).
admin_engine = _create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        # Release any open transaction/locks on the app connection first, or the
        # admin TRUNCATE below blocks behind them forever.
        session.rollback()
        session.close()
        # Wipe all domain data so reruns start clean. TRUNCATE ... CASCADE is
        # FK-safe and auto-discovers every table, so it scales as the schema grows
        # (audit FKs to `user` make an ordered DELETE brittle). Runs on the admin
        # engine — the app role cannot TRUNCATE the append-only ledgers.
        with Session(admin_engine) as admin_session:
            rows = admin_session.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).all()
            names = [r[0] for r in rows]
            if names:
                quoted = ", ".join(f'"{n}"' for n in names)
                admin_session.execute(
                    text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
                )
                admin_session.commit()


@pytest.fixture(autouse=True, scope="session")
def _disable_login_rate_limit() -> Generator[None, None, None]:
    # The suite logs in many times across fixtures; a global 5/15min limit would
    # break unrelated tests. Disable here; the rate-limit test re-enables locally.
    from app.core.limiter import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )


@pytest.fixture(scope="module")
def staff_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email_with_role(
        client=client,
        email="staff@example.com",
        db=db,
        role=UserRole.YGN_STAFF,
    )
