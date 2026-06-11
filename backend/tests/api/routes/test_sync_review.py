import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
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
    return crud.create_sync_review_item(
        session=db, data=data, submitted_by_user_id=_admin_id(db)
    ).id


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


def _payload() -> dict:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "mutation_kind": "sale",
        "payload": {"total_thb": "1200.00"},
        "reason": "STALE",
    }


def test_ingest_requires_auth(client: TestClient) -> None:
    r = client.post(f"{settings.API_V1_STR}/sync-review", json=_payload())
    assert r.status_code == 401


def test_staff_can_ingest(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "PENDING" and body["reason"] == "STALE"


def test_ingest_response_omits_payload(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "payload" not in body  # staff ingest response must not echo the payload
    assert body["state"] == "PENDING"


def test_admin_list_includes_payload(
    client: TestClient, superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    ingested_id = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    ).json()["id"]
    r = client.get(
        f"{settings.API_V1_STR}/sync-review?state=PENDING",
        headers=superuser_token_headers,
    )
    item = next(i for i in r.json() if i["id"] == ingested_id)
    assert "payload" in item  # admins are entitled to the full payload


def test_ingest_records_submitter(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    """Ingest stamps the submitting user on the row (hardening spec §4.1.3)."""
    r = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    # Staff-facing response must NOT expose the submitter (admin-only field).
    assert "submitted_by_user_id" not in body
    item = crud.get_sync_review_item(session=db, item_id=uuid.UUID(body["id"]))
    staff = crud.get_user_by_email(session=db, email="staff@example.com")
    assert item is not None and staff is not None
    assert item.submitted_by_user_id == staff.id


def test_replay_by_different_user_is_rejected(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    """Same idempotency_key replayed by a DIFFERENT user -> 409
    (hardening spec §4.1.3): a 122-bit key collision across users is a
    stolen/duplicated key, never a legitimate offline retry."""
    body = _payload()
    r1 = client.post(
        f"{settings.API_V1_STR}/sync-review", json=body, headers=staff_token_headers
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"{settings.API_V1_STR}/sync-review", json=body,
        headers=superuser_token_headers,
    )
    assert r2.status_code == 409


def test_ingest_is_idempotent_over_http(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    body = _payload()
    r1 = client.post(f"{settings.API_V1_STR}/sync-review", json=body, headers=staff_token_headers)
    r2 = client.post(f"{settings.API_V1_STR}/sync-review", json=body, headers=staff_token_headers)
    assert r1.json()["id"] == r2.json()["id"]


def test_list_is_admin_only(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/sync-review?state=PENDING",
        headers=staff_token_headers,
    )
    assert r.status_code == 403


def test_admin_lists_pending(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    ingested_id = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    ).json()["id"]
    r = client.get(
        f"{settings.API_V1_STR}/sync-review?state=PENDING",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert any(i["id"] == ingested_id for i in r.json())


def test_resolve_is_admin_only(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    created = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(), headers=staff_token_headers
    ).json()
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{created['id']}/resolve",
        json={"state": "RESOLVED", "note": "done"},
        headers=staff_token_headers,
    )
    assert r.status_code == 403


def test_admin_resolves_item(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    created = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(), headers=staff_token_headers
    ).json()
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{created['id']}/resolve",
        json={"state": "DISCARDED", "note": "duplicate"},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "DISCARDED"
    assert body["resolved_by_user_id"] is not None
    assert body["resolved_at"] is not None


def test_resolve_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{uuid.uuid4()}/resolve",
        json={"state": "RESOLVED", "note": None},
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
