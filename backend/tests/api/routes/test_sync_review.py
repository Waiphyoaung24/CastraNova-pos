import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    SyncReviewItemCreate,
    SyncReviewReason,
    SyncReviewState,
)


def _admin_id(db: Session) -> uuid.UUID:
    # resolved_by_user_id has a FK to user.id, so the actor must be a real user.
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _ingest(
    db: Session, *, reason: SyncReviewReason = SyncReviewReason.STALE,
    key: uuid.UUID | None = None,
) -> uuid.UUID:
    data = SyncReviewItemCreate(
        idempotency_key=key or uuid.uuid4(),
        mutation_kind="sale",
        payload={"customer_id": str(uuid.uuid4()), "total_thb": "1200.00"},
        reason=reason,
    )
    return crud.create_sync_review_item(session=db, data=data).id


def test_ingest_creates_pending_item(db: Session) -> None:
    item_id = _ingest(db, reason=SyncReviewReason.CONFLICT)
    item = crud.get_sync_review_item(session=db, item_id=item_id)
    assert item is not None
    assert item.state == SyncReviewState.PENDING
    assert item.reason == SyncReviewReason.CONFLICT
    assert item.resolved_by_user_id is None


def test_ingest_is_idempotent_by_key(db: Session) -> None:
    key = uuid.uuid4()
    first = _ingest(db, key=key)
    second = _ingest(db, key=key)  # replay of the same offline item
    assert first == second  # same row, no duplicate


def test_resolve_marks_resolved_with_actor_and_note(db: Session) -> None:
    item_id = _ingest(db)
    admin_id = _admin_id(db)
    item = crud.resolve_sync_review_item(
        session=db,
        item_id=item_id,
        admin_id=admin_id,
        new_state=SyncReviewState.RESOLVED,
        note="re-entered manually",
    )
    assert item.state == SyncReviewState.RESOLVED
    assert item.resolved_by_user_id == admin_id
    assert item.resolved_at is not None
    assert item.resolution_note == "re-entered manually"


def test_resolve_rejects_non_pending(db: Session) -> None:
    item_id = _ingest(db)
    admin_id = _admin_id(db)
    crud.resolve_sync_review_item(
        session=db,
        item_id=item_id,
        admin_id=admin_id,
        new_state=SyncReviewState.DISCARDED,
        note=None,
    )
    with pytest.raises(HTTPException) as exc:  # second resolve -> 409
        crud.resolve_sync_review_item(
            session=db,
            item_id=item_id,
            admin_id=admin_id,
            new_state=SyncReviewState.RESOLVED,
            note=None,
        )
    assert exc.value.status_code == 409


def test_resolve_rejects_pending_target_state(db: Session) -> None:
    item_id = _ingest(db)
    with pytest.raises(HTTPException) as exc:  # cannot "resolve" to PENDING
        crud.resolve_sync_review_item(
            session=db,
            item_id=item_id,
            admin_id=uuid.uuid4(),
            new_state=SyncReviewState.PENDING,
            note=None,
        )
    assert exc.value.status_code == 422


def test_resolve_404_for_missing_item(db: Session) -> None:
    with pytest.raises(HTTPException) as exc:
        crud.resolve_sync_review_item(
            session=db, item_id=uuid.uuid4(), admin_id=_admin_id(db),
            new_state=SyncReviewState.RESOLVED, note=None,
        )
    assert exc.value.status_code == 404


def test_list_filters_by_state(db: Session) -> None:
    pending_id = _ingest(db)
    discarded_id = _ingest(db)
    crud.resolve_sync_review_item(
        session=db,
        item_id=discarded_id,
        admin_id=_admin_id(db),
        new_state=SyncReviewState.DISCARDED,
        note=None,
    )
    pending = crud.list_sync_review_items(session=db, state=SyncReviewState.PENDING)
    ids = {i.id for i in pending}
    assert pending_id in ids and discarded_id not in ids
