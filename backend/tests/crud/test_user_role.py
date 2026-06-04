from sqlmodel import Session

from app import crud
from app.models import UserCreate, UserRole


def test_new_user_can_set_staff_role(db: Session) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email="role-staff@example.com",
            password="changethis123",
            role=UserRole.YGN_STAFF,
        ),
    )
    assert user.role == UserRole.YGN_STAFF


def test_new_user_defaults_to_admin_role(db: Session) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email="role-default@example.com",
            password="changethis123",
        ),
    )
    assert user.role == UserRole.BKK_ADMIN
