"""Route + trigger tests for notifications (FR-018, Task 2.7)."""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    ADMIN_ONLY_EVENTS,
    ALL_ROLE_EVENTS,
    CustomerCreate,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    ProductCreate,
    ProjectCreate,
    ProjectPullCreate,
    ProjectPullLineCreate,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
    UserRole,
)
from app.services import notify
from tests.utils.user import authentication_token_from_email_with_role
from tests.utils.utils import random_email

PREFIX = settings.API_V1_STR


def _resp(status_code: int, json_body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", "https://example.test"),
    )


# --- preference routes --------------------------------------------------------


def test_get_preferences_returns_current_user_prefs(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    # Query-or-create so this doesn't leak a duplicate that the UNIQUE constraint
    # would reject on a sibling test that reuses the seed admin.
    if not db.exec(
        select(NotificationPreference).where(
            NotificationPreference.user_id == admin.id,
            NotificationPreference.channel == NotificationChannel.LINE,
            NotificationPreference.event_type == NotificationEvent.PULL_SHORT,
        )
    ).first():
        db.add(
            NotificationPreference(
                user_id=admin.id,
                channel=NotificationChannel.LINE,
                event_type=NotificationEvent.PULL_SHORT,
                enabled=True,
            )
        )
        db.commit()
    r = client.get(f"{PREFIX}/notifications/preferences", headers=superuser_token_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(
        p["channel"] == "LINE" and p["event_type"] == "PULL_SHORT" for p in rows
    )


def test_patch_preferences_upsert_idempotent(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    body = {
        "preferences": [
            {
                "channel": "VIBER",
                "event_type": "LOW_STOCK",
                "enabled": True,
            }
        ]
    }
    r1 = client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=superuser_token_headers,
        json=body,
    )
    assert r1.status_code == 200, r1.text
    created = [
        p
        for p in r1.json()
        if p["channel"] == "VIBER" and p["event_type"] == "LOW_STOCK"
    ]
    assert len(created) == 1 and created[0]["enabled"] is True

    # toggle off — same row updated, not duplicated
    body["preferences"][0]["enabled"] = False
    r2 = client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=superuser_token_headers,
        json=body,
    )
    assert r2.status_code == 200, r2.text
    toggled = [
        p
        for p in r2.json()
        if p["channel"] == "VIBER" and p["event_type"] == "LOW_STOCK"
    ]
    assert len(toggled) == 1 and toggled[0]["enabled"] is False

    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    db.expire_all()
    rows = db.exec(
        select(NotificationPreference).where(
            NotificationPreference.user_id == admin.id,
            NotificationPreference.channel == NotificationChannel.VIBER,
            NotificationPreference.event_type == NotificationEvent.LOW_STOCK,
        )
    ).all()
    assert len(rows) == 1


def test_patch_preferences_rejects_duplicate_pair(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    body = {
        "preferences": [
            {"channel": "LINE", "event_type": "PULL_SHORT", "enabled": True},
            {"channel": "LINE", "event_type": "PULL_SHORT", "enabled": False},
        ]
    }
    r = client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=superuser_token_headers,
        json=body,
    )
    assert r.status_code == 422, r.text


def test_preferences_isolated_between_users(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=superuser_token_headers,
        json={
            "preferences": [
                {"channel": "LINE", "event_type": "OVERRIDE_PENDING", "enabled": True}
            ]
        },
    )
    r = client.get(
        f"{PREFIX}/notifications/preferences", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    assert not any(
        p["channel"] == "LINE" and p["event_type"] == "OVERRIDE_PENDING"
        for p in r.json()
    )


# --- generated preference grid ------------------------------------------------
#
# The grid is what makes opt-in self-service. Before it, GET returned only
# persisted rows, so a fresh user saw an empty page with no way to create one
# and provisioning needed hand-written SQL.


def _grid_pairs(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(p["channel"], p["event_type"]) for p in rows}


def test_grid_offers_every_channel_event_pair_to_a_fresh_user(
    client: TestClient, db: Session
) -> None:
    headers = authentication_token_from_email_with_role(
        client=client, email=random_email(), db=db, role=UserRole.YGN_STAFF
    )
    r = client.get(f"{PREFIX}/notifications/preferences", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()

    expected = {
        (c.value, e.value) for c in NotificationChannel for e in ALL_ROLE_EVENTS
    }
    assert _grid_pairs(rows) == expected
    # Nothing persisted yet, so every row is a synthetic default.
    assert all(p["enabled"] is False for p in rows)
    assert all(p["id"] is None for p in rows)


def test_grid_excludes_admin_only_events_from_staff(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{PREFIX}/notifications/preferences", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    offered_events = {p["event_type"] for p in r.json()}
    # Assert presence first: without this the test passes vacuously against an
    # empty grid and proves nothing.
    assert NotificationEvent.LOW_STOCK.value in offered_events
    for event in ADMIN_ONLY_EVENTS:
        assert event.value not in offered_events


def test_grid_offers_all_events_to_admin(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/notifications/preferences", headers=superuser_token_headers
    )
    assert r.status_code == 200, r.text
    offered = _grid_pairs(r.json())
    assert offered == {
        (c.value, e.value) for c in NotificationChannel for e in NotificationEvent
    }


def test_grid_preserves_a_persisted_opt_in(client: TestClient, db: Session) -> None:
    """A persisted row must win over the synthetic default, or toggling a
    preference on would appear to do nothing after a reload."""
    headers = authentication_token_from_email_with_role(
        client=client, email=random_email(), db=db, role=UserRole.YGN_STAFF
    )
    client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=headers,
        json={
            "preferences": [
                {
                    "channel": "TELEGRAM",
                    "event_type": "LOW_STOCK",
                    "enabled": True,
                }
            ]
        },
    )
    r = client.get(f"{PREFIX}/notifications/preferences", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()

    match = [
        p
        for p in rows
        if p["channel"] == "TELEGRAM" and p["event_type"] == "LOW_STOCK"
    ]
    # Exactly one row — the persisted one replaces the synthetic, not joins it.
    assert len(match) == 1
    assert match[0]["enabled"] is True
    assert match[0]["id"] is not None
    # The rest of the grid is still offered alongside it.
    assert len(rows) == len(NotificationChannel) * len(ALL_ROLE_EVENTS)


def test_patch_response_matches_get_response_shape(
    client: TestClient, db: Session
) -> None:
    """PATCH returns the full merged grid, the same shape as GET, so the
    client can replace its state wholesale after a toggle instead of merging
    two different response shapes."""
    headers = authentication_token_from_email_with_role(
        client=client, email=random_email(), db=db, role=UserRole.YGN_STAFF
    )
    r_patch = client.patch(
        f"{PREFIX}/notifications/preferences",
        headers=headers,
        json={
            "preferences": [
                {"channel": "LINE", "event_type": "LOW_STOCK", "enabled": True}
            ]
        },
    )
    assert r_patch.status_code == 200, r_patch.text
    r_get = client.get(f"{PREFIX}/notifications/preferences", headers=headers)
    assert r_get.status_code == 200, r_get.text
    assert _grid_pairs(r_patch.json()) == _grid_pairs(r_get.json())
    assert len(r_patch.json()) == len(NotificationChannel) * len(ALL_ROLE_EVENTS)


# --- trigger ------------------------------------------------------------------


@pytest.fixture
def short_pull_ctx(db: Session) -> dict[str, Any]:
    """Build a pull whose PART line will go SHORT (requests more than stock),
    with the seed admin enrolled + opted in to PULL_SHORT on LINE."""
    from app.models import Location

    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    admin.line_user_id = "L-admin"
    db.add(admin)
    if not db.exec(
        select(NotificationPreference).where(
            NotificationPreference.user_id == admin.id,
            NotificationPreference.channel == NotificationChannel.LINE,
            NotificationPreference.event_type == NotificationEvent.PULL_SHORT,
        )
    ).first():
        db.add(
            NotificationPreference(
                user_id=admin.id,
                channel=NotificationChannel.LINE,
                event_type=NotificationEvent.PULL_SHORT,
                enabled=True,
            )
        )
    db.commit()

    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="NotifCust")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"NP-{uuid.uuid4().hex[:8]}", name="NP", customer_id=customer.id
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="NSup")
    )
    part = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"NQ-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    crud.receive_quantity(
        session=db,
        product_id=part.id,
        supplier_id=supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )
    return {
        "project_id": project.id,
        "part_product_id": part.id,
        "admin_id": admin.id,
    }


def _create_pull(
    client: TestClient,
    headers: dict[str, str],
    ctx: dict[str, Any],
    *,
    part_qty: int,
) -> dict[str, Any]:
    payload = ProjectPullCreate(
        project_id=ctx["project_id"],
        lines=[
            ProjectPullLineCreate(
                line_kind=SaleLineKind.PART,
                product_id=ctx["part_product_id"],
                requested_qty=part_qty,
            )
        ],
    )
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=headers,
        json=payload.model_dump(mode="json"),
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_short_fulfill_writes_pull_short_log(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    short_pull_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "line-test-token")
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    pull = _create_pull(
        client, superuser_token_headers, short_pull_ctx, part_qty=3
    )
    line_id = pull["lines"][0]["id"]
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": [{"line_id": line_id, "fulfilled_qty": 2}]},  # 2 < 3 -> SHORT
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "SHORT"

    db.expire_all()
    logs = db.exec(
        select(NotificationLog).where(
            NotificationLog.event_type == NotificationEvent.PULL_SHORT,
            NotificationLog.target_user_id == short_pull_ctx["admin_id"],
        )
    ).all()
    relevant = [
        log for log in logs if log.payload.get("pull_id") == pull["id"]
    ]
    assert len(relevant) == 1
    assert relevant[0].status == NotificationStatus.SENT


def test_full_fulfill_writes_no_pull_short_log(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    short_pull_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    pull = _create_pull(
        client, superuser_token_headers, short_pull_ctx, part_qty=3
    )
    line_id = pull["lines"][0]["id"]
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": [{"line_id": line_id, "fulfilled_qty": 3}]},  # full
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "FULFILLED"

    db.expire_all()
    logs = db.exec(
        select(NotificationLog).where(
            NotificationLog.event_type == NotificationEvent.PULL_SHORT,
        )
    ).all()
    assert not [log for log in logs if log.payload.get("pull_id") == pull["id"]]


def test_notify_failure_does_not_break_fulfill(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    short_pull_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "line-test-token")

    def boom(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return _resp(503)

    monkeypatch.setattr(notify, "_post", boom)
    pull = _create_pull(
        client, superuser_token_headers, short_pull_ctx, part_qty=3
    )
    line_id = pull["lines"][0]["id"]
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": [{"line_id": line_id, "fulfilled_qty": 2}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "SHORT"

    db.expire_all()
    logs = db.exec(
        select(NotificationLog).where(
            NotificationLog.event_type == NotificationEvent.PULL_SHORT,
            NotificationLog.target_user_id == short_pull_ctx["admin_id"],
        )
    ).all()
    relevant = [log for log in logs if log.payload.get("pull_id") == pull["id"]]
    assert len(relevant) == 1
    assert relevant[0].status == NotificationStatus.FAILED
    # 4 attempts / 3 retries on persistent 5xx (regression for FIX 3/4).
    assert relevant[0].attempts == 4
