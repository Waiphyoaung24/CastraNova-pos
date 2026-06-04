import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Index, Numeric, UniqueConstraint, func, text
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


class AdjustmentTarget(str, enum.Enum):
    UNIT = "UNIT"
    QUANTITY = "QUANTITY"


class CustomerType(str, enum.Enum):
    DEALER = "DEALER"
    END_CUSTOMER = "END_CUSTOMER"


class ProjectStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    role: UserRole = Field(default=UserRole.BKK_ADMIN)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


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
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


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
    # may collide across suppliers; index (current_state, product_id) for SOH (§4.8).
    __table_args__ = (
        UniqueConstraint("castranova_barcode", name="uq_unit_castranova_barcode"),
        UniqueConstraint(
            "supplier_id", "supplier_serial", name="uq_unit_supplier_serial"
        ),
        Index("ix_unit_state_product", "current_state", "product_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    received_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
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
    # FK targets (sale/service_ticket/project_pull/stock_adjustment) are introduced
    # in later migrations; columns stay nullable and the FK constraints are wired
    # when each table lands (M010, M013, M012, M014).
    sale_id: uuid.UUID | None = Field(default=None)
    service_ticket_id: uuid.UUID | None = Field(default=None)
    project_pull_id: uuid.UUID | None = Field(default=None)
    stock_adjustment_id: uuid.UUID | None = Field(default=None)
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


# --- Serialized receive (FR-005) request/response -----------------------------


class ReceivePiece(SQLModel):
    supplier_serial: str = Field(max_length=128)
    purchase_cost_thb: Decimal


class ReceiveSerializedRequest(SQLModel):
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    pieces: list[ReceivePiece] = Field(min_length=1)
    idempotency_key: uuid.UUID


class ReceiveSerializedResponse(SQLModel):
    units: list[UnitPublic]


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


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
