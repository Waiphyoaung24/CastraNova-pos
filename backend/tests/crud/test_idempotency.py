import uuid

from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    MovementType,
    ProductCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitMovement,
)


def _seed_unit(db: Session) -> tuple[Unit, uuid.UUID]:
    """Receive one serialized unit; return it and the acting superuser id."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"IDEM-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[ReceivePiece(supplier_serial=f"SN-{uuid.uuid4().hex[:6]}", purchase_cost_thb="900.00")],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    return units[0], user.id


def test_get_or_replay_inserts_once_and_replays(db: Session) -> None:
    unit, user_id = _seed_unit(db)
    key = uuid.uuid4()
    ygn = db.exec(select(Location).where(Location.code == "YGN_WH")).first()
    assert ygn is not None

    def build() -> UnitMovement:
        return UnitMovement(
            unit_id=unit.id,
            event_type=MovementType.SOLD,
            from_location_id=ygn.id,
            actor_user_id=user_id,
            idempotency_key=key,
        )

    stmt = select(UnitMovement).where(UnitMovement.idempotency_key == key)

    obj1, replayed1 = crud.get_or_replay(session=db, statement=stmt, build=build)
    assert replayed1 is False

    obj2, replayed2 = crud.get_or_replay(session=db, statement=stmt, build=build)
    assert replayed2 is True
    assert obj2.id == obj1.id

    # Exactly one row exists for this key.
    db.expire_all()
    rows = db.exec(
        select(UnitMovement).where(UnitMovement.idempotency_key == key)
    ).all()
    assert len(rows) == 1
