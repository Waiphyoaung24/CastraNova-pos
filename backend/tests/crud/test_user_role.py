from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, UserRole


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


def test_new_user_defaults_to_staff(db: Session) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email="role-default@example.com",
            password="changethis123",
        ),
    )
    assert user.role == UserRole.YGN_STAFF


def test_first_superuser_seed_stays_admin(db: Session) -> None:
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    assert su.role == UserRole.BKK_ADMIN
