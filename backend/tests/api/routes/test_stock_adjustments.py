"""Stock Adjustment (FR-011, Flow E, Task 3.2).

SERIALIZED → unit terminal ADJUSTED_OUT; QUANTITY negative → FIFO consume
(spans batches); QUANTITY positive → new ADJ-### batch. Admin-only, idempotent."""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    AdjustmentTarget,
    CostLine,
    Location,
    PartBatch,
    PartMovement,
    ProductCreate,
    ReceivePiece,
    StockAdjustment,
    StockAdjustmentCreate,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitMovement,
    UnitState,
)

PREFIX = settings.API_V1_STR


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _seed(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _unit_adj(barcode: str, reason: str = "x") -> StockAdjustmentCreate:
    return StockAdjustmentCreate(
        target_kind=AdjustmentTarget.UNIT,
        castranova_barcode=barcode,
        reason=reason,
        idempotency_key=uuid.uuid4(),
    )


def _qty_adj(
    sku: str, delta: int, *, cost: str | None = None, reason: str = "x"
) -> StockAdjustmentCreate:
    return StockAdjustmentCreate(
        target_kind=AdjustmentTarget.QUANTITY,
        sku=sku,
        quantity_delta=delta,
        purchase_cost_thb=Decimal(cost) if cost is not None else None,
        reason=reason,
        idempotency_key=uuid.uuid4(),
    )


def _make(db: Session, adj_in: StockAdjustmentCreate) -> StockAdjustment:
    return crud.create_stock_adjustment(
        session=db, adj_in=adj_in, created_by_user_id=_user_id(db)
    )


def _quantity_product(db: Session, *, batches: list[tuple[int, str]]):
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ADJ-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    for qty, cost in batches:
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=_user_id(db),
        )
    return product


def _serialized_unit(db: Session) -> Unit:
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ADJU-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[ReceivePiece(supplier_serial="SN-A1", purchase_cost_thb=Decimal("600.00"))],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    return units[0]


# --- crud branches ------------------------------------------------------------


def test_serialized_adjustment_moves_unit_to_terminal(db: Session) -> None:
    unit = _serialized_unit(db)
    adj = _make(db, _unit_adj(unit.castranova_barcode, "damaged in storage"))
    db.refresh(unit)
    assert unit.current_state == UnitState.ADJUSTED_OUT
    mv = db.exec(
        select(UnitMovement).where(UnitMovement.stock_adjustment_id == adj.id)
    ).first()
    assert mv is not None and mv.event_type.value == "ADJUSTED_OUT"


def test_serialized_double_adjustment_conflict(db: Session) -> None:
    unit = _serialized_unit(db)
    _make(db, _unit_adj(unit.castranova_barcode))
    with pytest.raises(HTTPException) as exc:
        _make(db, _unit_adj(unit.castranova_barcode))  # distinct key, unit terminal
    assert exc.value.status_code == 409


def test_negative_quantity_adjustment_spans_two_batches(db: Session) -> None:
    product = _quantity_product(db, batches=[(3, "10.00"), (4, "12.00")])
    adj = _make(db, _qty_adj(product.sku, -5, reason="recount loss"))
    mv = db.exec(
        select(PartMovement).where(PartMovement.stock_adjustment_id == adj.id)
    ).first()
    assert mv is not None and mv.event_type.value == "ADJUSTED_OUT"
    assert mv.quantity == 5
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == mv.id)
    ).all()
    assert sorted((cl.quantity, str(cl.unit_cost_thb)) for cl in cost_lines) == [
        (2, "12.00"),
        (3, "10.00"),
    ]
    remaining = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product.id)
        ).all()
    )
    assert remaining == 2


def test_negative_adjustment_oversell_conflict(db: Session) -> None:
    product = _quantity_product(db, batches=[(3, "10.00")])
    with pytest.raises(HTTPException) as exc:
        _make(db, _qty_adj(product.sku, -5, reason="too much"))
    assert exc.value.status_code == 409


def test_positive_quantity_adjustment_creates_adj_batch(db: Session) -> None:
    product = _quantity_product(db, batches=[(2, "10.00")])
    adj = _make(db, _qty_adj(product.sku, 5, cost="11.50", reason="found stock"))
    batch = db.exec(
        select(PartBatch).where(
            PartBatch.product_id == product.id, PartBatch.is_adjustment.is_(True)
        )
    ).first()
    assert batch is not None
    assert "ADJ-" in batch.batch_no
    assert batch.remaining_qty == 5
    assert batch.supplier_id is None
    assert batch.purchase_cost_thb == Decimal("11.50")
    mv = db.exec(
        select(PartMovement).where(PartMovement.stock_adjustment_id == adj.id)
    ).first()
    assert mv is not None and mv.event_type.value == "RECEIVED"


def test_adjustment_idempotent_replay(db: Session) -> None:
    product = _quantity_product(db, batches=[(10, "10.00")])
    adj_in = _qty_adj(product.sku, -3, reason="recount")
    first = _make(db, adj_in)
    second = crud.create_stock_adjustment(  # same key -> replay, no double-consume
        session=db, adj_in=adj_in, created_by_user_id=_user_id(db)
    )
    assert first.id == second.id
    remaining = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product.id)
        ).all()
    )
    assert remaining == 7  # consumed once (10 - 3), not twice


# --- schema validation --------------------------------------------------------


def test_positive_adjustment_requires_purchase_cost() -> None:
    with pytest.raises(ValidationError):
        StockAdjustmentCreate(
            target_kind=AdjustmentTarget.QUANTITY,
            sku="X",
            quantity_delta=5,
            reason="no cost",
            idempotency_key=uuid.uuid4(),
        )


def test_unit_adjustment_rejects_quantity_fields() -> None:
    with pytest.raises(ValidationError):
        StockAdjustmentCreate(
            target_kind=AdjustmentTarget.UNIT,
            castranova_barcode="CN-1",
            quantity_delta=3,
            reason="mismatch",
            idempotency_key=uuid.uuid4(),
        )


# --- route authz --------------------------------------------------------------


def test_stock_adjustment_staff_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    product = _quantity_product(db, batches=[(5, "10.00")])
    r = client.post(
        f"{PREFIX}/stock-adjustments",
        headers=staff_token_headers,
        json={
            "target_kind": "QUANTITY",
            "sku": product.sku,
            "quantity_delta": -1,
            "reason": "staff try",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 403


def test_stock_adjustment_admin_ok(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product = _quantity_product(db, batches=[(5, "10.00")])
    r = client.post(
        f"{PREFIX}/stock-adjustments",
        headers=superuser_token_headers,
        json={
            "target_kind": "QUANTITY",
            "sku": product.sku,
            "quantity_delta": -2,
            "reason": "admin recount",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_kind"] == "QUANTITY"
    assert body["quantity_delta"] == -2
    assert db.get(StockAdjustment, uuid.UUID(body["id"])) is not None
