"""Sale returns (design 2026-07-25): FIFO rollback + margin reversal.

PART lines restore the exact batches the sale consumed, in reverse consumption
order, at the original unit_cost_thb. Over-return is a 409; replay is idempotent.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    CustomerCreate,
    CustomerType,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    ProductCreate,
    ReceivePiece,
    Sale,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SaleReturn,
    SaleReturnCreateRequest,
    SaleReturnLine,
    SaleReturnLineInput,
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


def _rand() -> str:
    return uuid.uuid4().hex[:8]


def _customer(db: Session) -> uuid.UUID:
    c = crud.create_customer(
        session=db,
        customer_in=CustomerCreate(
            name=f"Cust {_rand()}", type=CustomerType.END_CUSTOMER
        ),
    )
    return c.id


def _part_product(db: Session, *, price: str = "100.00") -> tuple[uuid.UUID, str]:
    sku = f"PART-{_rand()}"
    p = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku,
            model_name="Returnable part",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal(price),
            repair_price_thb=Decimal("20.00"),
        ),
    )
    return p.id, sku


def _receive(db: Session, *, product_id: uuid.UUID, qty: int, cost: str) -> PartBatch:
    """Receive one QUANTITY batch and return it."""
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup {_rand()}")
    )
    return crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier.id,
        received_qty=qty,
        purchase_cost_thb=Decimal(cost),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )


def _sell_parts(db: Session, *, sku: str, qty: int, customer_id: uuid.UUID) -> Sale:
    return crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=qty)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )


def _return(
    db: Session, *, sale: Sale, sale_line_id: uuid.UUID, quantity: int
) -> SaleReturn:
    return crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="customer changed their mind",
            lines=[SaleReturnLineInput(sale_line_id=sale_line_id, quantity=quantity)],
        ),
        created_by_user_id=_user_id(db),
    )


def _line_of(db: Session, sale: Sale) -> SaleLine:
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).first()
    assert line is not None
    return line


# --- exact multi-batch rollback ---------------------------------------------


def test_return_restores_batches_in_reverse_consumption_order(db: Session) -> None:
    """5 sold from two batches (3 @ 10 + 2 @ 20); returning 4 restores the
    newest-consumed units first: all 2 from the second batch, 2 from the first."""
    _seed(db)
    product_id, sku = _part_product(db)
    b1 = _receive(db, product_id=product_id, qty=3, cost="10.00")
    b2 = _receive(db, product_id=product_id, qty=2, cost="20.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    db.refresh(b1)
    db.refresh(b2)
    assert b1.remaining_qty == 0
    assert b2.remaining_qty == 0

    ret = _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=4)

    db.refresh(b1)
    db.refresh(b2)
    assert b2.remaining_qty == 2  # newest batch fully restored first
    assert b1.remaining_qty == 2  # then 2 of the 3 older units
    # 2 * 20 + 2 * 10 = 60.00 restored, exactly the cost those units carried.
    assert ret.total_cogs_restored_thb == Decimal("60.00")
    assert ret.total_refund_thb == Decimal("400.00")  # 4 * retail 100


def test_second_partial_return_continues_where_the_first_stopped(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    b1 = _receive(db, product_id=product_id, qty=3, cost="10.00")
    b2 = _receive(db, product_id=product_id, qty=2, cost="20.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    line_id = _line_of(db, sale).id

    _return(db, sale=sale, sale_line_id=line_id, quantity=4)
    ret2 = _return(db, sale=sale, sale_line_id=line_id, quantity=1)

    db.refresh(b1)
    db.refresh(b2)
    assert b1.remaining_qty == 3  # the last unit comes from the oldest batch
    assert b2.remaining_qty == 2
    assert ret2.total_cogs_restored_thb == Decimal("10.00")


def test_return_appends_a_movement_and_cost_lines_at_original_cost(
    db: Session,
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="15.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))

    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)

    movement = db.exec(
        select(PartMovement).where(
            PartMovement.sale_id == sale.id,
            PartMovement.event_type == MovementType.RETURNED,
        )
    ).first()
    assert movement is not None
    assert movement.quantity == 2
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == movement.id)
    ).all()
    assert [cl.unit_cost_thb for cl in cost_lines] == [Decimal("15.00")]
    assert cost_lines[0].total_cost_thb == Decimal("30.00")


# --- guards ------------------------------------------------------------------


def test_over_return_is_409_and_restores_nothing(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    batch = _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    _return(db, sale=sale, sale_line_id=line_id, quantity=2)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=line_id, quantity=1)
    assert exc.value.status_code == 409

    db.refresh(batch)
    assert batch.remaining_qty == 2  # unchanged by the rejected return


def test_line_from_another_sale_is_404(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=4, cost="10.00")
    customer_id = _customer(db)
    sale_a = _sell_parts(db, sku=sku, qty=2, customer_id=customer_id)
    sale_b = _sell_parts(db, sku=sku, qty=2, customer_id=customer_id)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale_a, sale_line_id=_line_of(db, sale_b).id, quantity=1)
    assert exc.value.status_code == 404


def test_duplicate_sale_line_in_one_payload_is_422(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id

    with pytest.raises(HTTPException) as exc:
        crud.create_sale_return(
            session=db,
            sale_id=sale.id,
            payload=SaleReturnCreateRequest(
                idempotency_key=uuid.uuid4(),
                reason="x",
                lines=[
                    SaleReturnLineInput(sale_line_id=line_id, quantity=1),
                    SaleReturnLineInput(sale_line_id=line_id, quantity=1),
                ],
            ),
            created_by_user_id=_user_id(db),
        )
    assert exc.value.status_code == 422


def test_replay_returns_the_same_row_and_restocks_once(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    batch = _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    key = uuid.uuid4()

    payload = SaleReturnCreateRequest(
        idempotency_key=key,
        reason="replay",
        lines=[SaleReturnLineInput(sale_line_id=line_id, quantity=2)],
    )
    first = crud.create_sale_return(
        session=db, sale_id=sale.id, payload=payload, created_by_user_id=_user_id(db)
    )
    second = crud.create_sale_return(
        session=db, sale_id=sale.id, payload=payload, created_by_user_id=_user_id(db)
    )

    assert first.id == second.id
    db.refresh(batch)
    assert batch.remaining_qty == 2  # restocked once, not twice
    assert (
        len(
            db.exec(
                select(SaleReturnLine).where(
                    SaleReturnLine.sale_return_id == first.id
                )
            ).all()
        )
        == 1
    )


# --- UNIT lines ---------------------------------------------------------------


def _serialized_unit(
    db: Session, *, price: str = "5000.00", cost: str = "3000.00"
) -> tuple[str, uuid.UUID]:
    """Receive one SERIALIZED unit; return (barcode, unit_id)."""
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"UNIT-{_rand()}",
            model_name="Returnable unit",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb=Decimal(price),
            repair_price_thb=Decimal("50.00"),
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup {_rand()}")
    )
    # receive_serialized returns list[Unit] directly (crud.py:883).
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"S-{_rand()}", purchase_cost_thb=Decimal(cost)
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    return units[0].castranova_barcode, units[0].id


def _sell_unit(db: Session, *, barcode: str, customer_id: uuid.UUID) -> Sale:
    return crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )


def test_returned_unit_is_back_in_stock_and_sellable(db: Session) -> None:
    _seed(db)
    barcode, unit_id = _serialized_unit(db)
    customer_id = _customer(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=customer_id)
    sold_movement = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit_id,
            UnitMovement.event_type == MovementType.SOLD,
        )
    ).one()

    ret = _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    unit = db.get(Unit, unit_id)
    assert unit is not None
    db.refresh(unit)
    assert unit.current_state == UnitState.IN_STOCK
    # Back where it stood before the sale, not left at the CUSTOMER location.
    assert unit.current_location_id == sold_movement.from_location_id
    assert ret.total_cogs_restored_thb == Decimal("3000.00")
    assert ret.total_refund_thb == Decimal("5000.00")

    # And it can be sold again.
    resale = _sell_unit(db, barcode=barcode, customer_id=customer_id)
    assert resale.total_thb == Decimal("5000.00")


def test_returned_unit_appends_a_returned_movement(db: Session) -> None:
    _seed(db)
    barcode, unit_id = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    movement = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit_id,
            UnitMovement.event_type == MovementType.RETURNED,
        )
    ).first()
    assert movement is not None
    assert movement.sale_id == sale.id


def test_returning_the_same_unit_twice_is_409(db: Session) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    _return(db, sale=sale, sale_line_id=line_id, quantity=1)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=line_id, quantity=1)
    assert exc.value.status_code == 409


def test_unit_line_quantity_must_be_one(db: Session) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)
    assert exc.value.status_code in (409, 422)


# --- HTTP surface -------------------------------------------------------------


def test_admin_can_post_a_return(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "faulty on arrival",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 2}],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["sale_id"] == str(sale.id)
    assert Decimal(body["total_refund_thb"]) == Decimal("200.00")
    assert Decimal(body["total_cogs_restored_thb"]) == Decimal("20.00")
    assert len(body["lines"]) == 1


def test_staff_cannot_post_a_return(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=1, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=1, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=normal_user_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "nope",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 1}],
        },
    )
    assert r.status_code == 403


def test_missing_reason_is_422(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=1, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=1, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 1}],
        },
    )
    assert r.status_code == 422


def test_unknown_sale_is_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/sales/{uuid.uuid4()}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "x",
            "lines": [{"sale_line_id": str(uuid.uuid4()), "quantity": 1}],
        },
    )
    assert r.status_code == 404
