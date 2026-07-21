import secrets
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, TypeVar, cast

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Select, case, func, or_
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
    AdjustmentTarget,
    AuditEntryPublic,
    BatchDrillRow,
    Channel,
    CostLine,
    Customer,
    CustomerCreate,
    CustomerOption,
    CustomerType,
    CustomerUpdate,
    HoldingPeriodReport,
    HoldingPeriodRow,
    LineState,
    Location,
    LowStockItemPublic,
    MarginBreakdownReport,
    MarginBreakdownRow,
    MarginDimension,
    MovementType,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationPreferencePublic,
    NotificationPreferenceUpdate,
    OverrideExceptionRow,
    OverrideExceptionsReport,
    OverrideState,
    OverrideTargetKind,
    PartBatch,
    PartMovement,
    PriceChange,
    PricingOverrideCreate,
    PricingOverrideRequest,
    Product,
    ProductCreate,
    ProductOption,
    ProductUpdate,
    Project,
    ProjectCreate,
    ProjectOption,
    ProjectPull,
    ProjectPullCreate,
    ProjectPullFulfillLine,
    ProjectPullLine,
    ProjectPullState,
    ProjectStatus,
    ProjectUpdate,
    ReceivePiece,
    Sale,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SerialMovementPublic,
    SerialSearchResult,
    ServiceTicket,
    ServiceTicketPart,
    ServiceTicketPartCreate,
    SkuBatchAdminPublic,
    SkuBatchPublic,
    SkuConsumptionDrawAdminPublic,
    SkuConsumptionEventAdminPublic,
    SkuConsumptionEventPublic,
    SkuSearchAdminResult,
    SkuSearchResult,
    StockAdjustment,
    StockAdjustmentCreate,
    StockOnHandResponse,
    StockOnHandRow,
    Supplier,
    SupplierCreate,
    SupplierOption,
    SupplierUpdate,
    SyncReviewItem,
    SyncReviewItemCreate,
    SyncReviewState,
    SystemSetting,
    TelegramConfirmOutcome,
    TelegramConnectCode,
    TrackingMode,
    Unit,
    UnitDrillRow,
    UnitMovement,
    UnitState,
    User,
    UserCreate,
    UserOption,
    UserUpdate,
    channel_connected,
    eligible_events,
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


def count_active_superusers(*, session: Session) -> int:
    """Number of users who can still log in with superuser access. Used to block
    demoting/deactivating the last one (which would lock everyone out of user
    management).

    Locks the matching rows with FOR UPDATE so two concurrent demotions of the
    last two superusers serialize instead of both reading 2 and racing to zero
    (FOR UPDATE can't apply to a bare COUNT aggregate, so we lock+count rows)."""
    statement = (
        select(User.id)
        .where(col(User.is_superuser).is_(True), col(User.is_active).is_(True))
        .with_for_update()
    )
    return len(session.exec(statement).all())


def list_user_options(*, session: Session) -> list[UserOption]:
    rows = session.exec(
        select(col(User.id), col(User.full_name), col(User.email)).order_by(
            func.coalesce(col(User.full_name), col(User.email))
        )
    ).all()
    return [UserOption(id=row[0], full_name=row[1], email=row[2]) for row in rows]


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


def _assert_replay_actor(
    *, stored_user_id: uuid.UUID, caller_user_id: uuid.UUID
) -> None:
    """Same-key replays must come from the original actor (spec §6.6 addendum).

    Client idempotency keys are 122-bit UUIDs; a same-key/different-user hit is
    a stolen/duplicated key, never a legitimate offline retry.
    """
    if stored_user_id != caller_user_id:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used by a different user.",
        )


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


# --- System settings (singleton key/jsonb store; §4.2 row 8) ------------------

OVERRIDE_THRESHOLD_KEY = "override_deviation_threshold_pct"
# JSONB-seeded; read back as Decimal via Decimal(str(...)) at the read site.
DEFAULT_OVERRIDE_THRESHOLD_PCT: float = 5.0
HOLDING_THRESHOLD_KEY = "holding_period_threshold_days"
DEFAULT_HOLDING_THRESHOLD_DAYS = 90


def get_setting(*, session: Session, key: str, default: Any = None) -> Any:
    row = session.exec(
        select(SystemSetting).where(SystemSetting.key == key)
    ).first()
    return row.value if row else default


def set_setting(
    *,
    session: Session,
    key: str,
    value: Any,
    updated_by_user_id: uuid.UUID | None = None,
) -> SystemSetting:
    row = session.exec(
        select(SystemSetting).where(SystemSetting.key == key)
    ).first()
    if row:
        row.value = value
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = get_datetime_utc()
    else:
        row = SystemSetting(
            key=key, value=value, updated_by_user_id=updated_by_user_id
        )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def seed_system_settings(*, session: Session) -> None:
    """Idempotently seed the default configurable thresholds."""
    defaults: list[tuple[str, Any]] = [
        (OVERRIDE_THRESHOLD_KEY, DEFAULT_OVERRIDE_THRESHOLD_PCT),
        (HOLDING_THRESHOLD_KEY, DEFAULT_HOLDING_THRESHOLD_DAYS),
    ]
    for key, value in defaults:
        if not session.exec(
            select(SystemSetting).where(SystemSetting.key == key)
        ).first():
            session.add(SystemSetting(key=key, value=value))
    session.commit()


def _ilike_term(q: str) -> str:
    """Escape LIKE wildcards in user input before wrapping it as `%q%`.

    Without this, a literal `%` or `_` typed into a catalog search box would
    be interpreted as a SQL wildcard instead of a literal character.
    """
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --- Supplier -----------------------------------------------------------------


def create_supplier(*, session: Session, supplier_in: SupplierCreate) -> Supplier:
    db_obj = Supplier.model_validate(supplier_in)
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def get_supplier(*, session: Session, supplier_id: uuid.UUID) -> Supplier | None:
    return session.get(Supplier, supplier_id)


_S = TypeVar("_S", bound=Select[Any])


def _supplier_where(stmt: _S, *, q: str | None, country: str | None) -> _S:
    if q and q.strip():
        stmt = stmt.where(col(Supplier.name).ilike(_ilike_term(q.strip()), escape="\\"))
    if country and country.strip():
        stmt = stmt.where(col(Supplier.country) == country.strip())
    return stmt


def list_suppliers(
    *,
    session: Session,
    q: str | None = None,
    country: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Supplier]:
    stmt = _supplier_where(select(Supplier), q=q, country=country)
    stmt = (
        stmt.order_by(col(Supplier.created_at).desc().nulls_last(), col(Supplier.id))
        .offset(skip)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def list_supplier_options(*, session: Session) -> list[SupplierOption]:
    rows = session.exec(
        select(col(Supplier.id), col(Supplier.name)).order_by(col(Supplier.name))
    ).all()
    return [SupplierOption(id=row[0], name=row[1]) for row in rows]


def list_supplier_countries(*, session: Session) -> list[str]:
    rows = session.exec(
        select(col(Supplier.country))
        .where(col(Supplier.country).is_not(None))
        .distinct()
        .order_by(col(Supplier.country))
    ).all()
    return [row for row in rows if row]


def count_suppliers(
    *, session: Session, q: str | None = None, country: str | None = None
) -> int:
    stmt = _supplier_where(
        select(func.count()).select_from(Supplier), q=q, country=country
    )
    return session.exec(stmt).one()


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


def get_customer(*, session: Session, customer_id: uuid.UUID) -> Customer | None:
    return session.get(Customer, customer_id)


def _customer_filter_clauses(
    *, q: str | None, country: str | None, type: CustomerType | None
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if q and q.strip():
        clauses.append(col(Customer.name).ilike(_ilike_term(q.strip()), escape="\\"))
    if country and country.strip():
        clauses.append(col(Customer.country) == country.strip())
    if type is not None:
        clauses.append(col(Customer.type) == type)
    return clauses


def list_customers(
    *,
    session: Session,
    q: str | None = None,
    country: str | None = None,
    type: CustomerType | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Customer]:
    stmt = select(Customer)
    for clause in _customer_filter_clauses(q=q, country=country, type=type):
        stmt = stmt.where(clause)
    stmt = (
        stmt.order_by(col(Customer.created_at).desc().nulls_last(), col(Customer.id))
        .offset(skip)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def list_customer_options(*, session: Session) -> list[CustomerOption]:
    rows = session.exec(
        select(col(Customer.id), col(Customer.name)).order_by(col(Customer.name))
    ).all()
    return [CustomerOption(id=row[0], name=row[1]) for row in rows]


def list_customer_countries(*, session: Session) -> list[str]:
    rows = session.exec(
        select(col(Customer.country))
        .where(col(Customer.country).is_not(None))
        .distinct()
        .order_by(col(Customer.country))
    ).all()
    return [row for row in rows if row]


def count_customers(
    *,
    session: Session,
    q: str | None = None,
    country: str | None = None,
    type: CustomerType | None = None,
) -> int:
    stmt = select(func.count()).select_from(Customer)
    for clause in _customer_filter_clauses(q=q, country=country, type=type):
        stmt = stmt.where(clause)
    return session.exec(stmt).one()


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


def get_project(*, session: Session, project_id: uuid.UUID) -> Project | None:
    return session.get(Project, project_id)


def _project_filter_clauses(
    *,
    q: str | None,
    customer_id: uuid.UUID | None,
    status: ProjectStatus | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if q and q.strip():
        term = _ilike_term(q.strip())
        clauses.append(
            or_(
                col(Project.code).ilike(term, escape="\\"),
                col(Project.name).ilike(term, escape="\\"),
            )
        )
    if customer_id is not None:
        clauses.append(col(Project.customer_id) == customer_id)
    if status is not None:
        clauses.append(col(Project.status) == status)
    return clauses


def list_projects(
    *,
    session: Session,
    q: str | None = None,
    customer_id: uuid.UUID | None = None,
    status: ProjectStatus | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Project]:
    stmt = select(Project)
    for clause in _project_filter_clauses(q=q, customer_id=customer_id, status=status):
        stmt = stmt.where(clause)
    stmt = (
        stmt.order_by(col(Project.created_at).desc().nulls_last(), col(Project.id))
        .offset(skip)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def list_project_options(*, session: Session) -> list[ProjectOption]:
    rows = session.exec(
        select(col(Project.id), col(Project.code), col(Project.name))
        .where(Project.status == ProjectStatus.ACTIVE)
        .order_by(col(Project.code))
    ).all()
    return [ProjectOption(id=row[0], code=row[1], name=row[2]) for row in rows]


def count_projects(
    *,
    session: Session,
    q: str | None = None,
    customer_id: uuid.UUID | None = None,
    status: ProjectStatus | None = None,
) -> int:
    stmt = select(func.count()).select_from(Project)
    for clause in _project_filter_clauses(q=q, customer_id=customer_id, status=status):
        stmt = stmt.where(clause)
    return session.exec(stmt).one()


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


def get_product(*, session: Session, product_id: uuid.UUID) -> Product | None:
    return session.get(Product, product_id)


def _product_filter_clauses(
    *,
    q: str | None,
    brand: str | None,
    category: str | None,
    tracking_mode: TrackingMode | None,
    is_active: bool | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    if q and q.strip():
        term = _ilike_term(q.strip())
        clauses.append(
            or_(
                col(Product.sku).ilike(term, escape="\\"),
                col(Product.model_name).ilike(term, escape="\\"),
            )
        )
    if brand and brand.strip():
        clauses.append(col(Product.brand).ilike(_ilike_term(brand.strip()), escape="\\"))
    if category and category.strip():
        clauses.append(
            col(Product.category).ilike(_ilike_term(category.strip()), escape="\\")
        )
    if tracking_mode is not None:
        clauses.append(col(Product.tracking_mode) == tracking_mode)
    if is_active is not None:
        clauses.append(col(Product.is_active) == is_active)
    return clauses


def list_products(
    *,
    session: Session,
    q: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    tracking_mode: TrackingMode | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Product]:
    stmt = select(Product)
    for clause in _product_filter_clauses(
        q=q,
        brand=brand,
        category=category,
        tracking_mode=tracking_mode,
        is_active=is_active,
    ):
        stmt = stmt.where(clause)
    stmt = (
        stmt.order_by(col(Product.created_at).desc().nulls_last(), col(Product.id))
        .offset(skip)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def count_products(
    *,
    session: Session,
    q: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    tracking_mode: TrackingMode | None = None,
    is_active: bool | None = None,
) -> int:
    stmt = select(func.count()).select_from(Product)
    for clause in _product_filter_clauses(
        q=q,
        brand=brand,
        category=category,
        tracking_mode=tracking_mode,
        is_active=is_active,
    ):
        stmt = stmt.where(clause)
    return session.exec(stmt).one()


def list_product_options(
    *, session: Session, active_only: bool = False
) -> list[ProductOption]:
    """Every product as a lightweight {id, sku, model_name, tracking_mode, prices}
    projection, ordered by SKU. Unpaginated single round-trip for pickers/lookups
    across the app; includes inactive products, whose historical movements still
    appear in the append-only ledgers."""
    statement = select(  # type: ignore[call-overload]
            col(Product.id),
            col(Product.sku),
            col(Product.model_name),
            col(Product.tracking_mode),
            col(Product.retail_price_thb),
            col(Product.repair_price_thb),
        ).order_by(col(Product.sku))
    if active_only:
        statement = statement.where(Product.is_active)
    rows = session.exec(statement).all()
    return [
        ProductOption(
            id=r[0],
            sku=r[1],
            model_name=r[2],
            tracking_mode=r[3],
            retail_price_thb=r[4],
            repair_price_thb=r[5],
        )
        for r in rows
    ]


def latest_purchase_costs(*, session: Session) -> dict[uuid.UUID, Decimal]:
    """Latest purchase cost per product — the purchase_cost_thb of the most
    recent receipt: newest PartBatch (QUANTITY) or newest Unit (SERIALIZED) by
    received_at. COGS / admin-only data. Set-based via Postgres DISTINCT ON (one
    row per product per source), merged in Python; no N+1. Products with no
    receipts are absent from the result."""
    latest: dict[uuid.UUID, tuple[datetime, Decimal]] = {}
    batch_rows = session.execute(
        sa_select(
            col(PartBatch.product_id), col(PartBatch.received_at), col(PartBatch.purchase_cost_thb)
        )
        .order_by(col(PartBatch.product_id), col(PartBatch.received_at).desc(), col(PartBatch.id).desc())
        .distinct(col(PartBatch.product_id))
    ).all()
    unit_rows = session.execute(
        sa_select(col(Unit.product_id), col(Unit.received_at), col(Unit.purchase_cost_thb))
        .order_by(col(Unit.product_id), col(Unit.received_at).desc(), col(Unit.id).desc())
        .distinct(col(Unit.product_id))
    ).all()
    # On an exact cross-source received_at tie, batch_rows wins by iteration order; benign in practice (products are single-tracking-mode).
    for source in (batch_rows, unit_rows):
        for r in source:
            product_id, received_at, cost = r[0], r[1], r[2]
            current = latest.get(product_id)
            if current is None or received_at > current[0]:
                latest[product_id] = (received_at, cost)
    return {pid: value[1] for pid, value in latest.items()}


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


def list_price_history(
    *, session: Session, product_id: uuid.UUID
) -> list[PriceChange]:
    return list(
        session.exec(
            select(PriceChange)
            .where(PriceChange.product_id == product_id)
            .order_by(col(PriceChange.changed_at).desc())
        ).all()
    )


# --- Serialized receive (FR-005) ----------------------------------------------


def get_unit(*, session: Session, unit_id: uuid.UUID) -> Unit | None:
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


def _require_active_product(product: Product) -> None:
    """Inactive (discontinued) products can't be transacted. Mirrors the
    active-only pickers at the API boundary — typed SKUs, scanned barcodes,
    and offline replays all bypass the picker filter."""
    if not product.is_active:
        raise HTTPException(
            status_code=400, detail=f"Product {product.sku} is inactive"
        )


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
    product = session.get(Product, product_id)
    if not product:
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
    if len(replay) == len(move_keys) and replay:
        # All units of one receipt share the actor — bind on the first.
        # (A zero-piece request falls through as a harmless non-replay.)
        _assert_replay_actor(
            stored_user_id=next(iter(replay.values())).received_by_user_id,
            caller_user_id=received_by_user_id,
        )
        return [replay[key] for key in move_keys]

    # Guarded after the replay lookup (as in receive_quantity): a replay of a
    # receipt made while the product was active must still return its units,
    # even if the product has since been retired.
    _require_active_product(product)

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
        if replay:
            _assert_replay_actor(
                stored_user_id=next(iter(replay.values())).received_by_user_id,
                caller_user_id=received_by_user_id,
            )
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
        _assert_replay_actor(
            stored_user_id=replay.received_by_user_id,
            caller_user_id=received_by_user_id,
        )
        return replay

    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    _require_active_product(product)
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
        _assert_replay_actor(
            stored_user_id=replay.received_by_user_id,
            caller_user_id=received_by_user_id,
        )
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


# --- Pricing override (FR-010) ------------------------------------------------

_PCT = Decimal("0.0001")
# Caps deviation at the Numeric(7,4) ceiling; used when the default price is 0
# so a meaningful percentage cannot be computed — forces the request to PENDING.
_MAX_DEVIATION_PCT = Decimal("999.9999")


def _default_price_for_target(
    *, product: Product, target_kind: OverrideTargetKind
) -> Decimal:
    if target_kind == OverrideTargetKind.SALE_LINE:
        return product.retail_price_thb
    return product.repair_price_thb


def create_pricing_override(
    *,
    session: Session,
    override_in: PricingOverrideCreate,
    created_by_user_id: uuid.UUID,
) -> PricingOverrideRequest:
    """Create an override request (FR-010). The default price is server-derived
    from the product (never client-supplied), so deviation can't be gamed.
    AUTO_APPROVED when deviation <= the configured threshold; else PENDING for an
    admin decide."""
    product = session.get(Product, override_in.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    default = _default_price_for_target(
        product=product, target_kind=override_in.target_kind
    )
    requested = override_in.requested_price_thb
    # A 0 default price can't yield a meaningful percentage. requested==0 is a
    # genuine no-op (0% deviation); any other price MUST go to admin review —
    # forced unconditionally (not via the threshold compare, which a threshold
    # set absurdly high could otherwise auto-approve).
    if default <= 0:
        if requested == 0:
            deviation = Decimal("0")
            force_pending = False
        else:
            deviation = _MAX_DEVIATION_PCT
            force_pending = True
    else:
        # Cap before quantize so a tiny default + huge requested price can't
        # overflow Numeric(7,4) (would 500 at commit).
        raw = abs(requested - default) / default * 100
        deviation = min(raw, _MAX_DEVIATION_PCT).quantize(
            _PCT, rounding=ROUND_HALF_UP
        )
        force_pending = False

    threshold = Decimal(
        str(
            get_setting(
                session=session,
                key=OVERRIDE_THRESHOLD_KEY,
                default=DEFAULT_OVERRIDE_THRESHOLD_PCT,
            )
        )
    )
    state = (
        OverrideState.AUTO_APPROVED
        if not force_pending and deviation <= threshold
        else OverrideState.PENDING
    )
    row = PricingOverrideRequest(
        target_kind=override_in.target_kind,
        product_id=product.id,
        default_price_thb=default,
        requested_price_thb=requested,
        deviation_pct=deviation,
        reason=override_in.reason,
        state=state,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_pricing_override(
    *, session: Session, override_id: uuid.UUID
) -> PricingOverrideRequest | None:
    return session.get(PricingOverrideRequest, override_id)


def list_pricing_overrides(
    *,
    session: Session,
    state: OverrideState | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[PricingOverrideRequest]:
    stmt = select(PricingOverrideRequest)
    if state is not None:
        stmt = stmt.where(PricingOverrideRequest.state == state)
    stmt = (
        stmt.order_by(PricingOverrideRequest.created_at.desc())  # type: ignore[attr-defined]
        .offset(skip)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def count_pricing_overrides(
    *, session: Session, state: OverrideState | None = None
) -> int:
    statement = select(func.count()).select_from(PricingOverrideRequest)
    if state is not None:
        statement = statement.where(PricingOverrideRequest.state == state)
    return session.exec(statement).one()


def decide_pricing_override(
    *,
    session: Session,
    override_id: uuid.UUID,
    decision: Literal["APPROVED", "REJECTED"],
    decided_by_user_id: uuid.UUID,
) -> PricingOverrideRequest:
    """Admin approves/rejects a PENDING override. Locks the row FOR UPDATE so two
    concurrent decisions serialize; only a PENDING request may be decided."""
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=422, detail="decision must be APPROVED or REJECTED"
        )
    row = session.exec(
        select(PricingOverrideRequest)
        .where(PricingOverrideRequest.id == override_id)
        .with_for_update()
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Override request not found")
    if row.state != OverrideState.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Only PENDING overrides can be decided (current: {row.state.value})",
        )
    row.state = (
        OverrideState.APPROVED
        if decision == "APPROVED"
        else OverrideState.REJECTED
    )
    row.decided_by_user_id = decided_by_user_id
    row.decided_at = get_datetime_utc()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _override_already_consumed(
    *, session: Session, override_id: uuid.UUID
) -> bool:
    """True if a sale_line or service_ticket_part already references the override
    (single-use). Safe to call after the override row is locked FOR UPDATE."""
    if session.exec(
        select(SaleLine.id).where(
            SaleLine.pricing_override_request_id == override_id
        )
    ).first():
        return True
    return (
        session.exec(
            select(ServiceTicketPart.id).where(
                ServiceTicketPart.pricing_override_request_id == override_id
            )
        ).first()
        is not None
    )


def _lock_override(
    *, session: Session, override_id: uuid.UUID
) -> PricingOverrideRequest:
    row = session.exec(
        select(PricingOverrideRequest)
        .where(PricingOverrideRequest.id == override_id)
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Override request not found")
    return row


def _apply_override_price(
    *,
    session: Session,
    override: PricingOverrideRequest,
    target_kind: OverrideTargetKind,
    product_id: uuid.UUID,
) -> Decimal:
    """Validate an already-locked override against the consuming line and return
    the price to charge. 400 for wrong target/product or an unapproved state; 409
    if it was already applied to another line (single-use)."""
    if override.target_kind != target_kind:
        raise HTTPException(
            status_code=400, detail="Override is for a different target kind"
        )
    if override.product_id != product_id:
        raise HTTPException(
            status_code=400, detail="Override is for a different product"
        )
    if override.state not in (
        OverrideState.AUTO_APPROVED,
        OverrideState.APPROVED,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Override not approved (state: {override.state.value})",
        )
    if _override_already_consumed(session=session, override_id=override.id):
        raise HTTPException(
            status_code=409, detail="Override already applied to a line"
        )
    return override.requested_price_thb


def override_exceptions_report(
    *, session: Session, year: int, month: int
) -> OverrideExceptionsReport:
    """Monthly list of pricing overrides requested in [month_start, next) UTC,
    with per-state counts (FR-010, spec §8). Sorted by deviation size (largest
    first); ties break by created_at ascending, then id for a total order. Each
    row carries the product SKU for readability."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    results = session.exec(
        select(PricingOverrideRequest, Product.sku)
        .join(Product, col(PricingOverrideRequest.product_id) == col(Product.id))
        .where(
            col(PricingOverrideRequest.created_at) >= start,
            col(PricingOverrideRequest.created_at) < end,
        )
        .order_by(
            col(PricingOverrideRequest.deviation_pct).desc(),
            col(PricingOverrideRequest.created_at).asc(),
            col(PricingOverrideRequest.id),
        )
    ).all()

    counts: dict[OverrideState, int] = dict.fromkeys(OverrideState, 0)
    rows: list[OverrideExceptionRow] = []
    for ovr, sku in results:
        counts[ovr.state] += 1
        rows.append(
            OverrideExceptionRow(
                id=ovr.id,
                target_kind=ovr.target_kind,
                product_id=ovr.product_id,
                sku=sku,
                default_price_thb=ovr.default_price_thb,
                requested_price_thb=ovr.requested_price_thb,
                deviation_pct=ovr.deviation_pct,
                reason=ovr.reason,
                state=ovr.state,
                created_by_user_id=ovr.created_by_user_id,
                created_at=ovr.created_at,
                decided_by_user_id=ovr.decided_by_user_id,
                decided_at=ovr.decided_at,
            )
        )

    return OverrideExceptionsReport(
        month=f"{year:04d}-{month:02d}",
        total=len(rows),
        auto_approved=counts[OverrideState.AUTO_APPROVED],
        pending=counts[OverrideState.PENDING],
        approved=counts[OverrideState.APPROVED],
        rejected=counts[OverrideState.REJECTED],
        rows=rows,
    )


# --- Holding-period report (FR-014, Flow F) -----------------------------------


def holding_period_report(
    *, session: Session, only_over_threshold: bool = False
) -> HoldingPeriodReport:
    """now() - received_at for in-stock SERIALIZED units (per unit) and active
    QUANTITY batches rolled up per SKU on the oldest non-depleted batch (Flow F).
    Threshold is admin-configurable via system_setting (default 90 days); rows
    above it are flagged. Sorted oldest-first."""
    threshold = int(
        get_setting(
            session=session,
            key=HOLDING_THRESHOLD_KEY,
            default=DEFAULT_HOLDING_THRESHOLD_DAYS,
        )
    )
    now = get_datetime_utc()
    rows: list[HoldingPeriodRow] = []

    units = session.exec(
        select(Unit, Product.sku)
        .join(Product, col(Unit.product_id) == col(Product.id))
        .where(Unit.current_state == UnitState.IN_STOCK)
    ).all()
    for unit, sku in units:
        days = (now - unit.received_at).days
        rows.append(
            HoldingPeriodRow(
                tracking_mode=TrackingMode.SERIALIZED,
                product_id=unit.product_id,
                sku=sku,
                reference=unit.castranova_barcode,
                received_at=unit.received_at,
                holding_days=days,
                quantity=1,
                over_threshold=days > threshold,
            )
        )

    # QUANTITY: roll up active batches per product onto the oldest one.
    active = session.exec(
        select(PartBatch, Product.sku)
        .join(Product, col(PartBatch.product_id) == col(Product.id))
        .where(PartBatch.remaining_qty > 0)
    ).all()
    rollup: dict[uuid.UUID, dict[str, Any]] = {}
    for batch, sku in active:
        entry = rollup.get(batch.product_id)
        if entry is None:
            rollup[batch.product_id] = {
                "sku": sku,
                "oldest": batch,
                "qty": batch.remaining_qty,
            }
        else:
            entry["qty"] += batch.remaining_qty
            if batch.received_at < entry["oldest"].received_at:
                entry["oldest"] = batch
    for product_id, entry in rollup.items():
        oldest: PartBatch = entry["oldest"]
        days = (now - oldest.received_at).days
        rows.append(
            HoldingPeriodRow(
                tracking_mode=TrackingMode.QUANTITY,
                product_id=product_id,
                sku=entry["sku"],
                reference=oldest.batch_no,
                received_at=oldest.received_at,
                holding_days=days,
                quantity=entry["qty"],
                over_threshold=days > threshold,
            )
        )

    if only_over_threshold:
        rows = [r for r in rows if r.over_threshold]
    rows.sort(key=lambda r: r.holding_days, reverse=True)
    return HoldingPeriodReport(
        threshold_days=threshold, generated_at=now, rows=rows
    )


# --- Search (FR-015, Flow F) --------------------------------------------------


def _build_serial_movements(
    *, session: Session, movements: list[UnitMovement]
) -> list[SerialMovementPublic]:
    """Resolve a unit's movements to display labels (locations, actor, linked
    sale/ticket/pull). No cost — serialized search is cost-free for both roles."""
    if not movements:
        return []

    loc_ids: set[uuid.UUID] = set()
    actor_ids: set[uuid.UUID] = set()
    sale_ids: set[uuid.UUID] = set()
    ticket_ids: set[uuid.UUID] = set()
    pull_ids: set[uuid.UUID] = set()
    for m in movements:
        if m.from_location_id is not None:
            loc_ids.add(m.from_location_id)
        if m.to_location_id is not None:
            loc_ids.add(m.to_location_id)
        actor_ids.add(m.actor_user_id)
        if m.sale_id is not None:
            sale_ids.add(m.sale_id)
        if m.service_ticket_id is not None:
            ticket_ids.add(m.service_ticket_id)
        if m.project_pull_id is not None:
            pull_ids.add(m.project_pull_id)

    locations = {
        loc.id: loc.name
        for loc in (
            session.exec(select(Location).where(col(Location.id).in_(loc_ids))).all()
            if loc_ids
            else []
        )
    }
    actors = {
        u.id: u.full_name
        for u in (
            session.exec(select(User).where(col(User.id).in_(actor_ids))).all()
            if actor_ids
            else []
        )
    }
    sales = {
        s.id: s
        for s in (
            session.exec(select(Sale).where(col(Sale.id).in_(sale_ids))).all()
            if sale_ids
            else []
        )
    }
    tickets = {
        t.id: t
        for t in (
            session.exec(
                select(ServiceTicket).where(col(ServiceTicket.id).in_(ticket_ids))
            ).all()
            if ticket_ids
            else []
        )
    }
    pulls = {
        p.id: p
        for p in (
            session.exec(select(ProjectPull).where(col(ProjectPull.id).in_(pull_ids))).all()
            if pull_ids
            else []
        )
    }
    cust_ids: set[uuid.UUID] = set()
    proj_ids: set[uuid.UUID] = set()
    for s in sales.values():
        cust_ids.add(s.customer_id)
    for t in tickets.values():
        cust_ids.add(t.customer_id)
    for p in pulls.values():
        cust_ids.add(p.customer_id)
        proj_ids.add(p.project_id)
    customers = {
        c.id: c.name
        for c in (
            session.exec(select(Customer).where(col(Customer.id).in_(cust_ids))).all()
            if cust_ids
            else []
        )
    }
    projects = {
        pr.id: pr
        for pr in (
            session.exec(select(Project).where(col(Project.id).in_(proj_ids))).all()
            if proj_ids
            else []
        )
    }

    out: list[SerialMovementPublic] = []
    for m in movements:
        kind: str | None = None
        label: str | None = None
        if m.sale_id is not None:
            kind = "SALE"
            sale = sales.get(m.sale_id)
            label = customers.get(sale.customer_id) if sale else None
        elif m.service_ticket_id is not None:
            kind = "SERVICE_TICKET"
            ticket = tickets.get(m.service_ticket_id)
            label = customers.get(ticket.customer_id) if ticket else None
        elif m.project_pull_id is not None:
            kind = "PROJECT_PULL"
            pull = pulls.get(m.project_pull_id)
            proj = projects.get(pull.project_id) if pull else None
            label = f"Project {proj.code} — {proj.name}" if proj else None
        elif m.stock_adjustment_id is not None:
            kind = "STOCK_ADJUSTMENT"
        out.append(
            SerialMovementPublic(
                event_type=m.event_type,
                from_location_id=m.from_location_id,
                to_location_id=m.to_location_id,
                occurred_at=m.occurred_at,
                actor_user_id=m.actor_user_id,
                sale_id=m.sale_id,
                service_ticket_id=m.service_ticket_id,
                project_pull_id=m.project_pull_id,
                stock_adjustment_id=m.stock_adjustment_id,
                notes=m.notes,
                from_location_name=(
                    locations.get(m.from_location_id) if m.from_location_id else None
                ),
                to_location_name=(
                    locations.get(m.to_location_id) if m.to_location_id else None
                ),
                actor_name=actors.get(m.actor_user_id),
                reference_kind=kind,
                reference_label=label,
            )
        )
    return out


def search_serial(
    *, session: Session, barcode: str
) -> SerialSearchResult:
    """Full lifecycle of one serialized unit by castranova_barcode — its
    unit_movement rows in chronological order (FR-015). No cost fields."""
    unit = session.exec(
        select(Unit).where(Unit.castranova_barcode == barcode)
    ).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    product = session.get(Product, unit.product_id)
    assert product is not None
    movements = session.exec(
        select(UnitMovement)
        .where(UnitMovement.unit_id == unit.id)
        .order_by(col(UnitMovement.occurred_at), col(UnitMovement.id))
    ).all()
    return SerialSearchResult(
        castranova_barcode=unit.castranova_barcode,
        product_id=unit.product_id,
        sku=product.sku,
        supplier_serial=unit.supplier_serial,
        current_state=unit.current_state,
        movements=_build_serial_movements(session=session, movements=list(movements)),
    )


_CONSUMING_EVENTS = (
    MovementType.SOLD,
    MovementType.MAINTENANCE_OUT,
    MovementType.PROJECT_OUT,
    MovementType.ADJUSTED_OUT,
)
_CONSUMPTION_LIMIT = 200  # bounded most-recent page (spec §7)


def _resolve_counterparty(
    m: PartMovement,
    sales: dict[uuid.UUID, Sale],
    tickets: dict[uuid.UUID, ServiceTicket],
    pulls: dict[uuid.UUID, ProjectPull],
    adjustments: dict[uuid.UUID, StockAdjustment],
    customers: dict[uuid.UUID, Customer],
    projects: dict[uuid.UUID, Project],
) -> tuple[str, uuid.UUID, str | None, str | None, str | None, str | None]:
    """Branch on the single non-null parent FK -> (reference_kind, reference_id,
    customer_name, project_name, project_code, notes)."""
    if m.sale_id is not None:
        s = sales.get(m.sale_id)
        cust = customers.get(s.customer_id) if s else None
        return "SALE", m.sale_id, (cust.name if cust else None), None, None, m.notes
    if m.service_ticket_id is not None:
        t = tickets.get(m.service_ticket_id)
        cust = customers.get(t.customer_id) if t else None
        return ("SERVICE_TICKET", m.service_ticket_id,
                (cust.name if cust else None), None, None, m.notes)
    if m.project_pull_id is not None:
        p = pulls.get(m.project_pull_id)
        cust = customers.get(p.customer_id) if p else None
        proj = projects.get(p.project_id) if p else None
        return ("PROJECT_PULL", m.project_pull_id, (cust.name if cust else None),
                (proj.name if proj else None), (proj.code if proj else None), m.notes)
    if m.stock_adjustment_id is not None:
        a = adjustments.get(m.stock_adjustment_id)
        return ("STOCK_ADJUSTMENT", m.stock_adjustment_id, None, None, None,
                (a.reason if a else m.notes))
    # Consuming events always carry a parent FK; defensive fallback only.
    return "UNKNOWN", m.id, None, None, None, m.notes


def _build_consumption_events(
    *, session: Session, movements: list[PartMovement], is_admin: bool
) -> list[SkuConsumptionEventPublic]:
    """Resolve consuming part_movements to attribution events (bulk, no N+1).
    Cost (draws + total_cost_thb) is populated only when is_admin."""
    if not movements:
        return []

    sale_ids: set[uuid.UUID] = set()
    ticket_ids: set[uuid.UUID] = set()
    pull_ids: set[uuid.UUID] = set()
    adj_ids: set[uuid.UUID] = set()
    actor_ids: set[uuid.UUID] = set()
    for m in movements:
        actor_ids.add(m.actor_user_id)
        if m.sale_id is not None:
            sale_ids.add(m.sale_id)
        elif m.service_ticket_id is not None:
            ticket_ids.add(m.service_ticket_id)
        elif m.project_pull_id is not None:
            pull_ids.add(m.project_pull_id)
        elif m.stock_adjustment_id is not None:
            adj_ids.add(m.stock_adjustment_id)

    def _by_id(model: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
        if not ids:
            return {}
        rows = session.exec(select(model).where(col(model.id).in_(ids))).all()
        return {r.id: r for r in rows}

    sales = _by_id(Sale, sale_ids)
    tickets = _by_id(ServiceTicket, ticket_ids)
    pulls = _by_id(ProjectPull, pull_ids)
    adjustments = _by_id(StockAdjustment, adj_ids)
    actors = _by_id(User, actor_ids)

    customer_ids: set[uuid.UUID] = set()
    project_ids: set[uuid.UUID] = set()
    for s in sales.values():
        customer_ids.add(s.customer_id)
    for t in tickets.values():
        customer_ids.add(t.customer_id)
    for p in pulls.values():
        customer_ids.add(p.customer_id)
        project_ids.add(p.project_id)
    customers = _by_id(Customer, customer_ids)
    projects = _by_id(Project, project_ids)

    draws_by_movement: dict[uuid.UUID, list[SkuConsumptionDrawAdminPublic]] = {}
    if is_admin:
        movement_ids = [m.id for m in movements]
        cost_lines = session.exec(
            select(CostLine)
            .join(PartBatch, col(CostLine.part_batch_id) == col(PartBatch.id))
            .where(col(CostLine.part_movement_id).in_(movement_ids))
            .order_by(col(PartBatch.received_at), col(PartBatch.id))
        ).all()
        batch_ids = {cl.part_batch_id for cl in cost_lines}
        batch_no = {
            b.id: b.batch_no
            for b in (
                session.exec(
                    select(PartBatch).where(col(PartBatch.id).in_(batch_ids))
                ).all()
                if batch_ids
                else []
            )
        }
        for cl in cost_lines:
            draws_by_movement.setdefault(cl.part_movement_id, []).append(
                SkuConsumptionDrawAdminPublic(
                    batch_no=batch_no.get(cl.part_batch_id, "—"),
                    quantity=cl.quantity,
                    unit_cost_thb=cl.unit_cost_thb,
                    total_cost_thb=cl.total_cost_thb,
                )
            )

    events: list[SkuConsumptionEventPublic] = []
    for m in movements:
        kind, ref_id, cust_name, proj_name, proj_code, notes = _resolve_counterparty(
            m, sales, tickets, pulls, adjustments, customers, projects
        )
        actor = actors.get(m.actor_user_id)
        common: dict[str, Any] = {
            "event_type": m.event_type,
            "occurred_at": m.occurred_at,
            "quantity": m.quantity,
            "reference_kind": kind,
            "reference_id": ref_id,
            "customer_name": cust_name,
            "project_name": proj_name,
            "project_code": proj_code,
            "actor_name": (actor.full_name if actor else None),
            "notes": notes,
        }
        if is_admin:
            draws = draws_by_movement.get(m.id, [])
            events.append(
                SkuConsumptionEventAdminPublic(
                    **common,
                    total_cost_thb=sum(
                        (d.total_cost_thb for d in draws), Decimal("0.00")
                    ),
                    draws=draws,
                )
            )
        else:
            events.append(SkuConsumptionEventPublic(**common))
    return events


def search_sku(
    *, session: Session, sku: str, is_admin: bool
) -> SkuSearchResult | SkuSearchAdminResult:
    """Batch attribution + QOH + consumption history for one SKU (FR-015).
    QUANTITY lists part_batch rows (oldest-first) and consuming part_movements
    (newest-first, bounded). SERIALIZED reports in-stock unit count, no
    consumption. Cost (batch purchase_cost, per-draw + total COGS) is returned
    only when is_admin — staff get attribution without money (spec §4, §6.5)."""
    product = session.exec(select(Product).where(Product.sku == sku)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    movements: list[PartMovement] = []
    if product.tracking_mode == TrackingMode.QUANTITY:
        batches = session.exec(
            select(PartBatch)
            .where(PartBatch.product_id == product.id)
            .order_by(col(PartBatch.received_at), col(PartBatch.id))
        ).all()
        total = sum(b.remaining_qty for b in batches)
        # Uses ix_part_movement_product_occurred (product_id, occurred_at DESC)
        # for the equality + ordering; event_type is NOT in that index, so it is
        # applied as an in-heap filter (the scan is bounded in practice by this
        # product's movement-history depth). If deep non-consuming histories ever
        # show up in pg_stat_statements, add a partial index
        # (product_id, occurred_at DESC) WHERE event_type IN (consuming...).
        movements = list(
            session.exec(
                select(PartMovement)
                .where(
                    PartMovement.product_id == product.id,
                    col(PartMovement.event_type).in_(_CONSUMING_EVENTS),
                )
                .order_by(
                    col(PartMovement.occurred_at).desc(),
                    col(PartMovement.id).desc(),
                )
                .limit(_CONSUMPTION_LIMIT)
            ).all()
        )
    else:
        total = len(
            session.exec(
                select(Unit.id).where(
                    Unit.product_id == product.id,
                    Unit.current_state == UnitState.IN_STOCK,
                )
            ).all()
        )
        batches = []

    events = _build_consumption_events(
        session=session, movements=movements, is_admin=is_admin
    )

    if is_admin:
        return SkuSearchAdminResult(
            sku=product.sku,
            product_id=product.id,
            tracking_mode=product.tracking_mode,
            total_on_hand=total,
            batches=[SkuBatchAdminPublic.model_validate(b) for b in batches],
            consumption=cast(list[SkuConsumptionEventAdminPublic], events),
        )
    return SkuSearchResult(
        sku=product.sku,
        product_id=product.id,
        tracking_mode=product.tracking_mode,
        total_on_hand=total,
        batches=[SkuBatchPublic.model_validate(b) for b in batches],
        consumption=events,
    )


# --- Stock adjustment (FR-011, Flow E) ----------------------------------------


def _stock_adjustment_by_key(
    *, session: Session, idempotency_key: uuid.UUID
) -> StockAdjustment | None:
    return session.exec(
        select(StockAdjustment).where(
            StockAdjustment.idempotency_key == idempotency_key
        )
    ).first()


def _commit_stock_adjustment(
    *, session: Session, adj: StockAdjustment, idempotency_key: uuid.UUID
) -> StockAdjustment:
    """Commit an adjustment; on an idempotency-key race return the winner (and
    discard any non-transactional low-stock crossing from the rolled-back work)."""
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        session.info["low_stock_crossed"] = set()
        winner = _stock_adjustment_by_key(
            session=session, idempotency_key=idempotency_key
        )
        if winner is None:
            raise
        return winner
    session.refresh(adj)
    return adj


def create_stock_adjustment(
    *,
    session: Session,
    adj_in: StockAdjustmentCreate,
    created_by_user_id: uuid.UUID,
) -> StockAdjustment:
    """Admin write-off / recount in one transaction, no notifications (Flow E):

    - SERIALIZED: lock the unit, transition IN_STOCK -> ADJUSTED_OUT (terminal),
      write a unit_movement(ADJUSTED_OUT) to the ADJUSTED_OUT location.
    - QUANTITY negative: FIFO-consume |delta| (same path as a sale), writing one
      part_movement(ADJUSTED_OUT) + its cost_line[]; 409 on insufficient stock.
    - QUANTITY positive: create a new is_adjustment part_batch (ADJ-### batch_no,
      admin-supplied purchase_cost) + one part_movement(RECEIVED).

    Idempotent on ``idempotency_key`` (admin double-submit returns the existing
    adjustment, never double-consumes / double-creates a batch). Field-shape is
    validated on ``StockAdjustmentCreate``; this only does existence/stock checks.
    """
    replay = _stock_adjustment_by_key(
        session=session, idempotency_key=adj_in.idempotency_key
    )
    if replay is not None:
        return replay

    adjusted_out = session.exec(
        select(Location).where(Location.code == "ADJUSTED_OUT")
    ).first()
    ygn = session.exec(
        select(Location).where(Location.code == "YGN_WH")
    ).first()
    if not adjusted_out or not ygn:
        raise HTTPException(status_code=500, detail="Locations not seeded")

    if adj_in.target_kind == AdjustmentTarget.UNIT:
        unit = session.exec(
            select(Unit)
            .where(Unit.castranova_barcode == adj_in.castranova_barcode)
            .with_for_update()
        ).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")
        try:
            new_state = assert_unit_transition(
                unit.current_state, MovementType.ADJUSTED_OUT
            )
        except IllegalTransition:
            raise HTTPException(
                status_code=409,
                detail=f"Unit cannot be adjusted from {unit.current_state.value}",
            )
        adj = StockAdjustment(
            target_kind=AdjustmentTarget.UNIT,
            unit_id=unit.id,
            reason=adj_in.reason,
            idempotency_key=adj_in.idempotency_key,
            created_by_user_id=created_by_user_id,
        )
        session.add(adj)
        session.flush()
        session.add(
            UnitMovement(
                unit_id=unit.id,
                event_type=MovementType.ADJUSTED_OUT,
                from_location_id=unit.current_location_id,
                to_location_id=adjusted_out.id,
                stock_adjustment_id=adj.id,
                actor_user_id=created_by_user_id,
                idempotency_key=uuid.uuid5(adj.id, str(unit.id)),
            )
        )
        unit.current_state = new_state
        unit.current_location_id = adjusted_out.id
        unit.updated_at = get_datetime_utc()
        session.add(unit)
        return _commit_stock_adjustment(
            session=session, adj=adj, idempotency_key=adj_in.idempotency_key
        )

    # QUANTITY
    product = session.exec(
        select(Product).where(Product.sku == adj_in.sku)
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # No _require_active_product here, deliberately: adjustments are the
    # reconciliation path for draining an inactive product's residual stock.
    if product.tracking_mode != TrackingMode.QUANTITY:
        raise HTTPException(
            status_code=400,
            detail="Stock adjustment SKU must be QUANTITY-tracked",
        )

    assert adj_in.quantity_delta is not None  # validator guarantees non-zero
    adj = StockAdjustment(
        target_kind=AdjustmentTarget.QUANTITY,
        product_id=product.id,
        quantity_delta=adj_in.quantity_delta,
        reason=adj_in.reason,
        idempotency_key=adj_in.idempotency_key,
        created_by_user_id=created_by_user_id,
    )
    session.add(adj)
    session.flush()

    if adj_in.quantity_delta < 0:
        cost_lines = consume_quantity_fifo(
            session=session,
            product_id=product.id,
            quantity_needed=-adj_in.quantity_delta,
        )
        movement = PartMovement(
            product_id=product.id,
            event_type=MovementType.ADJUSTED_OUT,
            quantity=-adj_in.quantity_delta,
            from_location_id=ygn.id,
            to_location_id=adjusted_out.id,
            stock_adjustment_id=adj.id,
            actor_user_id=created_by_user_id,
            idempotency_key=uuid.uuid5(adj.id, "neg"),
        )
        session.add(movement)
        session.flush()
        for cost_line in cost_lines:
            cost_line.part_movement_id = movement.id
            session.add(cost_line)
        # Flow E.5: adjustments never notify — drain the crossing the consume
        # recorded so the route can't dispatch a low-stock alert for it.
        session.info["low_stock_crossed"] = set()
    else:
        assert adj_in.purchase_cost_thb is not None  # validator guarantees set
        batch = PartBatch(
            product_id=product.id,
            batch_no=next_batch_no(
                session=session,
                product_id=product.id,
                sku=product.sku,
                today=date.today(),
                adj=True,
            ),
            supplier_id=None,
            received_qty=adj_in.quantity_delta,
            remaining_qty=adj_in.quantity_delta,
            purchase_cost_thb=adj_in.purchase_cost_thb,
            is_adjustment=True,
            received_by_user_id=created_by_user_id,
        )
        session.add(batch)
        session.flush()
        session.add(
            PartMovement(
                product_id=product.id,
                event_type=MovementType.RECEIVED,
                quantity=adj_in.quantity_delta,
                part_batch_id=batch.id,
                from_location_id=adjusted_out.id,
                to_location_id=ygn.id,
                stock_adjustment_id=adj.id,
                actor_user_id=created_by_user_id,
                idempotency_key=uuid.uuid5(adj.id, "pos"),
            )
        )

    return _commit_stock_adjustment(
        session=session, adj=adj, idempotency_key=adj_in.idempotency_key
    )


# --- Sync review queue (M020) -------------------------------------------------


def create_sync_review_item(
    *, session: Session, data: SyncReviewItemCreate, submitted_by_user_id: uuid.UUID
) -> SyncReviewItem:
    """Ingest a STALE/CONFLICT offline mutation into the admin review queue.

    Idempotent by ``idempotency_key``: a re-POST of the same offline item
    returns the existing row (UNIQUE constraint + IntegrityError rollback path
    via ``get_or_replay``), never a duplicate. Replays are bound to the
    original submitter (hardening spec §4.1.3); legacy NULL rows replay
    unbound."""
    item, replayed = get_or_replay(
        session=session,
        statement=select(SyncReviewItem).where(
            col(SyncReviewItem.idempotency_key) == data.idempotency_key
        ),
        build=lambda: SyncReviewItem(
            idempotency_key=data.idempotency_key,
            mutation_kind=data.mutation_kind,
            payload=data.payload,
            reason=data.reason,
            submitted_by_user_id=submitted_by_user_id,
        ),
    )
    if replayed and item.submitted_by_user_id is not None:
        _assert_replay_actor(
            stored_user_id=item.submitted_by_user_id,
            caller_user_id=submitted_by_user_id,
        )
    return item


def get_sync_review_item(
    *, session: Session, item_id: uuid.UUID
) -> SyncReviewItem | None:
    return session.get(SyncReviewItem, item_id)


def list_sync_review_items(
    *,
    session: Session,
    state: SyncReviewState | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[SyncReviewItem]:
    stmt = select(SyncReviewItem)
    if state is not None:
        stmt = stmt.where(col(SyncReviewItem.state) == state)
    stmt = stmt.order_by(col(SyncReviewItem.created_at)).offset(skip).limit(limit)
    return list(session.exec(stmt).all())


def resolve_sync_review_item(
    *,
    session: Session,
    item_id: uuid.UUID,
    admin_id: uuid.UUID,
    new_state: SyncReviewState,
    note: str | None,
) -> SyncReviewItem:
    """Status-only triage: mark RESOLVED or DISCARDED. Does NOT re-run the held
    mutation. 422 if target is not a terminal state; 404 if missing; 409 if the
    item was already triaged (not PENDING)."""
    if new_state not in (SyncReviewState.RESOLVED, SyncReviewState.DISCARDED):
        raise HTTPException(
            status_code=422, detail="state must be RESOLVED or DISCARDED"
        )
    item = session.exec(
        select(SyncReviewItem)
        .where(col(SyncReviewItem.id) == item_id)
        .with_for_update()
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Sync-review item not found")
    if item.state != SyncReviewState.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Only PENDING items can be resolved (current: {item.state.value})",
        )
    item.state = new_state
    item.resolved_by_user_id = admin_id
    item.resolved_at = get_datetime_utc()
    item.resolution_note = note
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# --- Serialized sale (FR-007) -------------------------------------------------


def get_sale(*, session: Session, sale_id: uuid.UUID) -> Sale | None:
    return session.get(Sale, sale_id)


@dataclass(frozen=True)
class SaleReceiptData:
    """Resolved display inputs for one sale's receipt PDF (non-financial beyond
    price + total)."""

    sale_id: uuid.UUID
    sold_at: datetime
    customer_name: str
    sold_by: str
    lines: list[tuple[str, int, Decimal]]
    total_thb: Decimal


def _receipt_line_label(
    *,
    line: SaleLine,
    units: dict[uuid.UUID, Unit],
    products: dict[uuid.UUID, Product],
) -> str:
    """Human-readable label for a receipt line: parts as ``Model (SKU)``, units
    as ``Model · serial``. Falls back to ``Unknown product`` if a row is gone."""
    if line.unit_id is not None:
        unit = units.get(line.unit_id)
        prod = products.get(unit.product_id) if unit is not None else None
        name = prod.model_name if prod is not None else "Unknown product"
        if unit is not None and unit.supplier_serial:
            return f"{name} · {unit.supplier_serial}"
        return name
    if line.product_id is not None:
        prod = products.get(line.product_id)
        if prod is not None:
            return f"{prod.model_name} ({prod.sku})"
    return "Unknown product"


def get_sale_receipt_data(
    *, session: Session, sale_id: uuid.UUID
) -> SaleReceiptData | None:
    """Resolve a sale into receipt display data via batched lookups (no N+1).
    Returns None when the sale does not exist."""
    sale = get_sale(session=session, sale_id=sale_id)
    if sale is None:
        return None
    sale_lines = session.exec(
        select(SaleLine).where(SaleLine.sale_id == sale.id)
    ).all()

    unit_ids = {ln.unit_id for ln in sale_lines if ln.unit_id is not None}
    product_ids = {ln.product_id for ln in sale_lines if ln.product_id is not None}
    units: dict[uuid.UUID, Unit] = {
        u.id: u
        for u in (
            session.exec(select(Unit).where(col(Unit.id).in_(unit_ids))).all()
            if unit_ids
            else []
        )
    }
    for u in units.values():
        product_ids.add(u.product_id)
    products: dict[uuid.UUID, Product] = {
        p.id: p
        for p in (
            session.exec(select(Product).where(col(Product.id).in_(product_ids))).all()
            if product_ids
            else []
        )
    }

    customer = session.get(Customer, sale.customer_id)
    customer_name = customer.name if customer is not None else "Unknown"
    user = session.get(User, sale.created_by_user_id)
    sold_by = (user.full_name or user.email) if user is not None else "Unknown"

    lines: list[tuple[str, int, Decimal]] = [
        (
            _receipt_line_label(line=ln, units=units, products=products),
            ln.quantity,
            ln.unit_price_thb,
        )
        for ln in sale_lines
    ]
    return SaleReceiptData(
        sale_id=sale.id,
        sold_at=sale.sold_at,
        customer_name=customer_name,
        sold_by=sold_by,
        lines=lines,
        total_thb=sale.total_thb,
    )


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
        _assert_replay_actor(
            stored_user_id=replay.created_by_user_id,
            caller_user_id=created_by_user_id,
        )
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
    # Optional pricing overrides (FR-010), keyed for application in the build
    # loops. seen_override_ids guards against citing one override on two lines.
    unit_override_by_barcode: dict[str, uuid.UUID] = {}
    part_override_by_product: dict[uuid.UUID, uuid.UUID] = {}
    seen_override_ids: set[uuid.UUID] = set()
    for line in lines:
        oid = line.pricing_override_request_id
        if oid is not None and oid in seen_override_ids:
            raise HTTPException(
                status_code=422,
                detail="An override may be applied to at most one line",
            )
        if line.line_kind == SaleLineKind.UNIT:
            if not line.castranova_barcode:
                raise HTTPException(
                    status_code=422, detail="UNIT line requires castranova_barcode"
                )
            barcodes.append(line.castranova_barcode)
            if oid is not None:
                unit_override_by_barcode[line.castranova_barcode] = oid
                seen_override_ids.add(oid)
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
            _require_active_product(product)
            if product.tracking_mode != TrackingMode.QUANTITY:
                raise HTTPException(
                    status_code=400,
                    detail="PART line requires a QUANTITY-tracked product",
                )
            part_reqs.append((product, line.quantity))
            if oid is not None:
                part_override_by_product[product.id] = oid
                seen_override_ids.add(oid)

    # Lock every cited override FOR UPDATE in id order, BEFORE locking units and
    # batches, so the global lock order (overrides -> units -> batches) is fixed
    # across concurrent sales and they cannot deadlock; the lock also serializes
    # two sales racing to consume the same single-use override.
    locked_overrides: dict[uuid.UUID, PricingOverrideRequest] = {
        oid: _lock_override(session=session, override_id=oid)
        for oid in sorted(seen_override_ids, key=str)
    }

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
        _require_active_product(product)
        unit_price = product.retail_price_thb
        override_id = unit_override_by_barcode.get(barcode)
        if override_id is not None:
            unit_price = _apply_override_price(
                session=session,
                override=locked_overrides[override_id],
                target_kind=OverrideTargetKind.SALE_LINE,
                product_id=unit.product_id,
            )
        unit_cost = unit.purchase_cost_thb

        session.add(
            SaleLine(
                sale_id=sale.id,
                line_kind=SaleLineKind.UNIT,
                unit_id=unit.id,
                quantity=1,
                unit_price_thb=unit_price,
                unit_cost_thb=unit_cost,
                pricing_override_request_id=override_id,
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
        unit_price = product.retail_price_thb
        override_id = part_override_by_product.get(product.id)
        if override_id is not None:
            unit_price = _apply_override_price(
                session=session,
                override=locked_overrides[override_id],
                target_kind=OverrideTargetKind.SALE_LINE,
                product_id=product.id,
            )
        session.add(
            SaleLine(
                sale_id=sale.id,
                line_kind=SaleLineKind.PART,
                product_id=product.id,
                quantity=qty,
                unit_price_thb=unit_price,
                unit_cost_thb=(line_cogs / qty).quantize(Decimal("0.01")),
                pricing_override_request_id=override_id,
            )
        )
        total_thb += unit_price * qty
        total_cogs_thb += line_cogs

    sale.total_thb = total_thb
    sale.total_cogs_thb = total_cogs_thb
    session.add(sale)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # session.info is NOT transactional: discard the low-stock crossings
        # recorded during the rolled-back consume so the route does not dispatch
        # a duplicate alert (the winning request already alerts).
        session.info["low_stock_crossed"] = set()
        # A single-use-override unique violation is NOT an idempotency race —
        # surface it as a clean 409 instead of looking up a non-existent winner
        # and re-raising a raw 500 (the FOR UPDATE pre-check normally prevents
        # reaching here, but the DB constraint is the backstop).
        # Override collision is not an idempotency race — no winner row exists
        # to bind, so the actor check below is intentionally not reached on
        # this path.
        if "pricing_override_request_id" in str(exc.orig):
            raise HTTPException(
                status_code=409, detail="Override already applied to a line"
            ) from exc
        # Otherwise: lost the idempotency race — return the winner's sale.
        winner = _sale_by_key(session=session, idempotency_key=idempotency_key)
        if winner is None:
            raise
        _assert_replay_actor(
            stored_user_id=winner.created_by_user_id,
            caller_user_id=created_by_user_id,
        )
        return winner
    session.refresh(sale)
    return sale


# --- Maintenance / service tickets (FR-008) -----------------------------------


def get_service_ticket(
    *, session: Session, ticket_id: uuid.UUID
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


def record_service_ticket(
    *,
    session: Session,
    customer_id: uuid.UUID,
    issue: str,
    parts: list[ServiceTicketPartCreate],
    idempotency_key: uuid.UUID,
    actor_user_id: uuid.UUID,
    notes: str | None = None,
    resolution: str | None = None,
) -> ServiceTicket:
    """Record a maintenance ticket in one transaction (FR-008, Flow C): create the
    ticket, add its parts, FIFO-consume each from stock (one
    part_movement(MAINTENANCE_OUT) + cost_line[] per line), and stamp closed_at —
    it is created already closed. Idempotent on idempotency_key: an offline replay
    returns the existing ticket without re-consuming (S6). There is no persistent
    open-ticket state.

    Price defaults to the product's repair_price_thb; a different price requires an
    approved SERVICE_TICKET_PART override (FR-010 / Flow C.3) — no free-form price
    bypass. Insufficient stock on any line 409s and commits nothing. Mirrors
    create_sale's atomic-idempotent shape."""
    replay = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.idempotency_key == idempotency_key
        )
    ).first()
    if replay is not None:
        _assert_replay_actor(
            stored_user_id=replay.created_by_user_id,
            caller_user_id=actor_user_id,
        )
        return replay

    if not session.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")

    # Validate every line up front (fail fast, no orphan ticket). Each SKU
    # resolves to a QUANTITY product; duplicate SKUs are rejected (the UI merges
    # by SKU); an override may be cited on at most one line.
    part_reqs: list[tuple[Product, int, uuid.UUID | None]] = []
    seen_skus: set[str] = set()
    seen_override_ids: set[uuid.UUID] = set()
    for line in parts:
        if line.sku in seen_skus:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate part line for SKU {line.sku}; merge into one",
            )
        seen_skus.add(line.sku)
        oid = line.pricing_override_request_id
        if oid is not None and oid in seen_override_ids:
            raise HTTPException(
                status_code=422,
                detail="An override may be applied to at most one line",
            )
        product = session.exec(
            select(Product).where(Product.sku == line.sku)
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        _require_active_product(product)
        if product.tracking_mode != TrackingMode.QUANTITY:
            raise HTTPException(
                status_code=400,
                detail="Service part requires a QUANTITY-tracked product",
            )
        part_reqs.append((product, line.quantity, oid))
        if oid is not None:
            seen_override_ids.add(oid)

    # Lock cited overrides FOR UPDATE in id order BEFORE consuming batches (lock
    # order: overrides -> batches), matching create_sale / the old close path, so
    # concurrent consumers cannot deadlock and a single-use override is serialized.
    locked_overrides: dict[uuid.UUID, PricingOverrideRequest] = {
        oid: _lock_override(session=session, override_id=oid)
        for oid in sorted(seen_override_ids, key=str)
    }

    ygn_loc = None
    customer_loc = None
    if part_reqs:
        ygn_loc = session.exec(
            select(Location).where(Location.code == "YGN_WH")
        ).first()
        customer_loc = session.exec(
            select(Location).where(Location.code == "CUSTOMER")
        ).first()
        if not ygn_loc or not customer_loc:
            raise HTTPException(status_code=500, detail="Locations not seeded")

    ticket = ServiceTicket(
        customer_id=customer_id,
        issue=issue,
        notes=notes,
        resolution=resolution,
        created_by_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        closed_at=get_datetime_utc(),
    )
    session.add(ticket)
    session.flush()

    # Consume in deterministic product order so concurrent consumption (across
    # tickets/sales) acquires batch locks in the same order and cannot deadlock.
    for idx, (product, qty, oid) in enumerate(
        sorted(part_reqs, key=lambda pr: str(pr[0].id))
    ):
        cost_lines = consume_quantity_fifo(
            session=session, product_id=product.id, quantity_needed=qty
        )
        assert ygn_loc is not None and customer_loc is not None
        movement = PartMovement(
            product_id=product.id,
            event_type=MovementType.MAINTENANCE_OUT,
            quantity=qty,
            from_location_id=ygn_loc.id,
            to_location_id=customer_loc.id,
            service_ticket_id=ticket.id,
            actor_user_id=actor_user_id,
            idempotency_key=uuid.uuid5(
                idempotency_key, f"maint:{idx}:{product.id}"
            ),
        )
        session.add(movement)
        session.flush()
        for cost_line in cost_lines:
            cost_line.part_movement_id = movement.id
            session.add(cost_line)
        unit_price = product.repair_price_thb
        if oid is not None:
            unit_price = _apply_override_price(
                session=session,
                override=locked_overrides[oid],
                target_kind=OverrideTargetKind.SERVICE_TICKET_PART,
                product_id=product.id,
            )
        session.add(
            ServiceTicketPart(
                service_ticket_id=ticket.id,
                product_id=product.id,
                quantity=qty,
                unit_price_thb=unit_price,
                pricing_override_request_id=oid,
            )
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # session.info is NOT transactional: discard low-stock crossings recorded
        # during the rolled-back consume so the route does not dispatch a
        # duplicate alert (the winning request already alerts).
        session.info["low_stock_crossed"] = set()
        # A single-use-override unique violation is not an idempotency race —
        # surface a clean 409 (the FOR UPDATE pre-lock normally prevents this).
        if "pricing_override_request_id" in str(exc.orig):
            raise HTTPException(
                status_code=409, detail="Override already applied to a line"
            ) from exc
        # Otherwise: lost the idempotency race — return the winner's ticket.
        winner = session.exec(
            select(ServiceTicket).where(
                ServiceTicket.idempotency_key == idempotency_key
            )
        ).first()
        if winner is None:
            raise
        _assert_replay_actor(
            stored_user_id=winner.created_by_user_id,
            caller_user_id=actor_user_id,
        )
        return winner
    session.refresh(ticket)
    return ticket


# --- Project pull (FR-009; Flow D) --------------------------------------------


def get_project_pull(
    *, session: Session, pull_id: uuid.UUID
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


def count_project_pulls(
    *, session: Session, state: ProjectPullState | None = None
) -> int:
    statement = select(func.count()).select_from(ProjectPull)
    if state is not None:
        statement = statement.where(ProjectPull.state == state)
    return session.exec(statement).one()


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
        _require_active_product(product)
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
    *, session: Session, user: User
) -> list[NotificationPreferencePublic]:
    """Return the user's full opt-in grid: one row per (channel, eligible event).

    Persisted rows are merged over a generated default of `enabled=False`, so a
    user who has never opted in still sees every switch they could turn on.
    Returning only persisted rows (the previous behaviour) left a fresh user
    with an empty page and no way to create the first row, which made opt-in a
    manual SQL step.

    Synthetic rows carry `id=None` — they do not exist until the user PATCHes
    one on. Pairs outside `eligible_events` are omitted entirely: the notify
    producers would never deliver them, so offering the switch would promise a
    send that silently never happens.
    """
    persisted = {
        (p.channel, p.event_type): p
        for p in session.exec(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id
            )
        ).all()
    }
    allowed = eligible_events(user)
    grid: list[NotificationPreferencePublic] = []
    # Stable ordering so the UI grid doesn't reshuffle between fetches.
    for channel in NotificationChannel:
        connected = channel_connected(user, channel)
        for event in NotificationEvent:
            if event not in allowed:
                continue
            row = persisted.get((channel, event))
            grid.append(
                NotificationPreferencePublic(
                    id=row.id if row else None,
                    channel=channel,
                    event_type=event,
                    enabled=row.enabled if row else False,
                    channel_connected=connected,
                )
            )
    return grid


def upsert_notification_preferences(
    *,
    session: Session,
    user: User,
    updates: list[NotificationPreferenceUpdate],
) -> list[NotificationPreferencePublic]:
    """Insert-or-update each (channel, event_type) opt-in for the user, then
    return the user's full merged grid (see `list_notification_preferences`).
    Idempotent."""
    for upd in updates:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user.id,
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
                    user_id=user.id,
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
    return list_notification_preferences(session=session, user=user)


def create_telegram_connect_code(
    *, session: Session, user_id: uuid.UUID
) -> TelegramConnectCode:
    """Mint a one-time, ~10-minute code for the Telegram connect deep link.

    See TelegramConnectCode's docstring: this is an authentication boundary,
    not a correlation key, so the code must be unguessable -- never a short
    or sequential value.

    token_hex gives 32 lowercase hex characters -- 128 bits of entropy (same
    as token_urlsafe(16)) and exactly the code column's max_length=32.

    Telegram's deep-link start parameter allows A-Z, a-z, 0-9, '_' and '-'
    (https://core.telegram.org/bots/features#deep-linking), so token_urlsafe
    would be equally valid here; hex is just unambiguous in a URL. Do NOT
    switch to plain base64 -- its '+', '/' and '=' are outside that set.
    """
    record = TelegramConnectCode(
        user_id=user_id,
        code=secrets.token_hex(16),
        expires_at=get_datetime_utc() + timedelta(minutes=10),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def confirm_telegram_connect_code(
    *, session: Session, user: User, code: str, chat_id: str, username: str | None
) -> TelegramConfirmOutcome:
    """Validate and atomically consume a pending connect code for `user`,
    binding `chat_id`/`username` on success. The caller (the confirm route)
    is responsible for resolving `chat_id`/`username` via
    ``notify.get_telegram_updates`` + ``parse_start_code`` first -- crud.py
    doesn't reach into the notify service, matching this codebase's existing
    layering (routes call both; crud stays DB-only).

    ``FOR UPDATE`` makes the consumed_at check-then-set atomic against a
    racing second confirm for the same code.

    Returns PENDING for anything the caller should keep polling through (no
    such code, wrong owner, expired, already consumed) and
    CHAT_ALREADY_LINKED for the one terminal case, so the UI can say
    something true instead of timing out with a generic message.
    """
    record = session.exec(
        select(TelegramConnectCode)
        .where(
            TelegramConnectCode.code == code,
            TelegramConnectCode.user_id == user.id,
        )
        .with_for_update()
    ).first()
    if record is None or record.consumed_at is not None:
        return TelegramConfirmOutcome.PENDING
    if record.expires_at < get_datetime_utc():
        return TelegramConfirmOutcome.PENDING

    # Checked up front for a clear answer in the common case; the
    # IntegrityError below still backstops a racing bind between here and
    # commit. Deliberately does NOT consume the code -- the user can unlink
    # the other account and retry within the TTL.
    incumbent = session.exec(
        select(User).where(
            User.telegram_chat_id == chat_id, User.id != user.id
        )
    ).first()
    if incumbent is not None:
        return TelegramConfirmOutcome.CHAT_ALREADY_LINKED

    record.consumed_at = get_datetime_utc()
    session.add(record)
    user.telegram_chat_id = chat_id
    user.telegram_username = username
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Lost the race: someone bound this chat between the check above and
        # the commit. The rollback also discards consumed_at, so the code
        # stays usable if the winner later unlinks.
        session.rollback()
        return TelegramConfirmOutcome.CHAT_ALREADY_LINKED
    return TelegramConfirmOutcome.CONNECTED


def disconnect_telegram(*, session: Session, user: User) -> None:
    user.telegram_chat_id = None
    user.telegram_username = None
    session.add(user)
    session.commit()


def get_latest_telegram_notification_log(
    *, session: Session, user_id: uuid.UUID
) -> NotificationLog | None:
    """The most recent Telegram send attempt logged for `user_id`, or None if
    they have never had one. Used to detect a rotted binding (bot blocked,
    chat deleted): only the LATEST attempt matters, not "any failure ever" --
    a later success means it recovered."""
    return session.exec(
        select(NotificationLog)
        .where(
            NotificationLog.target_user_id == user_id,
            NotificationLog.channel == NotificationChannel.TELEGRAM,
        )
        .order_by(col(NotificationLog.created_at).desc())
        .limit(1)
    ).first()


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


def _month_window(year: int, month: int) -> tuple[datetime, datetime]:
    """[start, next-month-start) in UTC for a reporting month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _channel_rows(
    session: Session,
    start: datetime,
    end: datetime,
    channel: Channel | None,
) -> list[MarginBreakdownRow]:
    """Revenue/COGS per channel (SALE, MAINTENANCE, PROJECT), fixed order.
    A channel filter narrows to that single channel; otherwise all three are
    returned even when zero (parity with the legacy report)."""
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

    totals = {
        Channel.SALE: (_q(sale_rev), _q(sale_cogs)),
        Channel.MAINTENANCE: (_q(maint_rev), _q(maint_cogs)),
        Channel.PROJECT: (_q(0), _q(proj_part_cogs + proj_unit_cogs)),
    }
    wanted = [channel] if channel is not None else list(totals)
    return [
        MarginBreakdownRow(
            key=ch.value,
            label=ch.value,
            revenue_thb=rev,
            cogs_thb=cogs,
            margin_thb=rev - cogs,
        )
        for ch in wanted
        for rev, cogs in [totals[ch]]
    ]


def _merge(
    acc: dict[uuid.UUID, list[Decimal]], key: uuid.UUID, rev: Decimal, cogs: Decimal
) -> None:
    slot = acc.setdefault(key, [Decimal("0"), Decimal("0")])
    slot[0] += rev
    slot[1] += cogs


def _product_rows(
    session: Session, start: datetime, end: datetime, channel: Channel | None
) -> list[MarginBreakdownRow]:
    """Revenue/COGS per product across the requested channel(s). A SALE line
    for a SERIALIZED product carries ``unit_id`` not ``product_id``, so the
    product is recovered via ``Unit``."""
    acc: dict[uuid.UUID, list[Decimal]] = {}

    if channel in (None, Channel.SALE):
        # SALE revenue: no rounding drift, product = COALESCE(SaleLine.product_id,
        # Unit.product_id).
        pid = func.coalesce(SaleLine.product_id, Unit.product_id)
        for product_id, rev in session.exec(
            select(
                pid,
                func.coalesce(
                    func.sum(SaleLine.quantity * SaleLine.unit_price_thb), Decimal("0")
                ),
            )
            .join(Sale, col(SaleLine.sale_id) == col(Sale.id))
            .join(Unit, col(SaleLine.unit_id) == col(Unit.id), isouter=True)
            .where(col(Sale.sold_at) >= start, col(Sale.sold_at) < end)
            .group_by(pid)
        ).all():
            _merge(acc, product_id, rev, Decimal("0"))
        # SALE COGS: exact sources (mirrors MAINTENANCE/PROJECT), not the rounded
        # SaleLine.unit_cost_thb snapshot -- see create_sale's per-unit-average
        # rounding comment (crud.py ~2244-2246).
        for product_id, cogs in session.exec(
            select(
                PartMovement.product_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(Sale, col(PartMovement.sale_id) == col(Sale.id))
            .where(
                PartMovement.event_type == MovementType.SOLD,
                col(Sale.sold_at) >= start,
                col(Sale.sold_at) < end,
            )
            .group_by(col(PartMovement.product_id))
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)
        for product_id, cogs in session.exec(
            select(
                Unit.product_id,
                func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")),
            )
            .select_from(UnitMovement)
            .join(Sale, col(UnitMovement.sale_id) == col(Sale.id))
            .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
            .where(
                UnitMovement.event_type == MovementType.SOLD,
                col(Sale.sold_at) >= start,
                col(Sale.sold_at) < end,
            )
            .group_by(col(Unit.product_id))
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)

    if channel in (None, Channel.MAINTENANCE):
        # revenue by ServiceTicketPart.product_id
        for product_id, rev in session.exec(
            select(
                ServiceTicketPart.product_id,
                func.coalesce(
                    func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb),
                    Decimal("0"),
                ),
            )
            .join(
                ServiceTicket,
                col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id),
            )
            .where(col(ServiceTicket.closed_at) >= start, col(ServiceTicket.closed_at) < end)
            .group_by(col(ServiceTicketPart.product_id))
        ).all():
            _merge(acc, product_id, rev, Decimal("0"))
        # COGS by PartMovement.product_id (MAINTENANCE_OUT)
        for product_id, cogs in session.exec(
            select(
                PartMovement.product_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
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
            .group_by(col(PartMovement.product_id))
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)

    if channel in (None, Channel.PROJECT):
        # part COGS by PartMovement.product_id (PROJECT_OUT)
        for product_id, cogs in session.exec(
            select(
                PartMovement.product_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
            .where(
                PartMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(PartMovement.product_id))
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)
        # unit COGS by Unit.product_id (PROJECT_OUT)
        for product_id, cogs in session.exec(
            select(
                Unit.product_id,
                func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")),
            )
            .select_from(UnitMovement)
            .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
            .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
            .where(
                UnitMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(Unit.product_id))
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)

    labels = _product_labels(session, list(acc))
    return _sorted_rows(
        (str(pid), labels[pid], _q(rev), _q(cogs)) for pid, (rev, cogs) in acc.items()
    )


def _product_labels(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        p.id: f"{p.sku} — {p.model_name}"
        for p in session.exec(select(Product).where(col(Product.id).in_(ids))).all()
    }


def _customer_rows(
    session: Session, start: datetime, end: datetime, channel: Channel | None
) -> list[MarginBreakdownRow]:
    """Revenue/COGS per customer across the requested channel(s). Every SALE,
    ServiceTicket, and ProjectPull carries a non-null customer_id, so there is
    no walk-in/None bucket."""
    acc: dict[uuid.UUID, list[Decimal]] = {}

    if channel in (None, Channel.SALE):
        # Sale-level authoritative totals: both revenue and COGS are exact
        # here (no per-line rounding drift), unlike the PRODUCT grouping's
        # SaleLine-based reconstruction.
        for cust_id, rev, cogs in session.exec(
            select(
                Sale.customer_id,
                func.coalesce(func.sum(Sale.total_thb), Decimal("0")),
                func.coalesce(func.sum(Sale.total_cogs_thb), Decimal("0")),
            )
            .where(col(Sale.sold_at) >= start, col(Sale.sold_at) < end)
            .group_by(col(Sale.customer_id))
        ).all():
            _merge(acc, cust_id, rev, cogs)

    if channel in (None, Channel.MAINTENANCE):
        for cust_id, rev in session.exec(
            select(
                ServiceTicket.customer_id,
                func.coalesce(
                    func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb),
                    Decimal("0"),
                ),
            )
            .join(
                ServiceTicketPart,
                col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id),
            )
            .where(col(ServiceTicket.closed_at) >= start, col(ServiceTicket.closed_at) < end)
            .group_by(col(ServiceTicket.customer_id))
        ).all():
            _merge(acc, cust_id, rev, Decimal("0"))
        for cust_id, cogs in session.exec(
            select(
                ServiceTicket.customer_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(ServiceTicket, col(PartMovement.service_ticket_id) == col(ServiceTicket.id))
            .where(
                PartMovement.event_type == MovementType.MAINTENANCE_OUT,
                col(ServiceTicket.closed_at) >= start,
                col(ServiceTicket.closed_at) < end,
            )
            .group_by(col(ServiceTicket.customer_id))
        ).all():
            _merge(acc, cust_id, Decimal("0"), cogs)

    if channel in (None, Channel.PROJECT):
        for cust_id, cogs in session.exec(
            select(
                ProjectPull.customer_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
            .where(
                PartMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(ProjectPull.customer_id))
        ).all():
            _merge(acc, cust_id, Decimal("0"), cogs)
        for cust_id, cogs in session.exec(
            select(
                ProjectPull.customer_id,
                func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")),
            )
            .select_from(UnitMovement)
            .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
            .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
            .where(
                UnitMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(ProjectPull.customer_id))
        ).all():
            _merge(acc, cust_id, Decimal("0"), cogs)

    labels = _customer_labels(session, list(acc))
    return _sorted_rows(
        (str(cid), labels[cid], _q(rev), _q(cogs)) for cid, (rev, cogs) in acc.items()
    )


def _customer_labels(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        c.id: c.name
        for c in session.exec(select(Customer).where(col(Customer.id).in_(ids))).all()
    }


def _project_labels(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        p.id: f"{p.code} — {p.name}"
        for p in session.exec(select(Project).where(col(Project.id).in_(ids))).all()
    }


def _project_rows(
    session: Session, start: datetime, end: datetime, channel: Channel | None
) -> list[MarginBreakdownRow]:
    """Revenue/COGS per project (cost-only, mirroring the PROJECT channel).
    Only PROJECT_OUT movements carry a project, so SALE + MAINTENANCE money
    has no project home; when ``channel`` is unscoped, that remainder is
    rolled into a single reconciling ``(not project work)`` bucket so totals
    still match the channel view."""
    acc: dict[uuid.UUID, list[Decimal]] = {}

    if channel in (None, Channel.PROJECT):
        for proj_id, cogs in session.exec(
            select(
                ProjectPull.project_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
            .where(
                PartMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(ProjectPull.project_id))
        ).all():
            _merge(acc, proj_id, Decimal("0"), cogs)
        for proj_id, cogs in session.exec(
            select(
                ProjectPull.project_id,
                func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")),
            )
            .select_from(UnitMovement)
            .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
            .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
            .where(
                UnitMovement.event_type == MovementType.PROJECT_OUT,
                col(ProjectPull.fulfilled_at) >= start,
                col(ProjectPull.fulfilled_at) < end,
            )
            .group_by(col(ProjectPull.project_id))
        ).all():
            _merge(acc, proj_id, Decimal("0"), cogs)

    labels = _project_labels(session, list(acc))
    rows = list(
        _sorted_rows(
            (str(pid), labels[pid], _q(rev), _q(cogs)) for pid, (rev, cogs) in acc.items()
        )
    )

    if channel is None:
        # SALE + MAINTENANCE have no project -> single reconciling bucket.
        remainder = [
            r
            for r in _channel_rows(session, start, end, None)
            if r.key in (Channel.SALE.value, Channel.MAINTENANCE.value)
        ]
        rev = sum((r.revenue_thb for r in remainder), Decimal("0.00"))
        cogs = sum((r.cogs_thb for r in remainder), Decimal("0.00"))
        if rev or cogs:
            rows.append(
                MarginBreakdownRow(
                    key="",
                    label="(not project work)",
                    revenue_thb=_q(rev),
                    cogs_thb=_q(cogs),
                    margin_thb=_q(rev - cogs),
                )
            )
    return rows


def _sorted_rows(
    triples: Iterable[tuple[str, str, Decimal, Decimal]],
) -> list[MarginBreakdownRow]:
    rows = [
        MarginBreakdownRow(
            key=key, label=label, revenue_thb=rev, cogs_thb=cogs, margin_thb=rev - cogs
        )
        for key, label, rev, cogs in triples
    ]
    rows.sort(key=lambda r: (-r.revenue_thb, -r.margin_thb, r.label))
    return rows


def margin_report(
    *,
    session: Session,
    year: int,
    month: int,
    group_by: MarginDimension = MarginDimension.CHANNEL,
    channel: Channel | None = None,
) -> MarginBreakdownReport:
    """Monthly revenue/COGS/margin, grouped by ``group_by`` and optionally
    scoped to one ``channel`` (FR-013 drill-down, spec §8). Read-only; all sums
    set-based and cent-quantized. For any fixed (month, channel) the row sums
    reconcile across every grouping."""
    start, end = _month_window(year, month)
    if group_by == MarginDimension.CHANNEL:
        rows = _channel_rows(session, start, end, channel)
    elif group_by == MarginDimension.PRODUCT:
        rows = _product_rows(session, start, end, channel)
    elif group_by == MarginDimension.CUSTOMER:
        rows = _customer_rows(session, start, end, channel)
    else:
        rows = _project_rows(session, start, end, channel)
    total_rev = sum((r.revenue_thb for r in rows), Decimal("0.00"))
    total_cogs = sum((r.cogs_thb for r in rows), Decimal("0.00"))
    return MarginBreakdownReport(
        month=f"{year:04d}-{month:02d}",
        group_by=group_by,
        channel=channel,
        rows=rows,
        total_revenue_thb=total_rev,
        total_cogs_thb=total_cogs,
        total_margin_thb=total_rev - total_cogs,
    )


# --- Customer dashboard (FR-020; role-tiered, spec §6.5 / S7) ------------------


def get_customer_dashboard(
    *, session: Session, customer_id: uuid.UUID
) -> dict[str, Any]:
    """Admin-superset dashboard for one customer: transactions, projects, and
    lifetime SALE / MAINTENANCE revenue·COGS·margin + PROJECT COGS. Mirrors the
    join shapes of margin_report() but scoped by customer (no date
    window). The route picks the staff or admin schema by role; redacted fields
    are physically absent from the staff JSON."""
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    sale_rev, sale_cogs = session.exec(
        select(
            func.coalesce(func.sum(Sale.total_thb), Decimal("0")),
            func.coalesce(func.sum(Sale.total_cogs_thb), Decimal("0")),
        ).where(col(Sale.customer_id) == customer_id)
    ).one()

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
        .where(
            col(ServiceTicket.customer_id) == customer_id,
            col(ServiceTicket.closed_at).is_not(None),
        )
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
            col(ServiceTicket.customer_id) == customer_id,
        )
    ).one()

    proj_part_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(
            PartMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.customer_id) == customer_id,
        )
    ).one()
    proj_unit_cogs = session.exec(
        select(func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")))
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(
            UnitMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.customer_id) == customer_id,
        )
    ).one()

    projects = session.exec(
        select(Project).where(col(Project.customer_id) == customer_id)
    ).all()
    active = [p for p in projects if p.status == ProjectStatus.ACTIVE]
    closed = [p for p in projects if p.status == ProjectStatus.CLOSED]

    costs = _project_consumed_costs(
        session=session, project_ids=[p.id for p in projects]
    )

    def _project_row(p: Project) -> dict[str, Any]:
        return {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "status": p.status,
            "budget_thb": p.budget_thb,
            "consumed_cost_thb": costs.get(p.id, _q(Decimal("0"))),
        }

    return {
        "customer": customer,
        "transactions": _customer_transactions(
            session=session, customer_id=customer_id
        ),
        "active_projects": [_project_row(p) for p in active],
        "closed_projects": [_project_row(p) for p in closed],
        "lifetime_sale_revenue_thb": _q(sale_rev),
        "lifetime_sale_cogs_thb": _q(sale_cogs),
        "lifetime_sale_margin_thb": _q(sale_rev - sale_cogs),
        "lifetime_maintenance_revenue_thb": _q(maint_rev),
        "lifetime_maintenance_cogs_thb": _q(maint_cogs),
        "lifetime_maintenance_margin_thb": _q(maint_rev - maint_cogs),
        "lifetime_project_cogs_thb": _q(proj_part_cogs + proj_unit_cogs),
    }


def _project_consumed_costs(
    *, session: Session, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Batch variant of _project_consumed_cost: part-COGS + unit-COGS per project
    in TWO grouped queries (avoids the 2N N+1 in get_customer_dashboard). Mirrors
    the join shapes of _project_consumed_cost; any project_id with no rows
    defaults to Decimal("0.00") via _q."""
    if not project_ids:
        return {}
    totals: dict[uuid.UUID, Decimal] = {pid: Decimal("0") for pid in project_ids}

    part_rows = session.exec(
        select(
            col(ProjectPull.project_id),
            func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
        )
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(
            PartMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.project_id).in_(project_ids),
        )
        .group_by(col(ProjectPull.project_id))
    ).all()
    for project_id, part_cogs in part_rows:
        totals[project_id] += part_cogs

    unit_rows = session.exec(
        select(
            col(ProjectPull.project_id),
            func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")),
        )
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(
            UnitMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.project_id).in_(project_ids),
        )
        .group_by(col(ProjectPull.project_id))
    ).all()
    for project_id, unit_cogs in unit_rows:
        totals[project_id] += unit_cogs

    return {pid: _q(total) for pid, total in totals.items()}


def _project_consumed_cost(*, session: Session, project_id: uuid.UUID) -> Decimal:
    part_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(
            PartMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.project_id) == project_id,
        )
    ).one()
    unit_cogs = session.exec(
        select(func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")))
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(
            UnitMovement.event_type == MovementType.PROJECT_OUT,
            col(ProjectPull.project_id) == project_id,
        )
    ).one()
    return _q(part_cogs + unit_cogs)


def get_project_dashboard(
    *, session: Session, project_id: uuid.UUID
) -> dict[str, Any]:
    """Admin-superset dashboard for one project: its pull transactions plus
    budget and consumed cost (reusing _project_consumed_cost). The route picks
    the staff or admin schema by role; the budget/consumed_cost fields are
    physically absent from the staff JSON."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    pulls = session.exec(
        select(ProjectPull).where(col(ProjectPull.project_id) == project_id)
    ).all()
    pull_rows = [
        {"kind": "PROJECT_PULL", "reference_id": p.id, "occurred_at": p.created_at}
        for p in sorted(pulls, key=lambda p: p.created_at, reverse=True)
    ]
    return {
        "project": project,
        "pulls": pull_rows,
        "budget_thb": project.budget_thb,
        "consumed_cost_thb": _project_consumed_cost(
            session=session, project_id=project_id
        ),
    }


def _customer_transactions(
    *, session: Session, customer_id: uuid.UUID
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in session.exec(
        select(Sale).where(col(Sale.customer_id) == customer_id)
    ).all():
        out.append({"kind": "SALE", "reference_id": s.id, "occurred_at": s.sold_at})
    for t in session.exec(
        select(ServiceTicket).where(
            col(ServiceTicket.customer_id) == customer_id,
            col(ServiceTicket.closed_at).is_not(None),
        )
    ).all():
        out.append(
            {"kind": "MAINTENANCE", "reference_id": t.id, "occurred_at": t.closed_at}
        )
    for pull in session.exec(
        select(ProjectPull).where(col(ProjectPull.customer_id) == customer_id)
    ).all():
        out.append(
            {
                "kind": "PROJECT_PULL",
                "reference_id": pull.id,
                "occurred_at": pull.created_at,
            }
        )
    out.sort(key=lambda r: r["occurred_at"], reverse=True)
    return out


# --- Audit trail (FR-019) -----------------------------------------------------


def list_audit(
    *,
    session: Session,
    event_type: MovementType | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    actor_user_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    unit_id: uuid.UUID | None = None,
    sku: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[AuditEntryPublic]:
    """Unified, chronological (occurred_at DESC) view over the two append-only
    movement ledgers (unit_movement + part_movement).

    Filter semantics: ``product_id`` only ever matches PART rows and ``unit_id``
    only ever matches UNIT rows, so supplying one restricts the result to that
    ledger (supplying both yields nothing, since no row is in both). ``sku``
    resolves to a product and spans whichever ledger it uses (a product is one
    tracking mode, so exactly one ledger yields rows); an unknown SKU returns no
    rows. The shared filters (event_type, [from_date, to_date), actor_user_id)
    apply to both.

    Implementation: each ledger is queried filtered + ordered DESC and bounded
    to ``skip + limit`` rows, the two bounded sets are merge-sorted in Python,
    then sliced — never an unbounded fetch.
    """
    bound = skip + limit

    product_id_from_sku: uuid.UUID | None = None
    if sku is not None:
        product_id_from_sku = session.exec(
            select(col(Product.id)).where(col(Product.sku) == sku)
        ).first()
        if product_id_from_sku is None:
            return []  # unknown SKU matches nothing

    audit_unit = product_id is None
    audit_part = unit_id is None

    rows: list[AuditEntryPublic] = []

    if audit_unit:
        u_stmt = select(UnitMovement)
        if event_type is not None:
            u_stmt = u_stmt.where(UnitMovement.event_type == event_type)
        if from_date is not None:
            u_stmt = u_stmt.where(col(UnitMovement.occurred_at) >= from_date)
        if to_date is not None:
            u_stmt = u_stmt.where(col(UnitMovement.occurred_at) < to_date)
        if actor_user_id is not None:
            u_stmt = u_stmt.where(UnitMovement.actor_user_id == actor_user_id)
        if unit_id is not None:
            u_stmt = u_stmt.where(UnitMovement.unit_id == unit_id)
        if sku is not None:
            u_stmt = u_stmt.where(
                col(UnitMovement.unit_id).in_(
                    select(col(Unit.id)).where(
                        col(Unit.product_id) == product_id_from_sku
                    )
                )
            )
        u_stmt = u_stmt.order_by(
            col(UnitMovement.occurred_at).desc(), col(UnitMovement.id).desc()
        ).limit(bound)
        rows.extend(
            AuditEntryPublic(
                id=m.id,
                ledger="UNIT",
                event_type=m.event_type,
                occurred_at=m.occurred_at,
                actor_user_id=m.actor_user_id,
                quantity=1,
                product_id=None,
                unit_id=m.unit_id,
                sale_id=m.sale_id,
                service_ticket_id=m.service_ticket_id,
                project_pull_id=m.project_pull_id,
                stock_adjustment_id=m.stock_adjustment_id,
                notes=m.notes,
            )
            for m in session.exec(u_stmt).all()
        )

    if audit_part:
        p_stmt = select(PartMovement)
        if event_type is not None:
            p_stmt = p_stmt.where(PartMovement.event_type == event_type)
        if from_date is not None:
            p_stmt = p_stmt.where(col(PartMovement.occurred_at) >= from_date)
        if to_date is not None:
            p_stmt = p_stmt.where(col(PartMovement.occurred_at) < to_date)
        if actor_user_id is not None:
            p_stmt = p_stmt.where(PartMovement.actor_user_id == actor_user_id)
        if product_id is not None:
            p_stmt = p_stmt.where(PartMovement.product_id == product_id)
        if sku is not None:
            p_stmt = p_stmt.where(
                col(PartMovement.product_id) == product_id_from_sku
            )
        p_stmt = p_stmt.order_by(
            col(PartMovement.occurred_at).desc(), col(PartMovement.id).desc()
        ).limit(bound)
        rows.extend(
            AuditEntryPublic(
                id=m.id,
                ledger="PART",
                event_type=m.event_type,
                occurred_at=m.occurred_at,
                actor_user_id=m.actor_user_id,
                quantity=m.quantity,
                product_id=m.product_id,
                unit_id=None,
                sale_id=m.sale_id,
                service_ticket_id=m.service_ticket_id,
                project_pull_id=m.project_pull_id,
                stock_adjustment_id=m.stock_adjustment_id,
                notes=m.notes,
            )
            for m in session.exec(p_stmt).all()
        )

    rows.sort(key=lambda e: (e.occurred_at, e.id), reverse=True)
    page = rows[skip : skip + limit]
    return _hydrate_audit(session=session, rows=page)


def count_audit(
    *,
    session: Session,
    event_type: MovementType | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    actor_user_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    unit_id: uuid.UUID | None = None,
    sku: str | None = None,
) -> int:
    """Total row count for the same filter set as list_audit, across both ledgers,
    for the pagination envelope (GET /audit). Mirrors list_audit's WHERE-clause
    construction exactly, so the count and the page it describes can never
    disagree about what "matches" — a deliberate, small duplication rather than
    a shared filter-builder abstraction, which would be a larger restructure of
    the read path than this fix warrants."""
    product_id_from_sku: uuid.UUID | None = None
    if sku is not None:
        product_id_from_sku = session.exec(
            select(col(Product.id)).where(col(Product.sku) == sku)
        ).first()
        if product_id_from_sku is None:
            return 0

    audit_unit = product_id is None
    audit_part = unit_id is None

    total = 0

    if audit_unit:
        u_stmt = select(func.count()).select_from(UnitMovement)
        if event_type is not None:
            u_stmt = u_stmt.where(UnitMovement.event_type == event_type)
        if from_date is not None:
            u_stmt = u_stmt.where(col(UnitMovement.occurred_at) >= from_date)
        if to_date is not None:
            u_stmt = u_stmt.where(col(UnitMovement.occurred_at) < to_date)
        if actor_user_id is not None:
            u_stmt = u_stmt.where(UnitMovement.actor_user_id == actor_user_id)
        if unit_id is not None:
            u_stmt = u_stmt.where(UnitMovement.unit_id == unit_id)
        if sku is not None:
            u_stmt = u_stmt.where(
                col(UnitMovement.unit_id).in_(
                    select(col(Unit.id)).where(
                        col(Unit.product_id) == product_id_from_sku
                    )
                )
            )
        total += session.exec(u_stmt).one()

    if audit_part:
        p_stmt = select(func.count()).select_from(PartMovement)
        if event_type is not None:
            p_stmt = p_stmt.where(PartMovement.event_type == event_type)
        if from_date is not None:
            p_stmt = p_stmt.where(col(PartMovement.occurred_at) >= from_date)
        if to_date is not None:
            p_stmt = p_stmt.where(col(PartMovement.occurred_at) < to_date)
        if actor_user_id is not None:
            p_stmt = p_stmt.where(PartMovement.actor_user_id == actor_user_id)
        if product_id is not None:
            p_stmt = p_stmt.where(PartMovement.product_id == product_id)
        if sku is not None:
            p_stmt = p_stmt.where(
                col(PartMovement.product_id) == product_id_from_sku
            )
        total += session.exec(p_stmt).one()

    return total


def _hydrate_audit(
    *, session: Session, rows: list[AuditEntryPublic]
) -> list[AuditEntryPublic]:
    """Populate the optional display fields on a page of audit rows via batched
    lookups (no N+1). Read-only; runs only on the already-sliced page so the
    ordering and filters of list_audit are untouched. Customer resolves through
    the single source (sale/ticket/pull); cost/money is never added."""
    if not rows:
        return rows

    unit_ids: set[uuid.UUID] = set()
    product_ids: set[uuid.UUID] = set()
    actor_ids: set[uuid.UUID] = set()
    sale_ids: set[uuid.UUID] = set()
    ticket_ids: set[uuid.UUID] = set()
    pull_ids: set[uuid.UUID] = set()
    for r in rows:
        actor_ids.add(r.actor_user_id)
        if r.unit_id is not None:
            unit_ids.add(r.unit_id)
        if r.product_id is not None:
            product_ids.add(r.product_id)
        if r.sale_id is not None:
            sale_ids.add(r.sale_id)
        if r.service_ticket_id is not None:
            ticket_ids.add(r.service_ticket_id)
        if r.project_pull_id is not None:
            pull_ids.add(r.project_pull_id)

    units: dict[uuid.UUID, Unit] = {
        u.id: u
        for u in (
            session.exec(select(Unit).where(col(Unit.id).in_(unit_ids))).all()
            if unit_ids
            else []
        )
    }
    # UNIT rows carry their product via the unit; PART rows carry it directly.
    for u in units.values():
        product_ids.add(u.product_id)
    products: dict[uuid.UUID, Product] = {
        p.id: p
        for p in (
            session.exec(select(Product).where(col(Product.id).in_(product_ids))).all()
            if product_ids
            else []
        )
    }
    actors: dict[uuid.UUID, User] = {
        u.id: u
        for u in (
            session.exec(select(User).where(col(User.id).in_(actor_ids))).all()
            if actor_ids
            else []
        )
    }
    sales: dict[uuid.UUID, Sale] = {
        s.id: s
        for s in (
            session.exec(select(Sale).where(col(Sale.id).in_(sale_ids))).all()
            if sale_ids
            else []
        )
    }
    tickets: dict[uuid.UUID, ServiceTicket] = {
        t.id: t
        for t in (
            session.exec(
                select(ServiceTicket).where(col(ServiceTicket.id).in_(ticket_ids))
            ).all()
            if ticket_ids
            else []
        )
    }
    pulls: dict[uuid.UUID, ProjectPull] = {
        p.id: p
        for p in (
            session.exec(
                select(ProjectPull).where(col(ProjectPull.id).in_(pull_ids))
            ).all()
            if pull_ids
            else []
        )
    }
    cust_ids: set[uuid.UUID] = set()
    for s in sales.values():
        cust_ids.add(s.customer_id)
    for t in tickets.values():
        cust_ids.add(t.customer_id)
    for pl in pulls.values():
        cust_ids.add(pl.customer_id)
    customers: dict[uuid.UUID, str] = {
        c.id: c.name
        for c in (
            session.exec(select(Customer).where(col(Customer.id).in_(cust_ids))).all()
            if cust_ids
            else []
        )
    }

    for r in rows:
        actor = actors.get(r.actor_user_id)
        if actor is not None:
            r.actor_full_name = actor.full_name or actor.email
        if r.unit_id is not None:
            unit = units.get(r.unit_id)
            if unit is not None:
                r.unit_castranova_barcode = unit.castranova_barcode
                r.unit_supplier_serial = unit.supplier_serial
                prod = products.get(unit.product_id)
                if prod is not None:
                    r.product_model_name = prod.model_name
                    r.product_sku = prod.sku
        elif r.product_id is not None:
            prod = products.get(r.product_id)
            if prod is not None:
                r.product_model_name = prod.model_name
                r.product_sku = prod.sku
        # Resolve customer via the single source (sale/ticket/pull), if any.
        if r.sale_id is not None:
            sale = sales.get(r.sale_id)
            if sale is not None:
                r.customer_name = customers.get(sale.customer_id)
        elif r.service_ticket_id is not None:
            ticket = tickets.get(r.service_ticket_id)
            if ticket is not None:
                r.customer_name = customers.get(ticket.customer_id)
        elif r.project_pull_id is not None:
            pull = pulls.get(r.project_pull_id)
            if pull is not None:
                r.customer_name = customers.get(pull.customer_id)

    return rows


# --- Stock-on-hand dashboard (FR-012) -----------------------------------------


def stock_on_hand(
    *,
    session: Session,
    q: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    supplier_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> StockOnHandResponse:
    """Server-side stock-on-hand per active product in one annotation pass.

    QUANTITY products: sum(part_batch.remaining_qty); SERIALIZED products: count
    of IN_STOCK unit rows. Correlated scalar subqueries with coalesce(...,0) keep
    this set-based (no N+1, no per-row @property). No cost/COGS fields — quantities
    aren't financial, so a single both-roles schema with no role-tiering."""
    qty_pred: list[ColumnElement[bool]] = [
        col(PartBatch.product_id) == col(Product.id),
        col(PartBatch.remaining_qty) > 0,
    ]
    if supplier_id is not None:
        qty_pred.append(col(PartBatch.supplier_id) == supplier_id)
    qty_subq = (
        select(func.coalesce(func.sum(PartBatch.remaining_qty), 0))
        .where(*qty_pred)
        .correlate(Product)
        .scalar_subquery()
    )
    unit_pred: list[ColumnElement[bool]] = [
        col(Unit.product_id) == col(Product.id),
        col(Unit.current_state) == UnitState.IN_STOCK,
    ]
    if supplier_id is not None:
        unit_pred.append(col(Unit.supplier_id) == supplier_id)
    unit_subq = (
        select(func.coalesce(func.count(col(Unit.id)), 0))
        .where(*unit_pred)
        .correlate(Product)
        .scalar_subquery()
    )
    on_hand = case(
        (col(Product.tracking_mode) == TrackingMode.SERIALIZED, unit_subq),
        else_=qty_subq,
    )
    clauses = _product_filter_clauses(
        q=q,
        brand=brand,
        category=category,
        tracking_mode=None,
        is_active=True,
    )
    if supplier_id is not None:
        qty_exists = (
            select(PartBatch.id)
            .where(
                col(PartBatch.product_id) == col(Product.id),
                col(PartBatch.supplier_id) == supplier_id,
                col(PartBatch.remaining_qty) > 0,
            )
            .correlate(Product)
            .exists()
        )
        unit_exists = (
            select(Unit.id)
            .where(
                col(Unit.product_id) == col(Product.id),
                col(Unit.supplier_id) == supplier_id,
                col(Unit.current_state) == UnitState.IN_STOCK,
            )
            .correlate(Product)
            .exists()
        )
        clauses.append(
            case(
                (
                    col(Product.tracking_mode) == TrackingMode.SERIALIZED,
                    unit_exists,
                ),
                else_=qty_exists,
            )
        )

    count_stmt = select(func.count()).select_from(Product)
    for clause in clauses:
        count_stmt = count_stmt.where(clause)
    count = session.exec(count_stmt).one()

    stmt = select(  # type: ignore[call-overload]
        Product.id,
        Product.sku,
        Product.model_name,
        Product.brand,
        Product.category,
        Product.tracking_mode,
        on_hand.label("quantity_on_hand"),
    )
    for clause in clauses:
        stmt = stmt.where(clause)
    stmt = stmt.order_by(col(Product.sku)).offset(skip).limit(limit)
    rows = [
        StockOnHandRow(
            product_id=r[0],
            sku=r[1],
            model_name=r[2],
            brand=r[3],
            category=r[4],
            tracking_mode=r[5],
            quantity_on_hand=int(r[6] or 0),
        )
        for r in session.exec(stmt).all()
    ]
    return StockOnHandResponse(rows=rows, count=count)


def stock_on_hand_batches(
    *, session: Session, product_id: uuid.UUID, include_supplier: bool
) -> list[BatchDrillRow]:
    """Active (remaining_qty > 0) batches for a product, oldest first (FIFO order)."""
    batches = session.exec(
        select(PartBatch, Supplier.name)
        .join(Supplier, col(PartBatch.supplier_id) == col(Supplier.id), isouter=True)
        .where(
            col(PartBatch.product_id) == product_id,
            PartBatch.remaining_qty > 0,
        )
        .order_by(col(PartBatch.received_at), col(PartBatch.id))
    ).all()
    return [
        BatchDrillRow(
            batch_no=batch.batch_no,
            remaining_qty=batch.remaining_qty,
            received_at=batch.received_at,
            supplier=supplier_name if include_supplier else None,
        )
        for batch, supplier_name in batches
    ]


def stock_on_hand_units(
    *, session: Session, product_id: uuid.UUID, include_supplier: bool
) -> list[UnitDrillRow]:
    """In-stock serialized units for a product, oldest first (received order)."""
    units = session.exec(
        select(Unit, Supplier.name)
        .join(Supplier, col(Unit.supplier_id) == col(Supplier.id))
        .where(
            col(Unit.product_id) == product_id,
            col(Unit.current_state) == UnitState.IN_STOCK,
        )
        .order_by(col(Unit.received_at), col(Unit.id))
    ).all()
    return [
        UnitDrillRow(
            id=unit.id,
            castranova_barcode=unit.castranova_barcode,
            supplier_serial=unit.supplier_serial,
            current_state=unit.current_state,
            received_at=unit.received_at,
            supplier=supplier_name if include_supplier else None,
        )
        for unit, supplier_name in units
    ]
