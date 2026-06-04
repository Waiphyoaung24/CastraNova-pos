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
)
from app.services import notify

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
