"""Schema-level coverage for LINE enrollment (m039): the UNIQUE constraint on
User.line_user_id and the LineConnectCode one-time-code table.

Mirrors test_telegram_enrollment.py.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app import crud
from app.models import (
    LineConnectCode,
    User,
    UserCreate,
    get_datetime_utc,
)
from tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session) -> User:
    return crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )


def _line_id() -> str:
    return f"U{uuid.uuid4().hex}"


def test_line_user_id_unique_across_users(db: Session) -> None:
    # Without this constraint two staff can bind the same LINE account and
    # cross-feed each other's stock and pricing notifications.
    shared = _line_id()
    a = _create_user(db)
    b = _create_user(db)
    a.line_user_id = shared
    db.add(a)
    db.commit()

    b.line_user_id = shared
    db.add(b)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_multiple_users_can_have_no_line_user_id(db: Session) -> None:
    # NULL != NULL under Postgres UNIQUE. Every user is un-enrolled until they
    # connect, so the constraint must not collide them with each other.
    a = _create_user(db)
    b = _create_user(db)
    assert a.line_user_id is None
    assert b.line_user_id is None
    db.add(a)
    db.add(b)
    db.commit()  # must not raise


def test_line_connect_code_round_trip(db: Session) -> None:
    user = _create_user(db)
    code = LineConnectCode(
        user_id=user.id,
        code=uuid.uuid4().hex,
        expires_at=get_datetime_utc() + timedelta(minutes=10),
    )
    db.add(code)
    db.commit()
    db.refresh(code)

    assert code.consumed_at is None
    assert code.id is not None
    assert code.user_id == user.id


def test_line_connect_code_uniqueness(db: Session) -> None:
    user = _create_user(db)
    shared_code = f"dup-{uuid.uuid4().hex[:8]}"
    db.add(
        LineConnectCode(
            user_id=user.id,
            code=shared_code,
            expires_at=get_datetime_utc() + timedelta(minutes=10),
        )
    )
    db.commit()

    db.add(
        LineConnectCode(
            user_id=user.id,
            code=shared_code,
            expires_at=get_datetime_utc() + timedelta(minutes=10),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
