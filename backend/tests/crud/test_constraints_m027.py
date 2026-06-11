"""M027 constraint-hardening tests: DB-level CHECKs for saleline.quantity (#5)
and product prices (#6), plus systemsetting.updated_by_user_id ON DELETE SET
NULL (#7). Defense-in-depth — the API already validates, these assert the DB
rejects raw writes that bypass it."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Product,
    Sale,
    SaleLine,
    SaleLineKind,
    SystemSetting,
    User,
)


def _make_product(db: Session, *, retail: str = "100.00", repair: str = "20.00") -> Product:
    product = Product(
        sku=f"M027-{uuid.uuid4().hex[:8]}",
        model_name="Widget",
        retail_price_thb=Decimal(retail),
        repair_price_thb=Decimal(repair),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def _make_sale(db: Session) -> Sale:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="M027 Cust")
    )
    sale = Sale(
        customer_id=customer.id,
        created_by_user_id=user.id,
        idempotency_key=uuid.uuid4(),
        total_thb=Decimal("0.00"),
        total_cogs_thb=Decimal("0.00"),
    )
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return sale


def test_saleline_quantity_must_be_positive(db: Session) -> None:
    """#5: a raw saleline insert with quantity <= 0 must be rejected by the DB."""
    product = _make_product(db)
    sale = _make_sale(db)
    line = SaleLine(
        sale_id=sale.id,
        line_kind=SaleLineKind.PART,
        product_id=product.id,
        quantity=0,
        unit_price_thb=Decimal("10.00"),
        unit_cost_thb=Decimal("5.00"),
    )
    db.add(line)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_product_prices_must_be_non_negative(db: Session) -> None:
    """#6: negative retail/repair price must be rejected by the DB."""
    bad_retail = Product(
        sku=f"M027-{uuid.uuid4().hex[:8]}",
        model_name="Widget",
        retail_price_thb=Decimal("-1.00"),
        repair_price_thb=Decimal("20.00"),
    )
    db.add(bad_retail)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_systemsetting_user_delete_sets_null(db: Session) -> None:
    """#7: deleting a user referenced by systemsetting.updated_by_user_id
    succeeds and nulls the column (instead of being blocked by the FK)."""
    user = User(
        email=f"m027-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    setting = SystemSetting(
        key=f"m027_{uuid.uuid4().hex[:8]}",
        value={"v": 1},
        updated_by_user_id=user.id,
    )
    db.add(setting)
    db.commit()
    setting_id = setting.id

    db.delete(user)
    db.commit()  # must NOT raise

    refreshed = db.exec(select(SystemSetting).where(SystemSetting.id == setting_id)).one()
    assert refreshed.updated_by_user_id is None
