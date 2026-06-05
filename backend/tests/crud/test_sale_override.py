"""Override wiring into create_sale (FR-010, Task 3.1e).

A sale line citing a pricing_override_request_id uses the approved override
price; a pending/rejected override blocks the sale (400); an override is
single-use (409 on a second sale)."""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    OverrideState,
    OverrideTargetKind,
    PricingOverrideCreate,
    ProductCreate,
    ReceivePiece,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _quantity_product(db: Session, *, retail: str = "100.00", qty: int = 10):
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"OVRSALE-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=retail,
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=qty,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    customer_id = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    ).id
    return product, customer_id


def _override(db: Session, product_id: uuid.UUID, requested: str):
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    return crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=product_id,
            requested_price_thb=Decimal(requested),
            reason="x",
        ),
        created_by_user_id=_user_id(db),
    )


def _sale_part_line(
    db: Session, *, sku: str, customer_id: uuid.UUID, override_id, key=None
):
    return crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.PART,
                sku=sku,
                quantity=2,
                pricing_override_request_id=override_id,
            )
        ],
        idempotency_key=key or uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )


def test_sale_part_approved_override_uses_requested_price(db: Session) -> None:
    product, customer_id = _quantity_product(db, retail="100.00")
    ovr = _override(db, product.id, "90.00")  # 10% -> PENDING
    crud.decide_pricing_override(
        session=db, override_id=ovr.id, decision="APPROVED", decided_by_user_id=_user_id(db)
    )
    sale = _sale_part_line(
        db, sku=product.sku, customer_id=customer_id, override_id=ovr.id
    )
    assert sale.total_thb == Decimal("180.00")  # 90 * 2, not retail 100
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).first()
    assert line is not None
    assert line.unit_price_thb == Decimal("90.00")
    assert line.pricing_override_request_id == ovr.id


def test_sale_part_auto_approved_override_applies(db: Session) -> None:
    product, customer_id = _quantity_product(db, retail="100.00")
    ovr = _override(db, product.id, "97.00")  # 3% -> AUTO_APPROVED
    assert ovr.state == OverrideState.AUTO_APPROVED
    sale = _sale_part_line(
        db, sku=product.sku, customer_id=customer_id, override_id=ovr.id
    )
    assert sale.total_thb == Decimal("194.00")  # 97 * 2


def test_sale_pending_override_blocked(db: Session) -> None:
    product, customer_id = _quantity_product(db, retail="100.00")
    ovr = _override(db, product.id, "90.00")  # 10% -> PENDING
    assert ovr.state == OverrideState.PENDING
    with pytest.raises(HTTPException) as exc:
        _sale_part_line(db, sku=product.sku, customer_id=customer_id, override_id=ovr.id)
    assert exc.value.status_code == 400


def test_sale_rejected_override_blocked(db: Session) -> None:
    product, customer_id = _quantity_product(db, retail="100.00")
    ovr = _override(db, product.id, "90.00")
    crud.decide_pricing_override(
        session=db, override_id=ovr.id, decision="REJECTED", decided_by_user_id=_user_id(db)
    )
    with pytest.raises(HTTPException) as exc:
        _sale_part_line(db, sku=product.sku, customer_id=customer_id, override_id=ovr.id)
    assert exc.value.status_code == 400


def test_sale_override_wrong_product_blocked(db: Session) -> None:
    product_a, customer_id = _quantity_product(db, retail="100.00")
    product_b, _ = _quantity_product(db, retail="100.00")
    ovr = _override(db, product_b.id, "97.00")  # for product B
    with pytest.raises(HTTPException) as exc:
        _sale_part_line(db, sku=product_a.sku, customer_id=customer_id, override_id=ovr.id)
    assert exc.value.status_code == 400


def test_sale_override_single_use(db: Session) -> None:
    product, customer_id = _quantity_product(db, retail="100.00", qty=10)
    ovr = _override(db, product.id, "97.00")  # AUTO_APPROVED
    _sale_part_line(db, sku=product.sku, customer_id=customer_id, override_id=ovr.id)
    with pytest.raises(HTTPException) as exc:
        _sale_part_line(db, sku=product.sku, customer_id=customer_id, override_id=ovr.id)
    assert exc.value.status_code == 409


def test_sale_unit_line_approved_override_uses_price(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"OVRUNIT-{uuid.uuid4().hex[:8]}",
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
        pieces=[ReceivePiece(supplier_serial="SN-OVR-1", purchase_cost_thb=Decimal("600.00"))],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    customer_id = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    ).id
    ovr = _override(db, product.id, "970.00")  # 3% -> AUTO_APPROVED
    sale = crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.UNIT,
                castranova_barcode=units[0].castranova_barcode,
                pricing_override_request_id=ovr.id,
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )
    assert sale.total_thb == Decimal("970.00")  # override, not retail 1000
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).first()
    assert line is not None
    assert line.pricing_override_request_id == ovr.id
