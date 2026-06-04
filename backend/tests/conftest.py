from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
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


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        # Wipe all domain data so reruns start clean. TRUNCATE ... CASCADE is
        # FK-safe and auto-discovers every table, so it scales as the schema grows
        # (audit FKs to `user` make an ordered DELETE brittle).
        rows = session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).all()
        names = [r[0] for r in rows]
        if names:
            quoted = ", ".join(f'"{n}"' for n in names)
            session.execute(
                text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            )
            session.commit()


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
