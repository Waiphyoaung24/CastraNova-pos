"""DB-level append-only enforcement (M021 triggers + M026 role grants) and
scheduled CHECK constraints. With the least-privilege app role configured
(hardening spec §4.2.3) the REVOKE denies ledger UPDATE/DELETE outright; on
the admin fallback connection the M021 triggers still fire."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlmodel import Session, select, text

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    CustomerCreate,
    Location,
    MovementType,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationStatus,
    PartMovement,
    PriceChange,
    ProductCreate,
    ProductUpdate,
    ReceivePiece,
    Sale,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitMovement,
    UnitState,
)


def _seed_ledger_rows(db: Session) -> dict[str, uuid.UUID]:
    """Seed one real row in each of the 5 append-only ledger tables via the
    normal flows where possible (receive -> unit_movement + part_movement;
    sale -> cost_line; price change -> price_change; notification -> log).
    Returns a mapping table_name -> a row id."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="AppendOnly Co")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="AppendOnly Cust")
    )

    # SERIALIZED receive -> one unit_movement (RECEIVED)
    ser_product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"AO-SER-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    crud.receive_serialized(
        session=db,
        product_id=ser_product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:8]}",
                purchase_cost_thb=Decimal("50.00"),
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    um = db.exec(select(UnitMovement)).first()
    assert um is not None

    # QUANTITY receive -> part_movement (RECEIVED), then a part sale -> cost_line
    qty_product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"AO-QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    crud.receive_quantity(
        session=db,
        product_id=qty_product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.PART, sku=qty_product.sku, quantity=2
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=user.id,
    )
    pm = db.exec(
        select(PartMovement).where(PartMovement.event_type == MovementType.SOLD)
    ).first()
    assert pm is not None
    cl = db.exec(select(CostLine)).first()
    assert cl is not None

    # price_change via product update (retail price)
    crud.update_product(
        session=db,
        db_product=qty_product,
        product_in=ProductUpdate(retail_price_thb=Decimal("150.00")),
        changed_by_user_id=user.id,
    )
    pc = db.exec(select(PriceChange)).first()
    assert pc is not None

    # notification_log inserted directly (minimal valid row)
    nl = NotificationLog(
        channel=NotificationChannel.LINE,
        event_type=NotificationEvent.LOW_STOCK,
        target_user_id=user.id,
        payload={"k": "v"},
        status=NotificationStatus.SENT,
        attempts=1,
    )
    db.add(nl)
    db.commit()
    db.refresh(nl)

    return {
        "unitmovement": um.id,
        "partmovement": pm.id,
        "costline": cl.id,
        "pricechange": pc.id,
        "notificationlog": nl.id,
    }


@pytest.fixture
def ledger_ids(db: Session) -> dict[str, uuid.UUID]:
    return _seed_ledger_rows(db)


# An existing, type-correct column per table to target in the tamper UPDATE
# (not every ledger has a `notes` column; the BEFORE trigger fires regardless of
# which column the UPDATE touches).
_UPDATE_SETS = {
    "unitmovement": "notes = 'tamper'",
    "partmovement": "notes = 'tamper'",
    "costline": "quantity = quantity + 1",
    "pricechange": "reason = 'tamper'",
    "notificationlog": "last_error = 'tamper'",
}


@pytest.mark.parametrize(
    "table",
    ["unitmovement", "partmovement", "costline", "pricechange", "notificationlog"],
)
def test_update_rejected_on_ledger(
    db: Session, ledger_ids: dict[str, uuid.UUID], table: str
) -> None:
    row_id = ledger_ids[table]
    try:
        with pytest.raises(DBAPIError) as exc:
            db.execute(
                text(f"UPDATE {table} SET {_UPDATE_SETS[table]} WHERE id = :id"),
                {"id": str(row_id)},
            )
        # App role: REVOKE denies before the trigger fires ("permission denied");
        # admin fallback: the M021 trigger raises ("append-only").
        msg = str(exc.value)
        assert "append-only" in msg or "permission denied" in msg
    finally:
        db.rollback()


@pytest.mark.parametrize(
    "table",
    ["unitmovement", "partmovement", "costline", "pricechange", "notificationlog"],
)
def test_delete_rejected_on_ledger(
    db: Session, ledger_ids: dict[str, uuid.UUID], table: str
) -> None:
    row_id = ledger_ids[table]
    try:
        with pytest.raises(DBAPIError) as exc:
            db.execute(
                text(f"DELETE FROM {table} WHERE id = :id"), {"id": str(row_id)}
            )
        # App role: REVOKE denies before the trigger fires ("permission denied");
        # admin fallback: the M021 trigger raises ("append-only").
        msg = str(exc.value)
        assert "append-only" in msg or "permission denied" in msg
    finally:
        db.rollback()


# --- least-privilege app role (M026 grants, hardening spec §4.2.3) -------------

requires_app_role = pytest.mark.skipif(
    not settings.POSTGRES_APP_USER, reason="app role not configured"
)


@requires_app_role
@pytest.mark.parametrize(
    "table",
    ["unitmovement", "partmovement", "costline", "pricechange", "notificationlog"],
)
def test_app_role_cannot_truncate_ledger(table: str) -> None:
    # Fresh engine so a denied statement can't poison the shared pool.
    app_engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with app_engine.connect() as conn:
            with pytest.raises(ProgrammingError) as exc:
                conn.execute(text(f"TRUNCATE TABLE {table}"))
            assert "permission denied" in str(exc.value)
            conn.rollback()
    finally:
        app_engine.dispose()


@requires_app_role
def test_app_role_cannot_disable_triggers_or_ddl() -> None:
    app_engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    try:
        with app_engine.connect() as conn:
            # Disabling the M021 append-only triggers requires table ownership.
            with pytest.raises(ProgrammingError) as exc:
                conn.execute(text("ALTER TABLE unitmovement DISABLE TRIGGER ALL"))
            assert "must be owner" in str(exc.value)
            conn.rollback()
            # So does any destructive DDL.
            with pytest.raises(ProgrammingError) as exc:
                conn.execute(text("DROP TABLE unitmovement"))
            assert "must be owner" in str(exc.value)
            conn.rollback()
    finally:
        app_engine.dispose()


def test_select_still_allowed_on_ledger(
    db: Session, ledger_ids: dict[str, uuid.UUID]
) -> None:
    # Append-only permits reads (and the seed above already proved INSERT works).
    row = db.execute(
        text("SELECT id FROM unitmovement WHERE id = :id"),
        {"id": str(ledger_ids["unitmovement"])},
    ).first()
    assert row is not None


# --- scheduled CHECK constraints (M021) ---------------------------------------


def _seed_unit_prereqs(db: Session) -> dict[str, uuid.UUID]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    loc = db.exec(select(Location).where(Location.code == "YGN_WH")).first()
    assert loc is not None
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Chk Co")
    )
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"CHK-{uuid.uuid4().hex[:8]}",
            model_name="W",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    return {
        "location_id": loc.id,
        "user_id": user.id,
        "supplier_id": supplier.id,
        "product_id": product.id,
    }


def test_unit_negative_purchase_cost_rejected(db: Session) -> None:
    p = _seed_unit_prereqs(db)
    unit = Unit(
        product_id=p["product_id"],
        supplier_id=p["supplier_id"],
        supplier_serial=f"SN-{uuid.uuid4().hex[:8]}",
        castranova_barcode=f"BC-{uuid.uuid4().hex[:8]}",
        current_state=UnitState.IN_STOCK,
        current_location_id=p["location_id"],
        purchase_cost_thb=Decimal("-1"),
        received_by_user_id=p["user_id"],
    )
    db.add(unit)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


_SALELINE_COLS = frozenset(
    {
        "id",
        "sale_id",
        "line_kind",
        "unit_id",
        "product_id",
        "quantity",
        "unit_price_thb",
        "unit_cost_thb",
        "pricing_override_request_id",
    }
)


def _insert_saleline_raw(db: Session, **cols: object) -> None:
    """Insert a saleline row via raw SQL so model-level validation does not
    pre-empt the DB CHECK we are exercising."""
    assert set(cols) <= _SALELINE_COLS, f"unexpected cols: {set(cols) - _SALELINE_COLS}"
    keys = ", ".join(cols.keys())
    placeholders = ", ".join(f":{k}" for k in cols)
    db.execute(
        text(f"INSERT INTO saleline ({keys}) VALUES ({placeholders})"), cols
    )


def _seed_sale(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Sale Cust")
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
    return sale.id


def test_saleline_negative_unit_cost_rejected(db: Session) -> None:
    sale_id = _seed_sale(db)
    with pytest.raises(IntegrityError):
        _insert_saleline_raw(
            db,
            id=str(uuid.uuid4()),
            sale_id=str(sale_id),
            line_kind="PART",
            product_id=None,
            unit_id=None,
            quantity=1,
            unit_price_thb=Decimal("10.00"),
            unit_cost_thb=Decimal("-1"),
        )
    db.rollback()


def test_saleline_unit_kind_requires_unit_id(db: Session) -> None:
    sale_id = _seed_sale(db)
    with pytest.raises(IntegrityError):
        _insert_saleline_raw(
            db,
            id=str(uuid.uuid4()),
            sale_id=str(sale_id),
            line_kind="UNIT",
            product_id=None,
            unit_id=None,
            quantity=1,
            unit_price_thb=Decimal("10.00"),
            unit_cost_thb=Decimal("5.00"),
        )
    db.rollback()
