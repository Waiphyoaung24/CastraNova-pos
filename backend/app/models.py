import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import EmailStr, model_validator
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# --- CastraNova domain enums ---------------------------------------------------


class UserRole(str, enum.Enum):
    BKK_ADMIN = "BKK_ADMIN"
    YGN_STAFF = "YGN_STAFF"


class TrackingMode(str, enum.Enum):
    SERIALIZED = "SERIALIZED"
    QUANTITY = "QUANTITY"


class Channel(str, enum.Enum):
    SALE = "SALE"
    MAINTENANCE = "MAINTENANCE"
    PROJECT = "PROJECT"


class UnitState(str, enum.Enum):
    RECEIVED = "RECEIVED"
    IN_STOCK = "IN_STOCK"
    SOLD = "SOLD"
    MAINTENANCE_OUT = "MAINTENANCE_OUT"
    PROJECT_OUT = "PROJECT_OUT"
    ADJUSTED_OUT = "ADJUSTED_OUT"


class MovementType(str, enum.Enum):
    RECEIVED = "RECEIVED"
    SOLD = "SOLD"
    MAINTENANCE_OUT = "MAINTENANCE_OUT"
    PROJECT_OUT = "PROJECT_OUT"
    ADJUSTED_OUT = "ADJUSTED_OUT"


class ProjectPullState(str, enum.Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class LineState(str, enum.Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class OverrideState(str, enum.Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OverrideTargetKind(str, enum.Enum):
    SALE_LINE = "SALE_LINE"
    SERVICE_TICKET_PART = "SERVICE_TICKET_PART"


class AdjustmentTarget(str, enum.Enum):
    UNIT = "UNIT"
    QUANTITY = "QUANTITY"


class SaleLineKind(str, enum.Enum):
    UNIT = "UNIT"
    PART = "PART"


class CustomerType(str, enum.Enum):
    DEALER = "DEALER"
    END_CUSTOMER = "END_CUSTOMER"


class ProjectStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SyncReviewReason(str, enum.Enum):
    STALE = "STALE"  # offline mutation older than the 7-day queue cap
    CONFLICT = "CONFLICT"  # lost a write-conflict (409) on replay


class SyncReviewState(str, enum.Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    DISCARDED = "DISCARDED"


class NotificationChannel(str, enum.Enum):
    LINE = "LINE"
    VIBER = "VIBER"
    TELEGRAM = "TELEGRAM"


class NotificationEvent(str, enum.Enum):
    LOW_STOCK = "LOW_STOCK"
    OVERRIDE_PENDING = "OVERRIDE_PENDING"
    PULL_FULFILLED = "PULL_FULFILLED"
    PULL_SHORT = "PULL_SHORT"


class NotificationStatus(str, enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"


# Who may receive which event. These must agree with the recipient queries in
# app.services.notify: the three below are fetched with
# `User.role == UserRole.BKK_ADMIN`, while notify_low_stock has no role filter.
# Offering a staff user a checkbox for an admin-only event would persist
# enabled=True and then silently never deliver.
ADMIN_ONLY_EVENTS: frozenset["NotificationEvent"] = frozenset(
    {
        NotificationEvent.PULL_SHORT,
        NotificationEvent.PULL_FULFILLED,
        NotificationEvent.OVERRIDE_PENDING,
    }
)
ALL_ROLE_EVENTS: frozenset["NotificationEvent"] = frozenset(
    set(NotificationEvent) - ADMIN_ONLY_EVENTS
)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    role: UserRole = Field(default=UserRole.YGN_STAFF)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    # A chat can only ever be bound to one account -- without this, two users
    # could silently bind the same Telegram chat and cross-feed each other's
    # notifications. Multiple NULLs (not-yet-connected users) are unaffected:
    # Postgres UNIQUE never compares NULL to NULL as equal.
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id", name="uq_user_telegram_chat_id"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    # Messaging platform recipient IDs (populated at deployment enrollment,
    # Task 5.4). Table-only — never exposed via the user API (UserBase/Public).
    line_user_id: str | None = Field(default=None, max_length=128)
    viber_user_id: str | None = Field(default=None, max_length=128)
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    # Display-only, captured alongside telegram_chat_id at connect time so a
    # stale binding is visible ("Connected as @username") rather than a bare,
    # meaningless chat id.
    telegram_username: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Mirrors the address-attribute mapping baked into services/notify.py's
# _CHANNELS -- keep both in sync if a channel is ever added.
CHANNEL_ADDRESS_ATTR: dict[NotificationChannel, str] = {
    NotificationChannel.LINE: "line_user_id",
    NotificationChannel.VIBER: "viber_user_id",
    NotificationChannel.TELEGRAM: "telegram_chat_id",
}


def channel_connected(user: User, channel: NotificationChannel) -> bool:
    """Whether `user` has an address configured for `channel`, independent of
    any event opt-in -- a preference row is meaningless to enable if notify()
    has no address to send to."""
    return bool(getattr(user, CHANNEL_ADDRESS_ATTR[channel]))


def eligible_events(user: User) -> set[NotificationEvent]:
    """The events `user` can actually receive, given their role.

    Keys off `role == BKK_ADMIN` — deliberately NOT `deps.is_admin`, which also
    treats any superuser as admin. The notify producers query the role strictly,
    so a superuser left at the default staff role genuinely does not receive
    admin-only events; the grid must reflect that rather than the wider check.
    """
    if user.role == UserRole.BKK_ADMIN:
        return set(NotificationEvent)
    return set(ALL_ROLE_EVENTS)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class UserOption(SQLModel):
    """Lightweight actor projection for the audit User filter. Deliberately
    unpaginated: no client parameter can amplify the response size. `email` is the
    label fallback because `full_name` is nullable. Includes deactivated users,
    whose historical movements still appear in the append-only ledgers."""

    id: uuid.UUID
    full_name: str | None
    email: EmailStr


# --- Location -----------------------------------------------------------------


class LocationBase(SQLModel):
    code: str = Field(unique=True, index=True, max_length=32)
    name: str = Field(max_length=255)
    country: str | None = Field(default=None, max_length=64)
    is_active: bool = True


class Location(LocationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class LocationPublic(LocationBase):
    id: uuid.UUID


# --- System settings (singleton key/jsonb store; M006, spec §4.2 row 8) -------


class SystemSetting(SQLModel, table=True):
    # One row per configurable knob: override deviation threshold (FR-010),
    # holding-period slow-mover threshold (FR-014), low-stock default, etc.
    # `value` is jsonb so each setting stores its own natural type.
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(unique=True, index=True, max_length=64)
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    updated_by_user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
        ),
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


# --- Supplier -----------------------------------------------------------------


class SupplierBase(SQLModel):
    name: str = Field(max_length=255)
    country: str | None = Field(default=None, max_length=64)
    contact: str | None = Field(default=None, max_length=255)


class Supplier(SupplierBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=64)
    contact: str | None = Field(default=None, max_length=255)


class SupplierPublic(SupplierBase):
    id: uuid.UUID


class SupplierOption(SQLModel):
    id: uuid.UUID
    name: str


# --- Customer -----------------------------------------------------------------


class CustomerBase(SQLModel):
    name: str = Field(max_length=255)
    country: str | None = Field(default=None, max_length=64)
    contact: str | None = Field(default=None, max_length=255)
    type: CustomerType = Field(default=CustomerType.END_CUSTOMER)
    notes: str | None = Field(default=None, max_length=1024)


class Customer(CustomerBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=64)
    contact: str | None = Field(default=None, max_length=255)
    type: CustomerType | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=1024)


class CustomerPublic(CustomerBase):
    id: uuid.UUID


class CustomerOption(SQLModel):
    id: uuid.UUID
    name: str


# --- Project ------------------------------------------------------------------


class ProjectBase(SQLModel):
    code: str = Field(unique=True, index=True, max_length=64)
    name: str = Field(max_length=255)
    customer_id: uuid.UUID = Field(
        foreign_key="customer.id", nullable=False, index=True
    )
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    budget_thb: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(12, 2), nullable=True)
    )


class Project(ProjectBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(SQLModel):
    code: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    customer_id: uuid.UUID | None = Field(default=None)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    status: ProjectStatus | None = Field(default=None)
    budget_thb: Decimal | None = Field(default=None)


class ProjectPublic(ProjectBase):
    id: uuid.UUID


class ProjectOption(SQLModel):
    id: uuid.UUID
    code: str
    name: str


class CustomersPublic(SQLModel):
    data: list[CustomerPublic]
    count: int


class SuppliersPublic(SQLModel):
    data: list[SupplierPublic]
    count: int


class ProjectsPublic(SQLModel):
    data: list[ProjectPublic]
    count: int


# --- Product ------------------------------------------------------------------


class ProductBase(SQLModel):
    sku: str = Field(unique=True, index=True, max_length=64)
    model_name: str = Field(max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, index=True, max_length=128)
    tracking_mode: TrackingMode = Field(default=TrackingMode.QUANTITY, index=True)
    specs: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    # No purchase_cost: SERIALIZED cost lives on unit, QUANTITY on part_batch.
    retail_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    repair_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    default_min_stock_level: int | None = Field(default=None)
    is_active: bool = Field(default=True, index=True)


class Product(ProductBase, table=True):
    __table_args__ = (
        CheckConstraint("retail_price_thb >= 0", name="ck_product_retail_price_nonneg"),
        CheckConstraint("repair_price_thb >= 0", name="ck_product_repair_price_nonneg"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ProductCreate(ProductBase):
    pass


class ProductUpdate(SQLModel):
    model_name: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=128)
    tracking_mode: TrackingMode | None = Field(default=None)
    specs: dict[str, Any] | None = Field(default=None)
    retail_price_thb: Decimal | None = Field(default=None)
    repair_price_thb: Decimal | None = Field(default=None)
    default_min_stock_level: int | None = Field(default=None)
    is_active: bool | None = Field(default=None)


class ProductPublic(ProductBase):
    id: uuid.UUID


class ProductsPublic(SQLModel):
    data: list[ProductPublic]
    count: int


class ProductOption(SQLModel):
    """Lightweight catalog projection for pickers/lookups (audit SKU filter, sale/
    receive/tickets/pulls product selection). Omits `specs` (JSONB) and admin-only
    catalog fields (brand, category, default_min_stock_level); prices are included
    because GET /products already exposes them to the same authenticated audience."""

    id: uuid.UUID
    sku: str
    model_name: str
    tracking_mode: TrackingMode
    retail_price_thb: Decimal
    repair_price_thb: Decimal


class ProductPurchaseCost(SQLModel):
    # Admin-only: latest receipt cost (COGS). Never added to ProductPublic,
    # which is served by the staff-accessible GET /products/.
    product_id: uuid.UUID
    latest_purchase_cost_thb: Decimal


# --- Low-stock alerts (FR-016) ------------------------------------------------


class LowStockItemPublic(SQLModel):
    product_id: uuid.UUID
    sku: str
    model_name: str
    tracking_mode: TrackingMode
    on_hand: int
    min_stock_level: int


class MinStockLevelUpdate(SQLModel):
    min_stock_level: int | None = Field(default=None, ge=0, le=1_000_000)


class BulkMinStockItem(SQLModel):
    product_id: uuid.UUID
    min_stock_level: int | None = Field(default=None, ge=0, le=1_000_000)


class BulkMinStockUpdate(SQLModel):
    items: list[BulkMinStockItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _no_duplicate_product_ids(self) -> "BulkMinStockUpdate":
        seen: set[uuid.UUID] = set()
        for item in self.items:
            if item.product_id in seen:
                raise ValueError(f"duplicate product_id: {item.product_id}")
            seen.add(item.product_id)
        return self


# --- Price change (append-only history; FR-002) -------------------------------


class PriceChangeBase(SQLModel):
    product_id: uuid.UUID = Field(
        foreign_key="product.id", nullable=False, index=True
    )
    field: str = Field(max_length=32)  # retail_price_thb | repair_price_thb
    old_value: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    new_value: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    reason: str | None = Field(default=None, max_length=512)


class PriceChange(PriceChangeBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    changed_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True
    )
    changed_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PriceChangePublic(PriceChangeBase):
    id: uuid.UUID
    changed_by_user_id: uuid.UUID
    changed_at: datetime | None = None


# --- Unit (SERIALIZED stock; state cache) -------------------------------------


class UnitBase(SQLModel):
    product_id: uuid.UUID = Field(foreign_key="product.id", nullable=False)
    supplier_id: uuid.UUID = Field(foreign_key="supplier.id", nullable=False)
    supplier_serial: str = Field(max_length=128)
    castranova_barcode: str = Field(max_length=64)
    current_state: UnitState
    current_location_id: uuid.UUID = Field(
        foreign_key="location.id", nullable=False
    )
    purchase_cost_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    received_by_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)


class Unit(UnitBase, table=True):
    # UNIQUE(castranova_barcode), UNIQUE(supplier_id, supplier_serial) — serials
    # may collide across suppliers; index (current_state, product_id) for SOH (§4.8);
    # standalone product_id index for a state-agnostic lookup (audit SKU filter,
    # FR-019 — (current_state, product_id) above doesn't serve a product_id-only scan).
    __table_args__ = (
        UniqueConstraint("castranova_barcode", name="uq_unit_castranova_barcode"),
        UniqueConstraint(
            "supplier_id", "supplier_serial", name="uq_unit_supplier_serial"
        ),
        Index("ix_unit_state_product", "current_state", "product_id"),
        Index("ix_unit_product", "product_id"),
        CheckConstraint(
            "purchase_cost_thb >= 0", name="ck_unit_purchase_cost_nonneg"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # received_at is audit data — NOT NULL with a DB default so non-ORM inserts
    # cannot leave it blank.
    received_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class UnitPublic(UnitBase):
    id: uuid.UUID
    received_at: datetime | None = None


# --- Unit movement (append-only serialized ledger; spec §4.4) -----------------


class UnitMovementBase(SQLModel):
    unit_id: uuid.UUID = Field(foreign_key="unit.id", nullable=False)
    event_type: MovementType
    from_location_id: uuid.UUID | None = Field(
        default=None, foreign_key="location.id"
    )
    to_location_id: uuid.UUID | None = Field(default=None, foreign_key="location.id")
    sale_id: uuid.UUID | None = Field(default=None, foreign_key="sale.id")
    # No ondelete: serviceticket rows are never deleted (no delete endpoint;
    # append-only domain).
    service_ticket_id: uuid.UUID | None = Field(
        default=None, foreign_key="serviceticket.id"
    )
    project_pull_id: uuid.UUID | None = Field(
        default=None, foreign_key="projectpull.id"
    )
    stock_adjustment_id: uuid.UUID | None = Field(
        default=None, foreign_key="stockadjustment.id"
    )
    actor_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    notes: str | None = Field(default=None, max_length=512)


class UnitMovement(UnitMovementBase, table=True):
    # Append-only: UNIQUE(idempotency_key) for offline replay safety (§7);
    # index (unit_id, occurred_at DESC) for lifecycle traversal (FR-015).
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_unit_movement_idempotency_key"),
        Index(
            "ix_unit_movement_unit_occurred",
            "unit_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_unitmovement_project_pull_id",
            "project_pull_id",
            unique=False,
            postgresql_where=text("project_pull_id IS NOT NULL"),
        ),
        Index(
            "ix_unitmovement_service_ticket_id",
            "service_ticket_id",
            unique=False,
            postgresql_where=text("service_ticket_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    idempotency_key: uuid.UUID
    occurred_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )


class UnitMovementPublic(UnitMovementBase):
    id: uuid.UUID
    idempotency_key: uuid.UUID
    occurred_at: datetime


# --- Unified audit view over the two movement ledgers (FR-019) ----------------


class AuditEntryPublic(SQLModel):
    id: uuid.UUID
    ledger: Literal["UNIT", "PART"]
    event_type: MovementType
    occurred_at: datetime
    actor_user_id: uuid.UUID
    quantity: int  # 1 for unit movements; part_movement.quantity for parts
    product_id: uuid.UUID | None = None  # set for PART; None for UNIT
    unit_id: uuid.UUID | None = None  # set for UNIT; None for PART
    sale_id: uuid.UUID | None = None
    service_ticket_id: uuid.UUID | None = None
    project_pull_id: uuid.UUID | None = None
    stock_adjustment_id: uuid.UUID | None = None
    notes: str | None = None
    # Hydrated, read-only display fields for the admin detail drawer (populated
    # by batched lookups in crud.list_audit). All optional; no cost/money — the
    # ledger stays non-financial. The screen is admin-only, so no redaction.
    product_model_name: str | None = None
    product_sku: str | None = None
    unit_castranova_barcode: str | None = None
    unit_supplier_serial: str | None = None
    customer_name: str | None = None  # source sale/ticket/pull customer, if any
    actor_full_name: str | None = None  # acting user's full_name, else email


class AuditPublic(SQLModel):
    data: list[AuditEntryPublic]
    count: int


# --- Serialized receive (FR-005) request/response -----------------------------


class ReceivePiece(SQLModel):
    supplier_serial: str = Field(max_length=128)
    # Non-negative and bounded to the Numeric(12,2) range; ge also rejects NaN.
    purchase_cost_thb: Decimal = Field(ge=0, le=9999999999.99)


class ReceiveSerializedRequest(SQLModel):
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    pieces: list[ReceivePiece] = Field(min_length=1, max_length=500)
    idempotency_key: uuid.UUID


class ReceiveSerializedResponse(SQLModel):
    units: list[UnitPublic]


# --- Part batch (QUANTITY FIFO stock; M009) -----------------------------------


class PartBatchBase(SQLModel):
    # No index=True: the composite (product_id, remaining_qty) index below already
    # covers product_id-prefix lookups, so a standalone B-tree would be redundant.
    product_id: uuid.UUID = Field(foreign_key="product.id", nullable=False)
    batch_no: str = Field(max_length=128)  # YYYYMMDD-{SKU}-[ADJ-]###
    # Nullable: positive Stock Adjustment batches (is_adjustment=True, found/
    # recounted stock) have no supplier. Normal receives still require one
    # (enforced in crud.receive_quantity).
    supplier_id: uuid.UUID | None = Field(
        default=None, foreign_key="supplier.id"
    )
    supplier_batch_ref: str | None = Field(default=None, max_length=128)
    received_qty: int
    remaining_qty: int
    purchase_cost_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    is_adjustment: bool = Field(default=False)


class PartBatch(PartBatchBase, table=True):
    # UNIQUE(product_id, batch_no) — race-safe sequence backstop (§6.4); index
    # (product_id, remaining_qty) drives FIFO candidate scans (§6.3); CHECK keeps
    # remaining_qty within [0, received_qty] at the DB level (§4.6 no-negative).
    __table_args__ = (
        UniqueConstraint("product_id", "batch_no", name="uq_part_batch_product_no"),
        Index("ix_part_batch_product_remaining", "product_id", "remaining_qty"),
        CheckConstraint(
            "received_qty > 0 AND remaining_qty >= 0 "
            "AND remaining_qty <= received_qty",
            name="ck_part_batch_qty_bounds",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    received_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False
    )
    # received_at doubles as the creation timestamp and the FIFO sort key.
    received_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PartBatchPublic(PartBatchBase):
    id: uuid.UUID
    received_by_user_id: uuid.UUID
    received_at: datetime | None = None


# --- Part movement (append-only QUANTITY ledger; M016, spec §4.4) -------------


class PartMovementBase(SQLModel):
    product_id: uuid.UUID = Field(foreign_key="product.id", nullable=False)
    event_type: MovementType
    quantity: int  # always positive; direction implied by event_type + locations
    # Set for RECEIVED (the batch this movement created) — the QUANTITY parallel
    # to unit_movement.unit_id. NULL for consumption events that span batches;
    # those carry their per-batch links on cost_line instead (M017).
    part_batch_id: uuid.UUID | None = Field(
        default=None, foreign_key="partbatch.id"
    )
    from_location_id: uuid.UUID | None = Field(
        default=None, foreign_key="location.id"
    )
    to_location_id: uuid.UUID | None = Field(default=None, foreign_key="location.id")
    sale_id: uuid.UUID | None = Field(default=None, foreign_key="sale.id")
    # No ondelete: serviceticket rows are never deleted (no delete endpoint;
    # append-only domain).
    service_ticket_id: uuid.UUID | None = Field(
        default=None, foreign_key="serviceticket.id"
    )
    project_pull_id: uuid.UUID | None = Field(
        default=None, foreign_key="projectpull.id"
    )
    stock_adjustment_id: uuid.UUID | None = Field(
        default=None, foreign_key="stockadjustment.id"
    )
    actor_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    notes: str | None = Field(default=None, max_length=512)


class PartMovement(PartMovementBase, table=True):
    # Append-only: UNIQUE(idempotency_key) for offline replay safety (§7);
    # index (product_id, occurred_at DESC) for SKU history (FR-015);
    # CHECK(quantity > 0) — direction is never encoded in the sign (§4.3).
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_part_movement_idempotency_key"
        ),
        Index(
            "ix_part_movement_product_occurred",
            "product_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_partmovement_project_pull_id",
            "project_pull_id",
            unique=False,
            postgresql_where=text("project_pull_id IS NOT NULL"),
        ),
        Index(
            "ix_partmovement_service_ticket_id",
            "service_ticket_id",
            unique=False,
            postgresql_where=text("service_ticket_id IS NOT NULL"),
        ),
        CheckConstraint("quantity > 0", name="ck_part_movement_qty_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    idempotency_key: uuid.UUID
    occurred_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )


# --- Cost line (append-only FIFO consumption split; M017, spec §4.6) ----------


class CostLineBase(SQLModel):
    part_movement_id: uuid.UUID = Field(
        foreign_key="partmovement.id", nullable=False
    )
    part_batch_id: uuid.UUID = Field(foreign_key="partbatch.id", nullable=False)
    quantity: int
    unit_cost_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    total_cost_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]


class CostLine(CostLineBase, table=True):
    # One row per batch a consuming part_movement drew from — closes the FIFO
    # audit chain (movement -> cost_line -> batch -> receipt). UNIQUE keeps a
    # movement from double-counting a batch; CHECK ties total to qty * unit_cost.
    __table_args__ = (
        UniqueConstraint(
            "part_movement_id", "part_batch_id", name="uq_cost_line_movement_batch"
        ),
        # FK lookups: "which cost lines drew from batch X?" (audit drill-down) and
        # Postgres FK-integrity checks on partbatch changes.
        Index("ix_cost_line_part_batch", "part_batch_id"),
        CheckConstraint(
            "quantity > 0 AND total_cost_thb = quantity * unit_cost_thb",
            name="ck_cost_line_total",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )


class CostLinePublic(CostLineBase):
    id: uuid.UUID


# --- QUANTITY receive (FR-005/FR-006) request/response ------------------------


class ReceiveQuantityRequest(SQLModel):
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    # Positive and bounded to a sane carton size; 0 is rejected (CHECK + here).
    received_qty: int = Field(gt=0, le=1_000_000)
    purchase_cost_thb: Decimal = Field(ge=0, le=9999999999.99)
    supplier_batch_ref: str | None = Field(default=None, max_length=128)
    # FR-006 discrepancy confirmation: the expected count is a transient
    # receive-form field; when it differs from actual the staff note is recorded
    # on the movement (no manifest entity is stored, §11).
    expected_qty: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=400)
    idempotency_key: uuid.UUID


# --- Pricing override (FR-010; M013) ------------------------------------------


class PricingOverrideRequest(SQLModel, table=True):
    # Standalone approval request. A sale_line / service_ticket_part points to it
    # via pricing_override_request_id (FK, not the reverse — spec line 222), so a
    # line carries at most one override. default_price_thb is server-derived from
    # the product (never client-supplied) so deviation can't be gamed. State is
    # AUTO_APPROVED when |requested-default| is within the system_setting
    # threshold; else PENDING for an admin decide (FR-010).
    __table_args__ = (
        Index("ix_pricing_override_state_created", "state", "created_at"),
        CheckConstraint(
            "default_price_thb >= 0", name="ck_override_default_price_nonneg"
        ),
        CheckConstraint(
            "requested_price_thb >= 0",
            name="ck_override_requested_price_nonneg",
        ),
        CheckConstraint(
            "deviation_pct >= 0", name="ck_override_deviation_nonneg"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    target_kind: OverrideTargetKind
    product_id: uuid.UUID = Field(
        foreign_key="product.id", nullable=False, index=True
    )
    default_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    requested_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    deviation_pct: Decimal = Field(sa_type=Numeric(7, 4))  # type: ignore[call-overload]
    reason: str = Field(max_length=512)
    state: OverrideState
    created_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": func.now()},
    )
    decided_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", index=True
    )
    decided_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class PricingOverrideCreate(SQLModel):
    target_kind: OverrideTargetKind
    product_id: uuid.UUID
    requested_price_thb: Decimal = Field(ge=0, le=9999999999.99)
    reason: str = Field(min_length=1, max_length=512)


class PricingOverrideDecision(SQLModel):
    decision: Literal["APPROVED", "REJECTED"]


class PricingOverridePublic(SQLModel):
    id: uuid.UUID
    target_kind: OverrideTargetKind
    product_id: uuid.UUID
    product_sku: str
    default_price_thb: Decimal
    requested_price_thb: Decimal
    deviation_pct: Decimal
    reason: str
    state: OverrideState
    created_by_user_id: uuid.UUID
    created_at: datetime
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None


# --- Stock adjustment (FR-011; M014) ------------------------------------------


class StockAdjustment(SQLModel, table=True):
    # Immutable after submit (Flow E). Admin-only. Links downstream:
    # unit_movement.stock_adjustment_id (SERIALIZED) or one+ part_movement rows
    # (QUANTITY: N on negative FIFO, one on a positive ADJ batch).
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_stock_adjustment_idempotency_key"
        ),
        CheckConstraint(
            "target_kind != 'UNIT' OR "
            "(unit_id IS NOT NULL AND product_id IS NULL "
            "AND quantity_delta IS NULL)",
            name="ck_stock_adjustment_unit_fields",
        ),
        CheckConstraint(
            "target_kind != 'QUANTITY' OR "
            "(product_id IS NOT NULL AND unit_id IS NULL "
            "AND quantity_delta IS NOT NULL AND quantity_delta <> 0)",
            name="ck_stock_adjustment_quantity_fields",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    target_kind: AdjustmentTarget
    unit_id: uuid.UUID | None = Field(
        default=None, foreign_key="unit.id", index=True
    )
    product_id: uuid.UUID | None = Field(
        default=None, foreign_key="product.id", index=True
    )
    # Signed for QUANTITY (+ found / - lost); NULL for a SERIALIZED write-off.
    quantity_delta: int | None = Field(default=None)
    reason: str = Field(max_length=512)
    # Idempotent on double-submit (admin online action; no offline queue).
    idempotency_key: uuid.UUID
    created_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": func.now()},
    )


class StockAdjustmentCreate(SQLModel):
    target_kind: AdjustmentTarget
    castranova_barcode: str | None = None  # SERIALIZED target
    sku: str | None = None  # QUANTITY target
    # QUANTITY: non-zero +/-, bounded like the receive/sale quantity caps.
    quantity_delta: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    # Required for a positive QUANTITY adjustment (cost basis of the new batch).
    purchase_cost_thb: Decimal | None = Field(
        default=None, ge=0, le=9999999999.99
    )
    reason: str = Field(min_length=1, max_length=512)
    idempotency_key: uuid.UUID

    @model_validator(mode="after")
    def _check_fields(self) -> "StockAdjustmentCreate":
        if self.target_kind == AdjustmentTarget.UNIT:
            if not self.castranova_barcode:
                raise ValueError("UNIT adjustment requires castranova_barcode")
            if (
                self.sku is not None
                or self.quantity_delta is not None
                or self.purchase_cost_thb is not None
            ):
                raise ValueError(
                    "UNIT adjustment must not set sku/quantity_delta/purchase_cost_thb"
                )
        else:  # QUANTITY
            if not self.sku:
                raise ValueError("QUANTITY adjustment requires sku")
            if self.castranova_barcode is not None:
                raise ValueError(
                    "QUANTITY adjustment must not set castranova_barcode"
                )
            if not self.quantity_delta:
                raise ValueError(
                    "QUANTITY adjustment requires a non-zero quantity_delta"
                )
            if self.quantity_delta > 0 and self.purchase_cost_thb is None:
                raise ValueError(
                    "Positive QUANTITY adjustment requires purchase_cost_thb"
                )
        return self


class StockAdjustmentPublic(SQLModel):
    id: uuid.UUID
    target_kind: AdjustmentTarget
    unit_id: uuid.UUID | None
    product_id: uuid.UUID | None
    quantity_delta: int | None
    reason: str
    created_by_user_id: uuid.UUID
    created_at: datetime


# --- Sync review queue (M020) -------------------------------------------------


class SyncReviewItem(SQLModel, table=True):
    # Captures offline mutations that replayed STALE (>7-day cap) or lost a
    # write-CONFLICT (409 on replay), for admin triage (M020). Thin ingest,
    # status-only triage; ingest is idempotent via the UNIQUE idempotency_key.
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_syncreviewitem_idempotency_key"
        ),
        Index("ix_syncreviewitem_state_created", "state", "created_at"),
        Index(
            "ix_syncreviewitem_submitted_by_user_id",
            "submitted_by_user_id",
            unique=False,
            postgresql_where=text("submitted_by_user_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Uniqueness via __table_args__ (not a plain index).
    idempotency_key: uuid.UUID = Field(index=False)
    mutation_kind: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    reason: SyncReviewReason
    state: SyncReviewState = Field(default=SyncReviewState.PENDING)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        sa_column_kwargs={"server_default": func.now()},
    )
    resolved_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", index=True
    )
    # ON DELETE SET NULL: keep the audit row when the submitter is deleted.
    submitted_by_user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid,
            ForeignKey(
                "user.id",
                ondelete="SET NULL",
                name="fk_syncreviewitem_submitted_by_user_id",
            ),
            nullable=True,
        ),
    )
    resolved_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    resolution_note: str | None = Field(default=None, max_length=500)


class SyncReviewItemCreate(SQLModel):
    idempotency_key: uuid.UUID
    mutation_kind: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    reason: SyncReviewReason


class SyncReviewItemStaffPublic(SQLModel):
    # Ingest response for any authenticated caller: deliberately OMITS `payload`
    # (and the admin-only resolved_* fields) so the staff-reachable route never
    # echoes a stored mutation payload back. Admin list/resolve use the full
    # SyncReviewItemPublic.
    id: uuid.UUID
    idempotency_key: uuid.UUID
    mutation_kind: str
    reason: SyncReviewReason
    state: SyncReviewState
    created_at: datetime


class SyncReviewItemPublic(SQLModel):
    id: uuid.UUID
    idempotency_key: uuid.UUID
    mutation_kind: str
    payload: dict[str, Any]
    reason: SyncReviewReason
    state: SyncReviewState
    created_at: datetime
    submitted_by_user_id: uuid.UUID | None
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None


class SyncReviewResolve(SQLModel):
    # state must be RESOLVED or DISCARDED (validated in crud).
    state: SyncReviewState
    note: str | None = Field(default=None, max_length=500)


# --- Sale + sale_line (FR-007; M010) ------------------------------------------


class Sale(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_sale_idempotency_key"),
        Index("ix_sale_customer_id", "customer_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(foreign_key="customer.id", nullable=False)
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    # UNIQUE constraint already indexes this; no separate index=True (avoids a
    # redundant B-tree).
    idempotency_key: uuid.UUID
    total_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    total_cogs_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    receipt_pdf_path: str | None = Field(default=None, max_length=512)
    sold_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )


class SaleLine(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "unit_cost_thb >= 0", name="ck_saleline_unit_cost_nonneg"
        ),
        CheckConstraint(
            "line_kind != 'UNIT' OR unit_id IS NOT NULL",
            name="ck_saleline_unit_requires_unit_id",
        ),
        CheckConstraint("quantity > 0", name="ck_saleline_quantity_positive"),
        # An override applies to at most one line (nullable unique → many NULLs OK).
        UniqueConstraint(
            "pricing_override_request_id",
            name="uq_saleline_pricing_override_request_id",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sale_id: uuid.UUID = Field(foreign_key="sale.id", nullable=False, index=True)
    line_kind: SaleLineKind
    unit_id: uuid.UUID | None = Field(default=None, foreign_key="unit.id")
    product_id: uuid.UUID | None = Field(default=None, foreign_key="product.id")
    quantity: int
    unit_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    unit_cost_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    pricing_override_request_id: uuid.UUID | None = Field(
        default=None, foreign_key="pricingoverriderequest.id"
    )


class SaleLinePublic(SQLModel):
    id: uuid.UUID
    line_kind: SaleLineKind
    unit_id: uuid.UUID | None
    product_id: uuid.UUID | None
    quantity: int
    unit_price_thb: Decimal
    unit_cost_thb: Decimal


class SalePublic(SQLModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    total_thb: Decimal
    total_cogs_thb: Decimal
    sold_at: datetime
    lines: list[SaleLinePublic]


class SaleLineStaffPublic(SQLModel):
    id: uuid.UUID
    line_kind: SaleLineKind
    unit_id: uuid.UUID | None
    product_id: uuid.UUID | None
    quantity: int
    unit_price_thb: Decimal
    # no unit_cost_thb — redacted for staff. Any NEW cost/margin field added to
    # SaleLine MUST be consciously omitted here too (staff must never see cost data).


class SaleStaffPublic(SQLModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    total_thb: Decimal
    sold_at: datetime
    lines: list[SaleLineStaffPublic]
    # no total_cogs_thb — redacted for staff. Any NEW financial/cost field added to
    # Sale MUST be consciously omitted here too (staff must never see cost data).


class SaleLineInput(SQLModel):
    line_kind: SaleLineKind
    castranova_barcode: str | None = None  # UNIT lines
    sku: str | None = None  # PART lines (Part 2)
    # Bounded like ServiceTicketPartCreate; UNIT lines are always treated as 1.
    quantity: int = Field(default=1, gt=0, le=1_000_000)
    # Optional approved pricing override (FR-010); price comes from the override
    # when present, else product.retail_price_thb.
    pricing_override_request_id: uuid.UUID | None = None


class SaleCreateRequest(SQLModel):
    customer_id: uuid.UUID
    lines: list[SaleLineInput] = Field(min_length=1, max_length=100)
    idempotency_key: uuid.UUID


# --- Service ticket (Maintenance, FR-008; M011) -------------------------------


class ServiceTicket(SQLModel, table=True):
    # Opened + closed at the warehouse (D26); UNIQUE(idempotency_key) covers
    # offline ticket-open replay (S6). Mutable until close; FIFO consumption for
    # its parts is written at close (Flow C).
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_service_ticket_idempotency_key"
        ),
        Index("ix_serviceticket_customer_id", "customer_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(foreign_key="customer.id", nullable=False)
    issue: str = Field(max_length=512)
    resolution: str | None = Field(default=None, max_length=512)
    # Captures the whole-machine-swap → original-sale linkage (notes only, §Flow C.5).
    notes: str | None = Field(default=None, max_length=512)
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    idempotency_key: uuid.UUID
    opened_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )
    closed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ServiceTicketPart(SQLModel, table=True):
    # Mutable until ticket close, then immutable (consumption rows written then).
    # CHECK(quantity > 0) mirrors the other consuming-quantity tables.
    __table_args__ = (
        CheckConstraint(
            "quantity > 0", name="ck_service_ticket_part_qty_positive"
        ),
        # An override applies to at most one line (nullable unique → many NULLs OK).
        UniqueConstraint(
            "pricing_override_request_id",
            name="uq_service_ticket_part_pricing_override_request_id",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    service_ticket_id: uuid.UUID = Field(
        foreign_key="serviceticket.id", nullable=False, index=True
    )
    product_id: uuid.UUID = Field(foreign_key="product.id", nullable=False)
    quantity: int
    unit_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    pricing_override_request_id: uuid.UUID | None = Field(
        default=None, foreign_key="pricingoverriderequest.id"
    )


class ServiceTicketPartPublic(SQLModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price_thb: Decimal


class ServiceTicketPublic(SQLModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    issue: str
    resolution: str | None
    notes: str | None
    opened_at: datetime
    closed_at: datetime | None
    parts: list[ServiceTicketPartPublic]


class ServiceTicketPartCreate(SQLModel):
    sku: str = Field(max_length=64)
    quantity: int = Field(gt=0, le=1_000_000)
    # Price defaults to product.repair_price_thb. A different price requires an
    # approved pricing override (FR-010) — no free-form price bypass.
    pricing_override_request_id: uuid.UUID | None = None


class ServiceTicketRecordRequest(SQLModel):
    # One atomic submission: open + parts + FIFO-consume + close in a single
    # transaction, idempotent on idempotency_key. There is no persistent
    # open-ticket state (FR-008: opened and closed at the warehouse).
    customer_id: uuid.UUID
    issue: str = Field(min_length=1, max_length=512)
    notes: str | None = Field(default=None, max_length=512)
    resolution: str | None = Field(default=None, max_length=512)
    idempotency_key: uuid.UUID
    parts: list[ServiceTicketPartCreate] = Field(default_factory=list)


# --- Project pull (FR-009; M012) ----------------------------------------------


class ProjectPull(SQLModel, table=True):
    # Admin-created online, fulfilled at the warehouse (Flow D). No
    # idempotency_key: replay safety lives in the deterministic movement keys
    # written at fulfill (§7, spec line 461). Index (state, created_at) drives the
    # staff queue.
    __table_args__ = (
        Index("ix_project_pull_state_created", "state", "created_at"),
        Index("ix_projectpull_customer_id", "customer_id"),
        Index("ix_projectpull_project_id", "project_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", nullable=False)
    # Denormalised from project.customer_id at create time (spec §4.3).
    customer_id: uuid.UUID = Field(foreign_key="customer.id", nullable=False)
    state: ProjectPullState = Field(default=ProjectPullState.PENDING)
    admin_notes: str | None = Field(default=None, max_length=512)
    created_by_user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )
    fulfilled_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    fulfilled_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    cancelled_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    cancelled_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )


class ProjectPullLine(SQLModel, table=True):
    # CHECK keeps requested_qty positive when present (PART lines); UNIT lines
    # carry unit_serial instead. Indexed by parent pull for fetch-with-lines.
    __table_args__ = (
        CheckConstraint(
            "requested_qty IS NULL OR requested_qty > 0",
            name="ck_project_pull_line_requested_qty_positive",
        ),
        CheckConstraint(
            "fulfilled_qty >= 0", name="ck_project_pull_line_fulfilled_qty_nn"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_pull_id: uuid.UUID = Field(
        foreign_key="projectpull.id", nullable=False, index=True
    )
    line_kind: SaleLineKind
    product_id: uuid.UUID = Field(foreign_key="product.id", nullable=False)
    # UNIT lines: the unit.castranova_barcode to scan. PART lines: requested_qty.
    unit_serial: str | None = Field(default=None, max_length=64)
    requested_qty: int | None = Field(default=None)
    fulfilled_qty: int = Field(default=0)
    line_state: LineState = Field(default=LineState.PENDING)


class ProjectPullLineCreate(SQLModel):
    line_kind: SaleLineKind
    product_id: uuid.UUID
    unit_serial: str | None = Field(default=None, max_length=64)  # UNIT lines
    requested_qty: int | None = Field(default=None, gt=0, le=1_000_000)  # PART lines


class ProjectPullCreate(SQLModel):
    project_id: uuid.UUID
    admin_notes: str | None = Field(default=None, max_length=512)
    lines: list[ProjectPullLineCreate] = Field(min_length=1, max_length=200)


class ProjectPullFulfillLine(SQLModel):
    line_id: uuid.UUID
    fulfilled_qty: int = Field(ge=0, le=1_000_000)


class ProjectPullFulfill(SQLModel):
    lines: list[ProjectPullFulfillLine] = Field(default_factory=list, max_length=200)


class ProjectPullLinePublic(SQLModel):
    id: uuid.UUID
    line_kind: SaleLineKind
    product_id: uuid.UUID
    product_sku: str
    model_name: str
    unit_serial: str | None
    requested_qty: int | None
    fulfilled_qty: int
    line_state: LineState


class ProjectPullPublic(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    # Display labels resolved at read time so staff (who can't list the
    # admin-only projects endpoint) can render the queue without an extra call.
    project_name: str
    project_code: str
    customer_id: uuid.UUID
    customer_name: str
    state: ProjectPullState
    admin_notes: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    fulfilled_at: datetime | None
    fulfilled_by_user_id: uuid.UUID | None
    cancelled_at: datetime | None
    cancelled_by_user_id: uuid.UUID | None
    lines: list[ProjectPullLinePublic]


class PricingOverridesPublic(SQLModel):
    data: list[PricingOverridePublic]
    count: int


class ProjectPullsPublic(SQLModel):
    data: list[ProjectPullPublic]
    count: int


# --- Notifications (FR-018; M007/M019) ----------------------------------------


class NotificationPreference(SQLModel, table=True):
    # Per-user M2M opt-in for a (channel, event) pair. UNIQUE keeps one row per
    # (user, channel, event) so the upsert is deterministic.
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "channel",
            "event_type",
            name="uq_notification_preference_user_channel_event",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, index=True)
    channel: NotificationChannel
    event_type: NotificationEvent
    enabled: bool = Field(default=True)
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class NotificationLog(SQLModel, table=True):
    # Append-only; enforced by trg_notificationlog_append_only (M021, BEFORE
    # UPDATE OR DELETE trigger).
    # Index (status, created_at) drives the weekly FAILED-row admin review.
    __table_args__ = (
        Index(
            "ix_notification_log_status_created", "status", "created_at"
        ),
        CheckConstraint(
            "attempts >= 0", name="ck_notification_log_attempts_nn"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel: NotificationChannel
    event_type: NotificationEvent
    target_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True
    )
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    status: NotificationStatus
    attempts: int
    last_error: str | None = Field(default=None, max_length=1024)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )


class TelegramConnectCode(SQLModel, table=True):
    """A short-lived, single-use code binding a Telegram `/start` deep link
    back to the user who requested it.

    This is an authentication boundary, not a mere correlation key: whoever's
    Telegram account echoes the code back gets bound to `user_id`. The code
    must therefore be unguessable (minted with `secrets.token_urlsafe`, not a
    short/sequential value), single-use (`consumed_at` set atomically on
    confirm), and short-lived (`expires_at`, checked at confirm time).
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, index=True)
    code: str = Field(unique=True, index=True, max_length=32)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    consumed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class NotificationPreferencePublic(SQLModel):
    # Nullable: the grid returns synthetic rows for pairs the user has never
    # opted into, which have no database row yet. Clients key on
    # (channel, event_type), not id.
    id: uuid.UUID | None
    channel: NotificationChannel
    event_type: NotificationEvent
    enabled: bool
    # Whether the user has an address configured for `channel` at all. A
    # checkbox with channel_connected=False can never actually deliver.
    channel_connected: bool


class NotificationPreferenceUpdate(SQLModel):
    channel: NotificationChannel
    event_type: NotificationEvent
    enabled: bool


class NotificationPreferencesUpdate(SQLModel):
    preferences: list[NotificationPreferenceUpdate] = Field(
        min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def _no_duplicate_pairs(self) -> "NotificationPreferencesUpdate":
        seen: set[tuple[NotificationChannel, NotificationEvent]] = set()
        for upd in self.preferences:
            key = (upd.channel, upd.event_type)
            if key in seen:
                raise ValueError(
                    f"duplicate (channel, event_type) pair: "
                    f"{upd.channel.value}/{upd.event_type.value}"
                )
            seen.add(key)
        return self


class TelegramConnectResponse(SQLModel):
    code: str
    deep_link: str
    qr_code_data_uri: str
    expires_at: datetime


class TelegramConfirmRequest(SQLModel):
    code: str


class TelegramConfirmOutcome(str, enum.Enum):
    """Why a confirm attempt ended. PENDING is the ordinary "the user hasn't
    tapped Start yet" case and must stay distinguishable from the terminal
    failures below, or the client would abort a poll that just needs more
    time -- or, worse, keep polling forever on something polling can't fix."""

    CONNECTED = "CONNECTED"
    PENDING = "PENDING"
    # This Telegram chat already backs a different account (UNIQUE
    # telegram_chat_id). Terminal: retrying cannot resolve it.
    CHAT_ALREADY_LINKED = "CHAT_ALREADY_LINKED"


class TelegramConfirmResult(SQLModel):
    connected: bool
    telegram_username: str | None = None
    # Human-readable reason, set only on a terminal failure the user must act
    # on. None on both success and PENDING -- the client keeps polling while
    # this is null and stops as soon as it isn't.
    error: str | None = None


class TelegramTestResult(SQLModel):
    ok: bool
    detail: str | None = None


class TelegramStatus(SQLModel):
    connected: bool
    telegram_username: str | None = None
    # True only when the MOST RECENT Telegram NotificationLog for this user
    # is FAILED -- a later successful send clears it, since the binding has
    # recovered (a stale reconnect, the user unblocking the bot, etc).
    delivery_failing: bool = False
    last_error: str | None = None


# --- Channel-margin report (FR-013; read-only aggregation) --------------------


MoneyTHB = Annotated[Decimal, Field(decimal_places=2, max_digits=14)]


class MarginDimension(str, enum.Enum):
    CHANNEL = "channel"
    PRODUCT = "product"
    CUSTOMER = "customer"
    PROJECT = "project"


class MarginBreakdownRow(SQLModel):
    key: str  # channel name, entity UUID as str, or "" for the (none) bucket
    label: str
    revenue_thb: MoneyTHB
    cogs_thb: MoneyTHB
    margin_thb: MoneyTHB


class MarginBreakdownReport(SQLModel):
    month: str  # "YYYY-MM"
    group_by: MarginDimension
    channel: Channel | None  # filter applied; None = all channels
    rows: list[MarginBreakdownRow]
    total_revenue_thb: MoneyTHB
    total_cogs_thb: MoneyTHB
    total_margin_thb: MoneyTHB


# --- Stock-on-hand dashboard (FR-012; both roles, no cost fields) -------------


class StockOnHandRow(SQLModel):
    product_id: uuid.UUID
    sku: str
    model_name: str
    brand: str | None
    category: str | None
    tracking_mode: TrackingMode
    quantity_on_hand: int


class StockOnHandResponse(SQLModel):
    rows: list[StockOnHandRow]


class BatchDrillRow(SQLModel):
    batch_no: str
    remaining_qty: int
    received_at: datetime
    # No purchase_cost_thb: COGS stays admin-only; this view is both-roles.


class UnitDrillRow(SQLModel):
    id: uuid.UUID  # unit identity — lets the Stock screen reprint the QR label
    castranova_barcode: str
    supplier_serial: str
    current_state: UnitState
    received_at: datetime
    # No purchase_cost_thb: COGS stays admin-only; this view is both-roles.


# --- Customer dashboard (FR-020; role-tiered, spec §6.5 / S7) ------------------


class TransactionSummaryPublic(SQLModel):
    kind: str  # "SALE" | "MAINTENANCE" | "PROJECT_PULL"
    reference_id: uuid.UUID
    occurred_at: datetime


class ProjectSummaryStaffPublic(SQLModel):
    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    # No budget / consumed_cost — staff redaction.


class ProjectSummaryAdminPublic(ProjectSummaryStaffPublic):
    budget_thb: Decimal | None
    consumed_cost_thb: Decimal


class CustomerDashboardStaffPublic(SQLModel):
    customer: CustomerPublic
    transactions: list[TransactionSummaryPublic]
    active_projects: list[ProjectSummaryStaffPublic]
    closed_projects: list[ProjectSummaryStaffPublic]


class CustomerDashboardAdminPublic(CustomerDashboardStaffPublic):
    # Financial fields are REQUIRED so a staff payload cannot upcast to admin.
    lifetime_sale_revenue_thb: Decimal
    lifetime_sale_cogs_thb: Decimal
    lifetime_sale_margin_thb: Decimal
    lifetime_maintenance_revenue_thb: Decimal
    lifetime_maintenance_cogs_thb: Decimal
    lifetime_maintenance_margin_thb: Decimal
    lifetime_project_cogs_thb: Decimal
    # Narrowed to the admin project row (adds budget/consumed_cost); the staff
    # base declares the redacted row. list invariance → explicit override.
    active_projects: list[ProjectSummaryAdminPublic]  # type: ignore[assignment]
    closed_projects: list[ProjectSummaryAdminPublic]  # type: ignore[assignment]


class ProjectStaffPublic(SQLModel):
    # Redacted project view for the staff dashboard: every ProjectPublic field
    # EXCEPT budget_thb (a financial field staff must never see). ProjectPublic
    # inherits budget_thb from ProjectBase, so the staff dashboard cannot reuse
    # it directly without leaking the budget.
    id: uuid.UUID
    code: str
    name: str
    customer_id: uuid.UUID
    start_date: date | None
    end_date: date | None
    status: ProjectStatus


class ProjectDashboardStaffPublic(SQLModel):
    project: ProjectStaffPublic
    pulls: list[TransactionSummaryPublic]  # kind="PROJECT_PULL"
    # No budget / consumed_cost — staff redaction.


class ProjectDashboardAdminPublic(ProjectDashboardStaffPublic):
    # Admin sees the full project (adds back budget_thb). consumed_cost_thb is
    # REQUIRED so a staff payload cannot upcast to admin; budget_thb is
    # intentionally optional (a project may have no budget).
    project: ProjectPublic  # type: ignore[assignment]
    budget_thb: Decimal | None
    consumed_cost_thb: Decimal


# --- Override-exceptions report (FR-010; read-only) ---------------------------


class OverrideExceptionRow(SQLModel):
    id: uuid.UUID
    target_kind: OverrideTargetKind
    product_id: uuid.UUID
    sku: str
    default_price_thb: MoneyTHB
    requested_price_thb: MoneyTHB
    deviation_pct: Decimal
    reason: str
    state: OverrideState
    created_by_user_id: uuid.UUID
    created_at: datetime
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None


class OverrideExceptionsReport(SQLModel):
    month: str  # "YYYY-MM"
    total: int
    auto_approved: int
    pending: int
    approved: int
    rejected: int
    rows: list[OverrideExceptionRow]


# --- Holding-period report (FR-014; read-only) --------------------------------


class HoldingPeriodRow(SQLModel):
    tracking_mode: TrackingMode
    product_id: uuid.UUID
    sku: str
    # SERIALIZED: the unit barcode (one row per in-stock unit). QUANTITY: the
    # oldest non-depleted batch_no (one rolled-up row per SKU).
    reference: str
    received_at: datetime
    holding_days: int
    quantity: int  # 1 for a unit; sum(remaining_qty) for a SKU rollup
    over_threshold: bool


class HoldingPeriodReport(SQLModel):
    threshold_days: int
    generated_at: datetime
    rows: list[HoldingPeriodRow]


# --- Search (FR-015; read-only, both roles — no cost fields) -------------------


class SerialMovementPublic(SQLModel):
    event_type: MovementType
    from_location_id: uuid.UUID | None
    to_location_id: uuid.UUID | None
    occurred_at: datetime
    actor_user_id: uuid.UUID
    sale_id: uuid.UUID | None
    service_ticket_id: uuid.UUID | None
    project_pull_id: uuid.UUID | None
    stock_adjustment_id: uuid.UUID | None
    notes: str | None
    # FR-015 enrichment (resolved at read time; no cost — serial search is
    # cost-free for both roles).
    from_location_name: str | None = None
    to_location_name: str | None = None
    actor_name: str | None = None
    reference_kind: str | None = None  # SALE | SERVICE_TICKET | PROJECT_PULL | STOCK_ADJUSTMENT
    reference_label: str | None = None


class SerialSearchResult(SQLModel):
    castranova_barcode: str
    product_id: uuid.UUID
    sku: str
    supplier_serial: str
    current_state: UnitState
    movements: list[SerialMovementPublic]  # chronological (occurred_at asc)


class SkuBatchPublic(SQLModel):
    # No purchase_cost_thb: COGS stays admin-only (search is both-roles).
    batch_no: str
    received_at: datetime
    received_qty: int
    remaining_qty: int
    is_adjustment: bool


class SkuSearchResult(SQLModel):
    sku: str
    product_id: uuid.UUID
    tracking_mode: TrackingMode
    total_on_hand: int
    batches: list[SkuBatchPublic]  # QUANTITY only; empty for SERIALIZED
    consumption: list["SkuConsumptionEventPublic"] = []  # QUANTITY only


# --- SKU consumption history (FR-015) -----------------------------------------


class SkuConsumptionEventPublic(SQLModel):
    """One consuming part_movement, STAFF view — attribution only, NO cost.
    Any NEW cost/margin field MUST go on the Admin subclass only; staff must
    never see cost data (mirrors SaleStaffPublic)."""

    event_type: MovementType  # SOLD | MAINTENANCE_OUT | PROJECT_OUT | ADJUSTED_OUT
    occurred_at: datetime
    quantity: int
    reference_kind: str  # SALE | SERVICE_TICKET | PROJECT_PULL | STOCK_ADJUSTMENT
    reference_id: uuid.UUID
    customer_name: str | None = None
    project_name: str | None = None
    project_code: str | None = None
    actor_name: str | None = None
    notes: str | None = None


class SkuConsumptionDrawAdminPublic(SQLModel):
    """One FIFO batch draw inside a consumption event — ADMIN only (cost)."""

    batch_no: str
    quantity: int
    unit_cost_thb: Decimal
    total_cost_thb: Decimal


class SkuConsumptionEventAdminPublic(SkuConsumptionEventPublic):
    total_cost_thb: Decimal
    draws: list[SkuConsumptionDrawAdminPublic]


class SkuBatchAdminPublic(SkuBatchPublic):
    purchase_cost_thb: Decimal  # PRD FR-015 batch attribution; admin only


class SkuSearchAdminResult(SQLModel):
    sku: str
    product_id: uuid.UUID
    tracking_mode: TrackingMode
    total_on_hand: int
    batches: list[SkuBatchAdminPublic]
    consumption: list[SkuConsumptionEventAdminPublic]


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None
    type: Literal["access", "refresh"] | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
