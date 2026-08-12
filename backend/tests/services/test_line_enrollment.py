"""Schema-level coverage for LINE enrollment (m039): the UNIQUE constraint on
User.line_user_id and the LineConnectCode one-time-code table.

Mirrors test_telegram_enrollment.py.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.models import (
    LineConfirmOutcome,
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


# --- crud: minting ---------------------------------------------------------


def test_create_mints_a_128_bit_code(db: Session) -> None:
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    # 32 hex chars == 128 bits. The code is a bearer credential: the webhook
    # has no session, so shortening it is a security regression, not cosmetic.
    assert len(record.code) == 32
    assert all(c in "0123456789abcdef" for c in record.code)
    assert record.consumed_at is None
    assert record.expires_at > get_datetime_utc()


def test_create_reaps_this_users_prior_codes(db: Session) -> None:
    user = _create_user(db)
    first = crud.create_line_connect_code(session=db, user_id=user.id)
    second = crud.create_line_connect_code(session=db, user_id=user.id)
    remaining = db.exec(
        select(LineConnectCode).where(LineConnectCode.user_id == user.id)
    ).all()
    assert [r.code for r in remaining] == [second.code]
    assert first.code != second.code


def test_create_does_not_reap_another_users_codes(db: Session) -> None:
    mine, theirs = _create_user(db), _create_user(db)
    theirs_code = crud.create_line_connect_code(session=db, user_id=theirs.id)
    crud.create_line_connect_code(session=db, user_id=mine.id)
    survived = db.exec(
        select(LineConnectCode).where(LineConnectCode.code == theirs_code.code)
    ).first()
    assert survived is not None


# --- crud: confirming ------------------------------------------------------


def test_confirm_binds_the_line_user_id(db: Session) -> None:
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=line_id
    )
    assert outcome is LineConfirmOutcome.CONNECTED
    db.refresh(user)
    assert user.line_user_id == line_id


def test_confirm_is_single_use(db: Session) -> None:
    # LINE redelivers webhooks, so this replay path is routine, not theoretical.
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=_line_id()
    )
    second = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=_line_id()
    )
    assert second is LineConfirmOutcome.PENDING


def test_confirm_rejects_an_unknown_code(db: Session) -> None:
    # The LINE analogue of Telegram's "a different user cannot confirm" test,
    # which cannot exist here because the webhook has no session at all.
    outcome = crud.confirm_line_connect_code(
        session=db, code=uuid.uuid4().hex, line_user_id=_line_id()
    )
    assert outcome is LineConfirmOutcome.PENDING


def test_confirm_rejects_an_expired_code(db: Session) -> None:
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    record.expires_at = get_datetime_utc() - timedelta(seconds=1)
    db.add(record)
    db.commit()
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=_line_id()
    )
    assert outcome is LineConfirmOutcome.PENDING
    db.refresh(user)
    assert user.line_user_id is None


def test_confirm_refuses_a_line_account_bound_elsewhere(db: Session) -> None:
    shared = _line_id()
    incumbent = _create_user(db)
    incumbent.line_user_id = shared
    db.add(incumbent)
    db.commit()

    latecomer = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=shared
    )
    assert outcome is LineConfirmOutcome.USER_ALREADY_LINKED
    db.refresh(latecomer)
    assert latecomer.line_user_id is None


def test_a_refused_cross_bind_does_not_consume_the_code(db: Session) -> None:
    # The user can unlink the other account and retry within the TTL, so
    # burning the code here would strand them.
    shared = _line_id()
    incumbent = _create_user(db)
    incumbent.line_user_id = shared
    db.add(incumbent)
    db.commit()

    latecomer = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)
    crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=shared
    )
    db.refresh(record)
    assert record.consumed_at is None


# --- crud: unbinding -------------------------------------------------------


def test_disconnect_clears_only_the_binding(db: Session) -> None:
    user = _create_user(db)
    user.line_user_id = _line_id()
    db.add(user)
    db.commit()

    crud.disconnect_line(session=db, user=user)
    db.refresh(user)
    assert user.line_user_id is None


def test_clear_line_user_unbinds_by_line_id(db: Session) -> None:
    line_id = _line_id()
    user = _create_user(db)
    user.line_user_id = line_id
    db.add(user)
    db.commit()

    crud.clear_line_user(session=db, line_user_id=line_id)
    db.refresh(user)
    assert user.line_user_id is None


def test_clear_line_user_is_a_no_op_for_an_unknown_id(db: Session) -> None:
    # unfollow fires for people who never connected.
    crud.clear_line_user(session=db, line_user_id=_line_id())
