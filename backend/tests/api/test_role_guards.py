import pytest
from fastapi import HTTPException

from app.api.deps import get_admin
from app.models import User, UserRole


def _user(role: UserRole) -> User:
    return User(email="x@example.com", hashed_password="x", role=role)


def test_get_admin_allows_admin() -> None:
    assert get_admin(_user(UserRole.BKK_ADMIN)).role == UserRole.BKK_ADMIN


def test_get_admin_blocks_staff() -> None:
    with pytest.raises(HTTPException) as exc:
        get_admin(_user(UserRole.YGN_STAFF))
    assert exc.value.status_code == 403
