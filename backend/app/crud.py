import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.security import get_password_hash, verify_password
from app.core.state_machine import assert_unit_transition
from app.models import (
    Customer,
    CustomerCreate,
    CustomerUpdate,
    Location,
    MovementType,
    PriceChange,
    Product,
    ProductCreate,
    ProductUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    ReceivePiece,
    Supplier,
    SupplierCreate,
    SupplierUpdate,
    Unit,
    UnitMovement,
    UnitState,
    User,
    UserCreate,
    UserUpdate,
    get_datetime_utc,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def seed_locations(*, session: Session) -> None:
    """Idempotently seed the fixed warehouse + virtual locations."""
    seeds = [
        ("YGN_WH", "Yangon Warehouse"),
        ("CUSTOMER", "Customer (virtual)"),
        ("ADJUSTED_OUT", "Adjusted Out (virtual)"),
    ]
    for code, name in seeds:
        if not session.exec(select(Location).where(Location.code == code)).first():
            session.add(Location(code=code, name=name))
    session.commit()


# --- Supplier -----------------------------------------------------------------


def create_supplier(*, session: Session, supplier_in: SupplierCreate) -> Supplier:
    db_obj = Supplier.model_validate(supplier_in)
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def get_supplier(*, session: Session, supplier_id: Any) -> Supplier | None:
    return session.get(Supplier, supplier_id)


def list_suppliers(
    *, session: Session, skip: int = 0, limit: int = 100
) -> list[Supplier]:
    return list(session.exec(select(Supplier).offset(skip).limit(limit)).all())


def update_supplier(
    *, session: Session, db_supplier: Supplier, supplier_in: SupplierUpdate
) -> Supplier:
    db_supplier.sqlmodel_update(supplier_in.model_dump(exclude_unset=True))
    db_supplier.updated_at = get_datetime_utc()
    session.add(db_supplier)
    session.commit()
    session.refresh(db_supplier)
    return db_supplier


# --- Customer -----------------------------------------------------------------


def create_customer(*, session: Session, customer_in: CustomerCreate) -> Customer:
    db_obj = Customer.model_validate(customer_in)
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def get_customer(*, session: Session, customer_id: Any) -> Customer | None:
    return session.get(Customer, customer_id)


def list_customers(
    *, session: Session, skip: int = 0, limit: int = 100
) -> list[Customer]:
    return list(session.exec(select(Customer).offset(skip).limit(limit)).all())


def update_customer(
    *, session: Session, db_customer: Customer, customer_in: CustomerUpdate
) -> Customer:
    db_customer.sqlmodel_update(customer_in.model_dump(exclude_unset=True))
    db_customer.updated_at = get_datetime_utc()
    session.add(db_customer)
    session.commit()
    session.refresh(db_customer)
    return db_customer


# --- Project ------------------------------------------------------------------


def create_project(*, session: Session, project_in: ProjectCreate) -> Project:
    if not session.get(Customer, project_in.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    db_obj = Project.model_validate(project_in)
    session.add(db_obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project code already exists")
    session.refresh(db_obj)
    return db_obj


def get_project(*, session: Session, project_id: Any) -> Project | None:
    return session.get(Project, project_id)


def list_projects(
    *, session: Session, skip: int = 0, limit: int = 100
) -> list[Project]:
    return list(session.exec(select(Project).offset(skip).limit(limit)).all())


def update_project(
    *, session: Session, db_project: Project, project_in: ProjectUpdate
) -> Project:
    db_project.sqlmodel_update(project_in.model_dump(exclude_unset=True))
    db_project.updated_at = get_datetime_utc()
    session.add(db_project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project code already exists")
    session.refresh(db_project)
    return db_project


# --- Product + price history --------------------------------------------------

_PRICE_FIELDS = ("retail_price_thb", "repair_price_thb")


def create_product(*, session: Session, product_in: ProductCreate) -> Product:
    db_obj = Product.model_validate(product_in)
    session.add(db_obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists")
    session.refresh(db_obj)
    return db_obj


def get_product(*, session: Session, product_id: Any) -> Product | None:
    return session.get(Product, product_id)


def list_products(
    *, session: Session, skip: int = 0, limit: int = 100
) -> list[Product]:
    return list(session.exec(select(Product).offset(skip).limit(limit)).all())


def update_product(
    *,
    session: Session,
    db_product: Product,
    product_in: ProductUpdate,
    changed_by_user_id: uuid.UUID,
) -> Product:
    data = product_in.model_dump(exclude_unset=True)
    # Record a price_change row for each price field that actually changes (FR-002),
    # in the same transaction as the product update.
    for field in _PRICE_FIELDS:
        new_value = data.get(field)
        if new_value is not None and new_value != getattr(db_product, field):
            session.add(
                PriceChange(
                    product_id=db_product.id,
                    field=field,
                    old_value=getattr(db_product, field),
                    new_value=new_value,
                    changed_by_user_id=changed_by_user_id,
                )
            )
    db_product.sqlmodel_update(data)
    db_product.updated_at = get_datetime_utc()
    session.add(db_product)
    session.commit()
    session.refresh(db_product)
    return db_product


def list_price_history(*, session: Session, product_id: Any) -> list[PriceChange]:
    return list(
        session.exec(
            select(PriceChange)
            .where(PriceChange.product_id == product_id)
            .order_by(col(PriceChange.changed_at).desc())
        ).all()
    )


# --- Serialized receive (FR-005) ----------------------------------------------


def get_unit(*, session: Session, unit_id: Any) -> Unit | None:
    return session.get(Unit, unit_id)


def _units_for_movement_keys(
    *, session: Session, move_keys: list[uuid.UUID]
) -> list[Unit]:
    existing = session.exec(
        select(UnitMovement).where(col(UnitMovement.idempotency_key).in_(move_keys))
    ).all()
    unit_ids = [m.unit_id for m in existing]
    if not unit_ids:
        return []
    return list(session.exec(select(Unit).where(col(Unit.id).in_(unit_ids))).all())


def receive_serialized(
    *,
    session: Session,
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    pieces: list[ReceivePiece],
    idempotency_key: uuid.UUID,
    received_by_user_id: uuid.UUID,
) -> list[Unit]:
    """Receive SERIALIZED pieces: one unit + one RECEIVED movement each, in one
    transaction. Idempotent per request — replaying the same idempotency_key
    returns the already-created units without inserting duplicates (FR-005, S5)."""
    if not session.get(Product, product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    if not session.get(Supplier, supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    ygn = session.exec(select(Location).where(Location.code == "YGN_WH")).first()
    if not ygn:
        raise HTTPException(status_code=500, detail="YGN_WH location not seeded")

    # Deterministic per-piece movement key so the whole request is replay-safe
    # even though unit_movement.idempotency_key is UNIQUE per row.
    move_keys = [
        uuid.uuid5(idempotency_key, p.supplier_serial) for p in pieces
    ]
    replay = _units_for_movement_keys(session=session, move_keys=move_keys)
    if replay:
        return replay

    state = assert_unit_transition(UnitState.RECEIVED, MovementType.RECEIVED)
    units: list[Unit] = []
    for piece, move_key in zip(pieces, move_keys, strict=True):
        unit = Unit(
            product_id=product_id,
            supplier_id=supplier_id,
            supplier_serial=piece.supplier_serial,
            castranova_barcode="CN-" + uuid.uuid4().hex[:10].upper(),
            current_state=state,
            current_location_id=ygn.id,
            purchase_cost_thb=piece.purchase_cost_thb,
            received_by_user_id=received_by_user_id,
        )
        session.add(unit)
        session.flush()
        session.add(
            UnitMovement(
                unit_id=unit.id,
                event_type=MovementType.RECEIVED,
                from_location_id=None,
                to_location_id=ygn.id,
                actor_user_id=received_by_user_id,
                idempotency_key=move_key,
            )
        )
        units.append(unit)
    try:
        session.commit()
    except IntegrityError:
        # Concurrent replay landed first — return its units instead.
        session.rollback()
        return _units_for_movement_keys(session=session, move_keys=move_keys)
    for unit in units:
        session.refresh(unit)
    return units


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user
