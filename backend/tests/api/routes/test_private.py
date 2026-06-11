from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User, UserRole


def test_create_user(client: TestClient, db: Session) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "pollo@listo.com",
            "password": "password123",
            "full_name": "Pollo Listo",
        },
    )

    assert r.status_code == 200

    data = r.json()

    user = db.exec(select(User).where(User.id == data["id"])).first()

    assert user
    assert user.email == "pollo@listo.com"
    assert user.full_name == "Pollo Listo"


def test_private_create_user_defaults_to_staff(
    client: TestClient, db: Session
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "staff-default@example.com",
            "password": "password123",
            "full_name": "Staff Default",
        },
    )

    assert r.status_code == 200

    user = db.exec(select(User).where(User.id == r.json()["id"])).first()

    assert user
    assert user.role == UserRole.YGN_STAFF


def test_private_create_user_accepts_explicit_role(
    client: TestClient, db: Session
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "explicit-admin@example.com",
            "password": "password123",
            "full_name": "Explicit Admin",
            "role": "BKK_ADMIN",
        },
    )

    assert r.status_code == 200

    user = db.exec(select(User).where(User.id == r.json()["id"])).first()

    assert user
    assert user.role == UserRole.BKK_ADMIN
