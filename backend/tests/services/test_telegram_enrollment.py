"""Schema-level coverage for Telegram enrollment (m031): the UNIQUE
constraint on User.telegram_chat_id, the telegram_username column, and the
TelegramConnectCode one-time-code table."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app import crud
from app.models import TelegramConnectCode, User, UserCreate, get_datetime_utc
from tests.utils.utils import random_email, random_lower_string


def _create_user(db: Session) -> User:
    return crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )


def test_telegram_chat_id_unique_across_users(db: Session) -> None:
    a = _create_user(db)
    b = _create_user(db)
    a.telegram_chat_id = "847392015"
    db.add(a)
    db.commit()

    b.telegram_chat_id = "847392015"
    db.add(b)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_multiple_users_can_have_no_telegram_chat_id(db: Session) -> None:
    # NULL != NULL under Postgres UNIQUE -- two unconnected users must not
    # collide with each other.
    a = _create_user(db)
    b = _create_user(db)
    assert a.telegram_chat_id is None
    assert b.telegram_chat_id is None
    db.add(a)
    db.add(b)
    db.commit()  # must not raise


def test_telegram_username_persists(db: Session) -> None:
    user = _create_user(db)
    user.telegram_chat_id = "111222333"
    user.telegram_username = "winthiha"
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.telegram_username == "winthiha"


def test_telegram_connect_code_round_trip(db: Session) -> None:
    user = _create_user(db)
    code = TelegramConnectCode(
        user_id=user.id,
        code="A7X2K9examplecode",
        expires_at=get_datetime_utc() + timedelta(minutes=10),
    )
    db.add(code)
    db.commit()
    db.refresh(code)

    assert code.consumed_at is None
    assert code.id is not None


def test_telegram_connect_code_uniqueness(db: Session) -> None:
    user = _create_user(db)
    shared_code = f"dup-{uuid.uuid4().hex[:8]}"
    db.add(
        TelegramConnectCode(
            user_id=user.id,
            code=shared_code,
            expires_at=get_datetime_utc() + timedelta(minutes=10),
        )
    )
    db.commit()

    db.add(
        TelegramConnectCode(
            user_id=user.id,
            code=shared_code,
            expires_at=get_datetime_utc() + timedelta(minutes=10),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
