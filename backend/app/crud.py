import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.core.security import get_password_hash, verify_password
from app.core.state_machine import (
    IllegalTransition,
    assert_pull_transition,
    assert_unit_transition,
)
from app.models import (
    Channel,
    ChannelMarginReport,
    ChannelMarginRow,
    CostLine,
    Customer,
    CustomerCreate,
    CustomerUpdate,
    LineState,
    Location,
    LowStockItemPublic,
    MovementType,
    NotificationPreference,
    NotificationPreferenceUpdate,
    PartBatch,
    PartMovement,
    PriceChange,
    Product,
    ProductCreate,
    ProductUpdate,
    Project,
    ProjectCreate,
    ProjectPull,
    ProjectPullCreate,
    ProjectPullFulfillLine,
    ProjectPullLine,
    ProjectPullState,
    ProjectUpdate,
    ReceivePiece,
    Sale,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    ServiceTicket,
    ServiceTicketPart,
    Supplier,
    SupplierCreate,
    SupplierUpdate,
    TrackingMode,
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


_T = TypeVar("_T", bound=SQLModel)


def get_or_replay(
    *,
    session: Session,
    statement: SelectOfScalar[_T],
    build: Callable[[], _T],
) -> tuple[_T, bool]:
    """Idempotent single-row insert keyed by UNIQUE(idempotency_key).

    ``statement`` selects the existing row by its idempotency key; ``build``
    constructs the new row. Returns ``(row, replayed)`` — ``replayed`` is True
    when an existing row was returned instead of a fresh insert (offline replay
    or a concurrent writer that won the UNIQUE race). Shared by Sale/Ticket/Pull
    so every offline-originating mutation is replay-safe (spec §7)."""
    existing = session.exec(statement).first()
    if existing is not None:
        return existing, True
    obj = build()
    session.add(obj)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(statement).first()
        if existing is None:
            raise
        return existing, True
    session.refresh(obj)
    return obj, False


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


def _units_by_movement_key(
    *, session: Session, move_keys: list[uuid.UUID]
) -> dict[uuid.UUID, Unit]:
    """Map each existing movement idempotency_key -> its unit (for replay)."""
    movements = session.exec(
        select(UnitMovement).where(col(UnitMovement.idempotency_key).in_(move_keys))
    ).all()
    unit_id_by_key = {m.idempotency_key: m.unit_id for m in movements}
    if not unit_id_by_key:
        return {}
    units = session.exec(
        select(Unit).where(col(Unit.id).in_(list(unit_id_by_key.values())))
    ).all()
    unit_by_id = {u.id: u for u in units}
    return {
        key: unit_by_id[uid]
        for key, uid in unit_id_by_key.items()
        if uid in unit_by_id
    }


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
    # even though unit_movement.idempotency_key is UNIQUE per row. Bound to
    # product_id so the key is collision-free if a request ever spans products.
    move_keys = [
        uuid.uuid5(idempotency_key, f"{product_id}:{p.supplier_serial}")
        for p in pieces
    ]
    replay = _units_by_movement_key(session=session, move_keys=move_keys)
    # Only treat as a replay when *every* piece is already present (the receive
    # commit is atomic, so a partial match means a tampered/foreign row, not a
    # legitimate prior receive — fall through and let UNIQUE catch it).
    if len(replay) == len(move_keys):
        return [replay[key] for key in move_keys]

    state = assert_unit_transition(UnitState.RECEIVED, MovementType.RECEIVED)
    units: list[Unit] = []
    for piece, move_key in zip(pieces, move_keys, strict=True):
        unit = Unit(
            product_id=product_id,
            supplier_id=supplier_id,
            supplier_serial=piece.supplier_serial,
            castranova_barcode="CN-" + uuid.uuid4().hex[:16].upper(),
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
        # Concurrent replay landed first — return its units instead (rollback
        # already expires the in-memory objects we mutated).
        session.rollback()
        replay = _units_by_movement_key(session=session, move_keys=move_keys)
        return [replay[key] for key in move_keys if key in replay]
    for unit in units:
        session.refresh(unit)
    return units


# --- QUANTITY receive + FIFO batch numbering (FR-005/FR-006, §6.4) ------------


def _batch_suffix(batch_no: str) -> int:
    """Numeric tail of a ``...-NNN`` batch_no; 0 if it is not parseable."""
    tail = batch_no.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def next_batch_no(
    *,
    session: Session,
    product_id: uuid.UUID,
    sku: str,
    today: date,
    adj: bool = False,
) -> str:
    """Allocate the next ``YYYYMMDD-{SKU}-[ADJ-]###`` suffix for a product on a
    day. The scan runs under a transaction-scoped 64-bit advisory lock keyed on
    (date, SKU) so two staff receiving the same SKU on the same day get
    sequential suffixes with no collision (S8, §6.4); the lock releases at
    COMMIT/ROLLBACK and ``UNIQUE(product_id, batch_no)`` is the backstop. The
    suffix is the numeric max over *this product's* batches for the day — scoped
    by ``product_id`` + ``is_adjustment`` so a different SKU that shares a
    dash-prefix cannot pollute the sequence, and parsed as an int so it survives
    the 999->1000 digit-width transition a text max would mis-sort. Plain and ADJ
    batches keep independent sequences."""
    yyyymmdd = today.strftime("%Y%m%d")
    session.execute(
        sa_select(
            func.pg_advisory_xact_lock(func.hashtext(yyyymmdd), func.hashtext(sku))
        )
    )
    same_day = session.exec(
        select(PartBatch.batch_no).where(
            PartBatch.product_id == product_id,
            PartBatch.is_adjustment == adj,
            col(PartBatch.batch_no).like(f"{yyyymmdd}-%"),
        )
    ).all()
    suffix = max((_batch_suffix(bn) for bn in same_day), default=0) + 1
    return f"{yyyymmdd}-{sku}-{'ADJ-' if adj else ''}{suffix:03d}"


def _discrepancy_note(
    *, expected_qty: int | None, received_qty: int, note: str | None
) -> str | None:
    """Compose the FR-006 confirmation note (expected vs actual) + staff note."""
    parts: list[str] = []
    if expected_qty is not None and expected_qty != received_qty:
        parts.append(f"Discrepancy: expected {expected_qty}, received {received_qty}.")
    if note:
        parts.append(note)
    return " ".join(parts) if parts else None


def _batch_for_receive_key(
    *, session: Session, idempotency_key: uuid.UUID
) -> PartBatch | None:
    """The batch created by a prior receive with this key (via its RECEIVED
    movement's part_batch_id), or None if this key has not been received yet."""
    prior = session.exec(
        select(PartMovement).where(PartMovement.idempotency_key == idempotency_key)
    ).first()
    if prior is None or prior.part_batch_id is None:
        return None
    return session.get(PartBatch, prior.part_batch_id)


def receive_quantity(
    *,
    session: Session,
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    received_qty: int,
    purchase_cost_thb: Decimal,
    idempotency_key: uuid.UUID,
    received_by_user_id: uuid.UUID,
    supplier_batch_ref: str | None = None,
    expected_qty: int | None = None,
    note: str | None = None,
) -> PartBatch:
    """Receive a QUANTITY batch: one part_batch (``remaining_qty == received_qty``)
    + one RECEIVED part_movement, in one transaction. Idempotent per request —
    replaying the same idempotency_key returns the existing batch without
    inserting duplicates (FR-005, S6). When ``expected_qty`` differs from actual,
    the FR-006 confirmation note is recorded on the movement (no manifest entity,
    §11)."""
    replay = _batch_for_receive_key(session=session, idempotency_key=idempotency_key)
    if replay is not None:
        return replay

    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.tracking_mode != TrackingMode.QUANTITY:
        raise HTTPException(
            status_code=400, detail="Product is not QUANTITY-tracked"
        )
    if not session.get(Supplier, supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    ygn = session.exec(select(Location).where(Location.code == "YGN_WH")).first()
    if not ygn:
        raise HTTPException(status_code=500, detail="YGN_WH location not seeded")

    batch = PartBatch(
        product_id=product_id,
        batch_no=next_batch_no(
            session=session,
            product_id=product_id,
            sku=product.sku,
            today=date.today(),
        ),
        supplier_id=supplier_id,
        supplier_batch_ref=supplier_batch_ref,
        received_qty=received_qty,
        remaining_qty=received_qty,
        purchase_cost_thb=purchase_cost_thb,
        received_by_user_id=received_by_user_id,
    )
    session.add(batch)
    session.flush()  # assign the batch row before the movement FK references it
    session.add(
        PartMovement(
            product_id=product_id,
            event_type=MovementType.RECEIVED,
            quantity=received_qty,
            part_batch_id=batch.id,
            from_location_id=None,
            to_location_id=ygn.id,
            actor_user_id=received_by_user_id,
            idempotency_key=idempotency_key,
            notes=_discrepancy_note(
                expected_qty=expected_qty, received_qty=received_qty, note=note
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # Concurrent replay won the idempotency race — return its batch.
        session.rollback()
        replay = _batch_for_receive_key(
            session=session, idempotency_key=idempotency_key
        )
        if replay is None:
            raise
        return replay
    session.refresh(batch)
    return batch


def consume_quantity_fifo(
    *, session: Session, product_id: uuid.UUID, quantity_needed: int
) -> list[CostLine]:
    """Consume ``quantity_needed`` from a product's QUANTITY batches oldest-first
    (FIFO, §6.3). Candidate batches are locked ``FOR UPDATE`` in deterministic
    receipt order (``received_at, id``) so concurrent consumers acquire locks in
    the same order and cannot deadlock; ``remaining_qty`` is decremented under
    the lock. Returns the per-batch ``CostLine`` rows with ``part_movement_id``
    unset — the caller attaches its consuming movement and commits the whole
    transaction. Raises 409 (no batch mutated) when stock is insufficient (§4.6
    no-negative-stock); rejects a non-positive request with 400."""
    if quantity_needed <= 0:
        raise HTTPException(
            status_code=400, detail="quantity_needed must be positive"
        )
    batches = session.exec(
        select(PartBatch)
        .where(PartBatch.product_id == product_id, col(PartBatch.remaining_qty) > 0)
        .order_by(col(PartBatch.received_at), col(PartBatch.id))
        .with_for_update()
    ).all()
    total_available = sum(b.remaining_qty for b in batches)
    if total_available < quantity_needed:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient stock: have {total_available}, need {quantity_needed}",
        )

    cost_lines: list[CostLine] = []
    remaining = quantity_needed
    for batch in batches:
        if remaining == 0:
            break
        take = min(batch.remaining_qty, remaining)
        batch.remaining_qty -= take
        batch.updated_at = get_datetime_utc()
        session.add(batch)
        cost_lines.append(
            CostLine(
                part_batch_id=batch.id,
                quantity=take,
                unit_cost_thb=batch.purchase_cost_thb,
                total_cost_thb=take * batch.purchase_cost_thb,
            )
        )
        remaining -= take

    # FR-016 low-stock crossing: flag a FRESH downward crossing below the per-SKU
    # threshold (was at/above before, now below). Read-only product fetch + a set
    # insert — no new locks, no change to FIFO/409 semantics. The route pops these
    # post-commit and dispatches a background alert.
    after = total_available - quantity_needed
    product = session.get(Product, product_id)
    threshold = product.default_min_stock_level if product else None
    if threshold is not None and total_available >= threshold and after < threshold:
        session.info.setdefault("low_stock_crossed", set()).add(product_id)

    return cost_lines


def pop_low_stock_crossed(session: Session) -> set[uuid.UUID]:
    """Return and clear the product_ids flagged as crossing below their low-stock
    threshold during this session's consumption (FR-016)."""
    crossed: set[uuid.UUID] = session.info.get("low_stock_crossed", set())
    session.info["low_stock_crossed"] = set()
    return crossed


# --- Low-stock min levels + list (FR-016) -------------------------------------


def _on_hand(session: Session, product: Product) -> int:
    """Current on-hand for a product: sum of batch remaining_qty (QUANTITY) or
    count of IN_STOCK units (SERIALIZED)."""
    if product.tracking_mode == TrackingMode.QUANTITY:
        total = session.exec(
            select(func.coalesce(func.sum(PartBatch.remaining_qty), 0)).where(
                PartBatch.product_id == product.id
            )
        ).one()
        return int(total)
    count = session.exec(
        select(func.count()).where(
            Unit.product_id == product.id,
            Unit.current_state == UnitState.IN_STOCK,
        )
    ).one()
    return int(count)


def list_low_stock(session: Session) -> list[LowStockItemPublic]:
    """Products with a non-null threshold whose on-hand is below it (FR-016)."""
    products = session.exec(
        select(Product).where(col(Product.default_min_stock_level).is_not(None))
    ).all()
    items: list[LowStockItemPublic] = []
    for product in products:
        threshold = product.default_min_stock_level
        if threshold is None:  # WHERE guarantees non-null; explicit guard for -O
            continue
        on_hand = _on_hand(session, product)
        if on_hand < threshold:
            items.append(
                LowStockItemPublic(
                    product_id=product.id,
                    sku=product.sku,
                    model_name=product.model_name,
                    tracking_mode=product.tracking_mode,
                    on_hand=on_hand,
                    min_stock_level=threshold,
                )
            )
    return items


def set_min_stock_level(
    *, session: Session, product_id: uuid.UUID, min_stock_level: int | None
) -> Product:
    """Set (or clear, with None) a product's per-SKU low-stock threshold."""
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.default_min_stock_level = min_stock_level
    product.updated_at = get_datetime_utc()
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def bulk_set_min_stock_level(
    *, session: Session, items: list[tuple[uuid.UUID, int | None]]
) -> list[Product]:
    """Set many per-SKU thresholds in one transaction. 404 if any product is
    missing (whole batch fails, no partial apply)."""
    products: list[Product] = []
    for product_id, level in items:
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(
                status_code=404, detail=f"Product {product_id} not found"
            )
        product.default_min_stock_level = level
        product.updated_at = get_datetime_utc()
        session.add(product)
        products.append(product)
    session.commit()
    for product in products:
        session.refresh(product)
    return products


# --- Serialized sale (FR-007) -------------------------------------------------


def get_sale(*, session: Session, sale_id: Any) -> Sale | None:
    return session.get(Sale, sale_id)


def _sale_by_key(*, session: Session, idempotency_key: uuid.UUID) -> Sale | None:
    return session.exec(
        select(Sale).where(Sale.idempotency_key == idempotency_key)
    ).first()


def create_sale(
    *,
    session: Session,
    customer_id: uuid.UUID,
    lines: list[SaleLineInput],
    idempotency_key: uuid.UUID,
    created_by_user_id: uuid.UUID,
) -> Sale:
    """Sell SERIALIZED units and QUANTITY parts in one transaction (FR-007).

    UNIT lines lock the unit row, assert IN_STOCK -> SOLD, and write a
    unit_movement(SOLD). PART lines FIFO-consume stock (consume_quantity_fifo),
    writing a part_movement(SOLD) + cost_line[] and snapshotting the per-unit
    cost onto the sale_line. Price/cost are snapshotted; everything commits
    atomically. Idempotent on sale.idempotency_key (offline replay returns the
    existing sale, S6)."""
    replay = _sale_by_key(session=session, idempotency_key=idempotency_key)
    if replay is not None:
        return replay

    if not session.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    customer_loc = session.exec(
        select(Location).where(Location.code == "CUSTOMER")
    ).first()
    if not customer_loc:
        raise HTTPException(status_code=500, detail="CUSTOMER location not seeded")

    # Validate every line up front (fail fast, no orphan sale row). UNIT lines
    # carry a barcode; PART lines carry a SKU + positive quantity resolved to a
    # QUANTITY-tracked product.
    barcodes: list[str] = []
    part_reqs: list[tuple[Product, int]] = []
    part_skus: set[str] = set()
    for line in lines:
        if line.line_kind == SaleLineKind.UNIT:
            if not line.castranova_barcode:
                raise HTTPException(
                    status_code=422, detail="UNIT line requires castranova_barcode"
                )
            barcodes.append(line.castranova_barcode)
        else:  # PART
            if not line.sku:
                raise HTTPException(status_code=422, detail="PART line requires sku")
            if line.sku in part_skus:
                raise HTTPException(
                    status_code=422,
                    detail=f"Duplicate PART line for SKU {line.sku}; merge into one",
                )
            part_skus.add(line.sku)
            if line.quantity <= 0:
                raise HTTPException(
                    status_code=422, detail="PART line quantity must be positive"
                )
            product = session.exec(
                select(Product).where(Product.sku == line.sku)
            ).first()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            if product.tracking_mode != TrackingMode.QUANTITY:
                raise HTTPException(
                    status_code=400,
                    detail="PART line requires a QUANTITY-tracked product",
                )
            part_reqs.append((product, line.quantity))

    ygn_loc = None
    if part_reqs:
        ygn_loc = session.exec(
            select(Location).where(Location.code == "YGN_WH")
        ).first()
        if not ygn_loc:
            raise HTTPException(status_code=500, detail="YGN_WH location not seeded")

    # Lock all target units up front in a single canonical (id-ordered) query so
    # concurrent sales/pulls touching overlapping units acquire locks in the same
    # order and cannot deadlock (§7).
    locked = session.exec(
        select(Unit)
        .where(col(Unit.castranova_barcode).in_(barcodes))
        .order_by(col(Unit.id))
        .with_for_update()
    ).all()
    unit_by_barcode = {u.castranova_barcode: u for u in locked}

    sale = Sale(
        customer_id=customer_id,
        created_by_user_id=created_by_user_id,
        idempotency_key=idempotency_key,
        total_thb=Decimal("0.00"),
        total_cogs_thb=Decimal("0.00"),
    )
    session.add(sale)
    session.flush()

    total_thb = Decimal("0.00")
    total_cogs_thb = Decimal("0.00")
    for barcode in barcodes:
        unit = unit_by_barcode.get(barcode)
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")
        try:
            new_state = assert_unit_transition(
                unit.current_state, MovementType.SOLD
            )
        except IllegalTransition:
            raise HTTPException(
                status_code=409,
                detail=f"Unit already {unit.current_state.value}",
            )
        product = session.get(Product, unit.product_id)
        assert product is not None  # FK guarantees existence
        unit_price = product.retail_price_thb  # override hook lands in Part 4
        unit_cost = unit.purchase_cost_thb

        session.add(
            SaleLine(
                sale_id=sale.id,
                line_kind=SaleLineKind.UNIT,
                unit_id=unit.id,
                quantity=1,
                unit_price_thb=unit_price,
                unit_cost_thb=unit_cost,
            )
        )
        session.add(
            UnitMovement(
                unit_id=unit.id,
                event_type=MovementType.SOLD,
                from_location_id=unit.current_location_id,
                to_location_id=customer_loc.id,
                sale_id=sale.id,
                actor_user_id=created_by_user_id,
                idempotency_key=uuid.uuid5(
                    idempotency_key, str(unit.id)
                ),
            )
        )
        unit.current_state = new_state
        unit.current_location_id = customer_loc.id
        unit.updated_at = get_datetime_utc()
        session.add(unit)
        total_thb += unit_price
        total_cogs_thb += unit_cost

    # PART lines: FIFO-consume in deterministic product order (by id) so
    # concurrent sales acquire batch locks in the same order and cannot deadlock
    # (§7). Each line writes one SOLD part_movement + its cost_line[] and snapshots
    # the per-unit average cost onto the sale_line (authoritative COGS stays on
    # cost_line / sale.total_cogs_thb).
    for idx, (product, qty) in enumerate(
        sorted(part_reqs, key=lambda pr: str(pr[0].id))
    ):
        cost_lines = consume_quantity_fifo(
            session=session, product_id=product.id, quantity_needed=qty
        )
        line_cogs = sum((cl.total_cost_thb for cl in cost_lines), Decimal("0.00"))
        movement = PartMovement(
            product_id=product.id,
            event_type=MovementType.SOLD,
            quantity=qty,
            from_location_id=ygn_loc.id if ygn_loc else None,
            to_location_id=customer_loc.id,
            sale_id=sale.id,
            actor_user_id=created_by_user_id,
            idempotency_key=uuid.uuid5(idempotency_key, f"part:{idx}:{product.id}"),
        )
        session.add(movement)
        session.flush()
        for cost_line in cost_lines:
            cost_line.part_movement_id = movement.id
            session.add(cost_line)
        unit_price = product.retail_price_thb  # override hook lands in Part 4
        session.add(
            SaleLine(
                sale_id=sale.id,
                line_kind=SaleLineKind.PART,
                product_id=product.id,
                quantity=qty,
                unit_price_thb=unit_price,
                unit_cost_thb=(line_cogs / qty).quantize(Decimal("0.01")),
            )
        )
        total_thb += unit_price * qty
        total_cogs_thb += line_cogs

    sale.total_thb = total_thb
    sale.total_cogs_thb = total_cogs_thb
    session.add(sale)
    try:
        session.commit()
    except IntegrityError:
        # Lost the idempotency race — return the winner's sale.
        session.rollback()
        # session.info is NOT transactional: discard the low-stock crossings
        # recorded during the rolled-back consume so the route does not dispatch
        # a duplicate alert (the winning request already alerts).
        session.info["low_stock_crossed"] = set()
        winner = _sale_by_key(session=session, idempotency_key=idempotency_key)
        if winner is None:
            raise
        return winner
    session.refresh(sale)
    return sale


# --- Maintenance / service tickets (FR-008) -----------------------------------


def get_service_ticket(
    *, session: Session, ticket_id: Any
) -> ServiceTicket | None:
    return session.get(ServiceTicket, ticket_id)


def list_service_ticket_parts(
    *, session: Session, ticket_id: uuid.UUID
) -> list[ServiceTicketPart]:
    return list(
        session.exec(
            select(ServiceTicketPart).where(
                ServiceTicketPart.service_ticket_id == ticket_id
            )
        ).all()
    )


def open_service_ticket(
    *,
    session: Session,
    customer_id: uuid.UUID,
    issue: str,
    idempotency_key: uuid.UUID,
    created_by_user_id: uuid.UUID,
    notes: str | None = None,
) -> ServiceTicket:
    """Open a maintenance ticket. Idempotent on idempotency_key — replaying an
    offline ticket-open returns the existing ticket without re-validating (FR-008,
    S6). Customer existence is only checked on a genuine create."""
    existing = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.idempotency_key == idempotency_key
        )
    ).first()
    if existing is not None:
        return existing
    if not session.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    ticket, _ = get_or_replay(
        session=session,
        statement=select(ServiceTicket).where(
            ServiceTicket.idempotency_key == idempotency_key
        ),
        build=lambda: ServiceTicket(
            customer_id=customer_id,
            issue=issue,
            notes=notes,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key,
        ),
    )
    return ticket


def add_service_ticket_part(
    *,
    session: Session,
    ticket_id: uuid.UUID,
    sku: str,
    quantity: int,
    unit_price_thb: Decimal | None = None,
) -> ServiceTicketPart:
    """Add a part line to an open ticket. Price defaults to the product's
    repair_price_thb unless an override is supplied (FR-008 / Flow C.3). Rejected
    once the ticket is closed (its parts are immutable then). The ticket row is
    locked FOR UPDATE so this serializes against a concurrent close — a part can
    never be inserted into a ticket that close has already consumed."""
    ticket = session.exec(
        select(ServiceTicket)
        .where(ServiceTicket.id == ticket_id)
        .with_for_update()
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Service ticket not found")
    if ticket.closed_at is not None:
        raise HTTPException(status_code=409, detail="Service ticket is closed")
    product = session.exec(select(Product).where(Product.sku == sku)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.tracking_mode != TrackingMode.QUANTITY:
        raise HTTPException(
            status_code=400, detail="Service part requires a QUANTITY-tracked product"
        )
    part = ServiceTicketPart(
        service_ticket_id=ticket.id,
        product_id=product.id,
        quantity=quantity,
        unit_price_thb=(
            unit_price_thb if unit_price_thb is not None else product.repair_price_thb
        ),
    )
    session.add(part)
    session.commit()
    session.refresh(part)
    return part


def close_service_ticket(
    *,
    session: Session,
    ticket_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    resolution: str | None = None,
) -> ServiceTicket:
    """Close a ticket: FIFO-consume each part line, writing one
    part_movement(MAINTENANCE_OUT) + cost_line[] per line, and stamp closed_at —
    all in one transaction (Flow C.4). The ticket row is locked FOR UPDATE and a
    re-close is idempotent (already-closed tickets return unchanged, never
    re-consume). 409 on insufficient stock leaves the ticket open."""
    ticket = session.exec(
        select(ServiceTicket)
        .where(ServiceTicket.id == ticket_id)
        .with_for_update()
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Service ticket not found")
    if ticket.closed_at is not None:
        return ticket  # idempotent: already closed, do not re-consume

    customer_loc = session.exec(
        select(Location).where(Location.code == "CUSTOMER")
    ).first()
    ygn_loc = session.exec(
        select(Location).where(Location.code == "YGN_WH")
    ).first()
    if not customer_loc or not ygn_loc:
        raise HTTPException(status_code=500, detail="Locations not seeded")

    parts = session.exec(
        select(ServiceTicketPart).where(
            ServiceTicketPart.service_ticket_id == ticket_id
        )
    ).all()
    # Consume in deterministic product order so concurrent consumption (across
    # tickets/sales) acquires batch locks in the same order and cannot deadlock.
    for part in sorted(parts, key=lambda p: str(p.product_id)):
        cost_lines = consume_quantity_fifo(
            session=session,
            product_id=part.product_id,
            quantity_needed=part.quantity,
        )
        movement = PartMovement(
            product_id=part.product_id,
            event_type=MovementType.MAINTENANCE_OUT,
            quantity=part.quantity,
            from_location_id=ygn_loc.id,
            to_location_id=customer_loc.id,
            service_ticket_id=ticket.id,
            actor_user_id=actor_user_id,
            idempotency_key=uuid.uuid5(ticket.id, f"maint:{part.id}"),
        )
        session.add(movement)
        session.flush()
        for cost_line in cost_lines:
            cost_line.part_movement_id = movement.id
            session.add(cost_line)

    ticket.closed_at = get_datetime_utc()
    if resolution is not None:
        ticket.resolution = resolution
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


# --- Project pull (FR-009; Flow D) --------------------------------------------


def get_project_pull(
    *, session: Session, pull_id: Any
) -> ProjectPull | None:
    return session.get(ProjectPull, pull_id)


def list_project_pull_lines(
    *, session: Session, pull_id: uuid.UUID
) -> list[ProjectPullLine]:
    return list(
        session.exec(
            select(ProjectPullLine)
            .where(ProjectPullLine.project_pull_id == pull_id)
            .order_by(col(ProjectPullLine.id))
        ).all()
    )


def list_project_pulls(
    *,
    session: Session,
    state: ProjectPullState | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[ProjectPull]:
    """List pulls newest-first, optionally filtered by state (the staff queue
    uses ``state=PENDING``; the (state, created_at) index serves it)."""
    statement = select(ProjectPull)
    if state is not None:
        statement = statement.where(ProjectPull.state == state)
    statement = (
        statement.order_by(col(ProjectPull.created_at).desc()).offset(skip).limit(limit)
    )
    return list(session.exec(statement).all())


def create_project_pull(
    *,
    session: Session,
    pull_in: ProjectPullCreate,
    created_by_user_id: uuid.UUID,
) -> ProjectPull:
    """Admin creates a PENDING pull + its lines in one transaction (Flow D.1).

    customer_id is denormalised from the project. Each UNIT line requires a
    unit_serial on a SERIALIZED product; each PART line requires requested_qty on
    a QUANTITY product. 404 on a missing project/product, 400 on a tracking_mode
    mismatch, 422 on a malformed line."""
    project = session.get(Project, pull_in.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pull = ProjectPull(
        project_id=project.id,
        customer_id=project.customer_id,
        admin_notes=pull_in.admin_notes,
        created_by_user_id=created_by_user_id,
    )
    session.add(pull)
    session.flush()

    for line in pull_in.lines:
        product = session.get(Product, line.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        if line.line_kind == SaleLineKind.UNIT:
            if not line.unit_serial:
                raise HTTPException(
                    status_code=422, detail="UNIT line requires unit_serial"
                )
            if product.tracking_mode != TrackingMode.SERIALIZED:
                raise HTTPException(
                    status_code=400,
                    detail="UNIT line requires a SERIALIZED product",
                )
        else:  # PART
            if line.requested_qty is None or line.requested_qty <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="PART line requires a positive requested_qty",
                )
            if product.tracking_mode != TrackingMode.QUANTITY:
                raise HTTPException(
                    status_code=400,
                    detail="PART line requires a QUANTITY-tracked product",
                )
        session.add(
            ProjectPullLine(
                project_pull_id=pull.id,
                line_kind=line.line_kind,
                product_id=product.id,
                unit_serial=line.unit_serial,
                requested_qty=line.requested_qty,
            )
        )

    session.commit()
    session.refresh(pull)
    return pull


def fulfill_project_pull(
    *,
    session: Session,
    pull_id: uuid.UUID,
    fulfill_lines: list[ProjectPullFulfillLine],
    actor_user_id: uuid.UUID,
) -> ProjectPull:
    """Staff fulfills a PENDING pull at the warehouse (Flow D.2), consuming
    SERIALIZED units (PROJECT_OUT) and QUANTITY parts (FIFO), cost-only.

    One-shot and PENDING-only: the pull is locked FOR UPDATE; a FULFILLED/SHORT
    pull returns unchanged (idempotent — never re-consume), a CANCELLED pull
    raises 409. Per line the requested amount defaults from the line (UNIT->1,
    PART->requested_qty) unless overridden in ``fulfill_lines``. UNIT lines that
    lost the race (missing/not IN_STOCK) become SHORT with no movement; PART
    lines fulfilled below request become SHORT. The pull settles FULFILLED iff
    every line is FULFILLED, else SHORT — all atomic with the movement writes
    (409 on insufficient stock rolls the whole thing back)."""
    pull = session.exec(
        select(ProjectPull)
        .where(ProjectPull.id == pull_id)
        .with_for_update()
    ).first()
    if not pull:
        raise HTTPException(status_code=404, detail="Project pull not found")
    if pull.state == ProjectPullState.CANCELLED:
        raise HTTPException(status_code=409, detail="Project pull is cancelled")
    if pull.state != ProjectPullState.PENDING:
        return pull  # idempotent: already settled (FULFILLED/SHORT), do not re-consume

    customer_loc = session.exec(
        select(Location).where(Location.code == "CUSTOMER")
    ).first()
    ygn_loc = session.exec(
        select(Location).where(Location.code == "YGN_WH")
    ).first()
    if not customer_loc or not ygn_loc:
        raise HTTPException(status_code=500, detail="Locations not seeded")

    lines = session.exec(
        select(ProjectPullLine)
        .where(ProjectPullLine.project_pull_id == pull.id)
        .order_by(col(ProjectPullLine.id))
    ).all()

    # Validate payload line_ids before any write so a bad payload aborts the
    # whole transaction cleanly (nothing consumed/moved).
    payload_ids = [fl.line_id for fl in fulfill_lines]
    if len(payload_ids) != len(set(payload_ids)):
        dupes = {lid for lid in payload_ids if payload_ids.count(lid) > 1}
        raise HTTPException(
            status_code=422, detail=f"Duplicate line_id in payload: {dupes}"
        )
    known_ids = {ln.id for ln in lines}
    unknown = set(payload_ids) - known_ids
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unknown line_id for this pull: {unknown}"
        )
    qty_by_line = {fl.line_id: fl.fulfilled_qty for fl in fulfill_lines}

    # Lock all target units up front in a single canonical (id-ordered) query so
    # concurrent sales/pulls touching overlapping units acquire locks in the same
    # order and cannot deadlock (§7).
    unit_serials = [
        ln.unit_serial
        for ln in lines
        if ln.line_kind == SaleLineKind.UNIT and ln.unit_serial
    ]
    unit_by_barcode: dict[str, Unit] = {}
    if unit_serials:
        locked = session.exec(
            select(Unit)
            .where(col(Unit.castranova_barcode).in_(unit_serials))
            .order_by(col(Unit.id))
            .with_for_update()
        ).all()
        unit_by_barcode = {u.castranova_barcode: u for u in locked}

    # UNIT lines first, then PART lines in deterministic product order so
    # concurrent consumers acquire batch locks in the same order (§7).
    unit_lines = [ln for ln in lines if ln.line_kind == SaleLineKind.UNIT]
    part_lines = sorted(
        (ln for ln in lines if ln.line_kind == SaleLineKind.PART),
        key=lambda ln: str(ln.product_id),
    )

    for line in unit_lines:
        requested = qty_by_line.get(line.id, 1)
        unit = unit_by_barcode.get(line.unit_serial) if line.unit_serial else None
        if requested < 1 or unit is None:
            line.line_state = LineState.SHORT
            line.fulfilled_qty = 0
            session.add(line)
            continue
        try:
            new_state = assert_unit_transition(
                unit.current_state, MovementType.PROJECT_OUT
            )
        except IllegalTransition:
            # Lost the race (already SOLD/PROJECT_OUT/etc.) — first-write-wins.
            line.line_state = LineState.SHORT
            line.fulfilled_qty = 0
            session.add(line)
            continue
        session.add(
            UnitMovement(
                unit_id=unit.id,
                event_type=MovementType.PROJECT_OUT,
                from_location_id=unit.current_location_id,
                to_location_id=customer_loc.id,
                project_pull_id=pull.id,
                actor_user_id=actor_user_id,
                idempotency_key=uuid.uuid5(pull.id, f"unit:{line.id}"),
            )
        )
        unit.current_state = new_state
        unit.current_location_id = customer_loc.id
        unit.updated_at = get_datetime_utc()
        session.add(unit)
        line.line_state = LineState.FULFILLED
        line.fulfilled_qty = 1
        session.add(line)

    for line in part_lines:
        requested_qty = line.requested_qty or 0
        wanted = qty_by_line.get(line.id, requested_qty)
        actual = min(wanted, requested_qty)
        if actual <= 0:
            line.line_state = LineState.SHORT
            line.fulfilled_qty = 0
            session.add(line)
            continue
        cost_lines = consume_quantity_fifo(
            session=session, product_id=line.product_id, quantity_needed=actual
        )
        movement = PartMovement(
            product_id=line.product_id,
            event_type=MovementType.PROJECT_OUT,
            quantity=actual,
            from_location_id=ygn_loc.id,
            to_location_id=customer_loc.id,
            project_pull_id=pull.id,
            actor_user_id=actor_user_id,
            idempotency_key=uuid.uuid5(pull.id, f"part:{line.id}"),
        )
        session.add(movement)
        session.flush()
        for cost_line in cost_lines:
            cost_line.part_movement_id = movement.id
            session.add(cost_line)
        line.line_state = (
            LineState.FULFILLED if actual == requested_qty else LineState.SHORT
        )
        line.fulfilled_qty = actual
        session.add(line)

    all_fulfilled = all(ln.line_state == LineState.FULFILLED for ln in lines)
    target = ProjectPullState.FULFILLED if all_fulfilled else ProjectPullState.SHORT
    pull.state = assert_pull_transition(pull.state, target)
    pull.fulfilled_at = get_datetime_utc()
    pull.fulfilled_by_user_id = actor_user_id
    session.add(pull)
    # FR-018: notifying admins on a SHORT pull is a post-commit side effect
    # triggered in the fulfill route (kept out of this consumption transaction).
    session.commit()
    session.refresh(pull)
    return pull


def cancel_project_pull(
    *,
    session: Session,
    pull_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> ProjectPull:
    """Admin cancels a PENDING or SHORT pull (Flow D.3): mark CANCELLED, flip
    still-PENDING lines to CANCELLED, write no movements. The pull is locked FOR
    UPDATE; an already-CANCELLED pull returns unchanged (idempotent); a FULFILLED
    pull raises 409."""
    pull = session.exec(
        select(ProjectPull)
        .where(ProjectPull.id == pull_id)
        .with_for_update()
    ).first()
    if not pull:
        raise HTTPException(status_code=404, detail="Project pull not found")
    if pull.state == ProjectPullState.CANCELLED:
        return pull  # idempotent
    if pull.state == ProjectPullState.FULFILLED:
        raise HTTPException(
            status_code=409, detail="Cannot cancel a fulfilled pull"
        )

    pull.state = assert_pull_transition(pull.state, ProjectPullState.CANCELLED)
    pull.cancelled_at = get_datetime_utc()
    pull.cancelled_by_user_id = actor_user_id
    session.add(pull)

    lines = session.exec(
        select(ProjectPullLine).where(ProjectPullLine.project_pull_id == pull.id)
    ).all()
    for line in lines:
        if line.line_state == LineState.PENDING:
            line.line_state = LineState.CANCELLED
            session.add(line)

    session.commit()
    session.refresh(pull)
    return pull


def list_notification_preferences(
    *, session: Session, user_id: uuid.UUID
) -> list[NotificationPreference]:
    """Return a user's notification preferences (FR-018)."""
    return list(
        session.exec(
            select(NotificationPreference)
            .where(NotificationPreference.user_id == user_id)
            .order_by(col(NotificationPreference.id))
        ).all()
    )


def upsert_notification_preferences(
    *,
    session: Session,
    user_id: uuid.UUID,
    updates: list[NotificationPreferenceUpdate],
) -> list[NotificationPreference]:
    """Insert-or-update each (channel, event_type) opt-in for the user, then
    return the user's full preference list. Idempotent."""
    for upd in updates:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.channel == upd.channel,
            NotificationPreference.event_type == upd.event_type,
        )
        existing = session.exec(stmt).first()
        if existing:
            existing.enabled = upd.enabled
            existing.updated_at = get_datetime_utc()
            session.add(existing)
            session.flush()
        else:
            session.add(
                NotificationPreference(
                    user_id=user_id,
                    channel=upd.channel,
                    event_type=upd.event_type,
                    enabled=upd.enabled,
                )
            )
            try:
                # Flush per-row so a concurrent insert racing the
                # UNIQUE(user_id, channel, event_type) is isolated to this row.
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.exec(stmt).first()
                if existing is None:
                    raise
                existing.enabled = upd.enabled
                existing.updated_at = get_datetime_utc()
                session.add(existing)
                session.flush()
    session.commit()
    return list_notification_preferences(session=session, user_id=user_id)


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


# --- Channel-margin report (FR-013) -------------------------------------------

_CENT = Decimal("0.01")


def _q(value: Decimal | int) -> Decimal:
    """Quantize a money sum to cents."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def channel_margin_report(
    *, session: Session, year: int, month: int
) -> ChannelMarginReport:
    """Monthly revenue / COGS / margin by derived channel (SALE, MAINTENANCE,
    PROJECT), read-only (FR-013, spec §8). Channel is derived from each source
    record's own timestamp (sale.sold_at / service_ticket.closed_at /
    project_pull.fulfilled_at) falling in [month_start, next_month_start) UTC.
    COGS is the full snapshot: SALE uses sale.total_cogs_thb (already includes
    serialized-unit + part cost); PROJECT adds pulled unit.purchase_cost_thb to
    the part FIFO cost. All sums are set-based; amounts quantized to cents."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    # --- SALE: sales sold_at in window. ---
    sale_rev, sale_cogs = session.exec(
        select(
            func.coalesce(func.sum(Sale.total_thb), Decimal("0")),
            func.coalesce(func.sum(Sale.total_cogs_thb), Decimal("0")),
        ).where(col(Sale.sold_at) >= start, col(Sale.sold_at) < end)
    ).one()

    # --- MAINTENANCE: parts of tickets closed in window. ---
    maint_rev = session.exec(
        select(
            func.coalesce(
                func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb),
                Decimal("0"),
            )
        )
        .join(
            ServiceTicket,
            col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id),
        )
        .where(col(ServiceTicket.closed_at) >= start, col(ServiceTicket.closed_at) < end)
    ).one()
    maint_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(
            ServiceTicket,
            col(PartMovement.service_ticket_id) == col(ServiceTicket.id),
        )
        .where(
            PartMovement.event_type == MovementType.MAINTENANCE_OUT,
            col(ServiceTicket.closed_at) >= start,
            col(ServiceTicket.closed_at) < end,
        )
    ).one()

    # --- PROJECT (cost-only): pulls fulfilled in window. ---
    proj_part_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(
            PartMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.fulfilled_at) >= start,
            col(ProjectPull.fulfilled_at) < end,
        )
    ).one()
    proj_unit_cogs = session.exec(
        select(func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")))
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(
            UnitMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.fulfilled_at) >= start,
            col(ProjectPull.fulfilled_at) < end,
        )
    ).one()

    rows = [
        (Channel.SALE, _q(sale_rev), _q(sale_cogs)),
        (Channel.MAINTENANCE, _q(maint_rev), _q(maint_cogs)),
        (Channel.PROJECT, _q(0), _q(proj_part_cogs + proj_unit_cogs)),
    ]
    channels = [
        ChannelMarginRow(
            channel=ch, revenue_thb=rev, cogs_thb=cogs, margin_thb=rev - cogs
        )
        for ch, rev, cogs in rows
    ]
    total_rev = sum((r.revenue_thb for r in channels), Decimal("0.00"))
    total_cogs = sum((r.cogs_thb for r in channels), Decimal("0.00"))
    return ChannelMarginReport(
        month=f"{year:04d}-{month:02d}",
        channels=channels,
        total_revenue_thb=total_rev,
        total_cogs_thb=total_cogs,
        total_margin_thb=total_rev - total_cogs,
    )
