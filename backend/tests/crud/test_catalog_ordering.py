"""Newest-first ordering on the shared catalogs (hardening spec §3).

Unordered LIMIT-100 heap scans silently dropped newly created rows from every
screen catalog once a table crossed 100 rows (observed live at 107 products,
2026-06-11). Newest-first guarantees recent rows are always on page one.
"""

import uuid

from sqlmodel import Session

from app import crud
from app.models import (
    CustomerCreate,
    ProductCreate,
    ProjectCreate,
    SupplierCreate,
    TrackingMode,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def test_list_products_newest_first(db: Session) -> None:
    first = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ORD-A-{_suffix()}",
            model_name="Ordering A",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    second = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ORD-B-{_suffix()}",
            model_name="Ordering B",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    listed = crud.list_products(session=db, skip=0, limit=500)
    ids = [p.id for p in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_customers_newest_first(db: Session) -> None:
    first = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ordering Cust A {_suffix()}")
    )
    second = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ordering Cust B {_suffix()}")
    )
    listed = crud.list_customers(session=db, skip=0, limit=500)
    ids = [c.id for c in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_suppliers_newest_first(db: Session) -> None:
    first = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Ordering Supp A {_suffix()}")
    )
    second = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Ordering Supp B {_suffix()}")
    )
    listed = crud.list_suppliers(session=db, skip=0, limit=500)
    ids = [s.id for s in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_projects_newest_first(db: Session) -> None:
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ordering Proj Cust {_suffix()}")
    )
    first = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"ORD-A-{_suffix()}",
            name="Ordering Project A",
            customer_id=customer.id,
        ),
    )
    second = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"ORD-B-{_suffix()}",
            name="Ordering Project B",
            customer_id=customer.id,
        ),
    )
    listed = crud.list_projects(session=db, skip=0, limit=500)
    ids = [p.id for p in listed]
    assert ids.index(second.id) < ids.index(first.id)
