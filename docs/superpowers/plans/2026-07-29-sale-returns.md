# Sale Returns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin record a customer return of sale lines (UNIT or PART), restoring stock at the original FIFO cost and reversing the sale's margin contribution in the return month.

**Architecture:** A first-class `SaleReturn` / `SaleReturnLine` pair records the event; stock is restored by *appending* reversal movements (`UnitMovement(RETURNED)` / `PartMovement(RETURNED)` + `CostLine`s at the original `unit_cost_thb`) and incrementing `PartBatch.remaining_qty`. The original sale's `CostLine`s are the cost source, so no cost drift is possible. The channel-margin report keys returns on `SaleReturn.returned_at`, so past months stay immutable.

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL 18, pytest; React + TanStack Query/Router, shadcn/ui, `@hey-api/openapi-ts` SDK, vitest, Playwright.

**Source design:** `docs/superpowers/specs/2026-07-25-sale-returns-design.md` (approved 2026-07-25).

## Global Constraints

Every task's requirements implicitly include this section.

- **Branch:** work on a feature branch off `dev_wth`; PR targets `dev`. Never push to `master`.
- **Never run tests against the dev `app` database.** The pytest session fixture and the Playwright global setup both TRUNCATE whatever DB they are pointed at. All backend tests in this plan run against `app_test`.
- **Backend test command** (the dev `backend` container does not contain `tests/`, so tests run in a one-off container that mounts the working tree):
  ```bash
  # One-time: build an env file pointing at app_test.
  docker exec castranova-pos-backend-1 printenv \
    | grep -E "^(POSTGRES|SECRET_KEY|FIRST_SUPERUSER|ENVIRONMENT|PROJECT_NAME|EMAIL|SMTP|DOMAIN|FRONTEND|BACKEND_CORS|SENTRY)" \
    | sed 's/^POSTGRES_DB=.*/POSTGRES_DB=app_test/' > backend/.test.env

  # Every run:
  MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
    --env-file backend/.test.env \
    -v "$PWD/backend:/app/backend" -w /app/backend backend:latest \
    python -m pytest <TEST_PATH> -q
  ```
  `backend/.test.env` must be added to `.gitignore` and never committed.
- **Migrations run the same way:** replace the `python -m pytest ...` tail with `alembic upgrade head`. Apply to `app_test` first, then to the dev `app` DB (`docker compose exec -T backend alembic upgrade head`) once green.
- **Regenerate the SDK from a live backend, never inside the frontend container** — the image-baked `openapi.json` is stale and silently drops new params. Dump `openapi.json` from the running backend, then run `bunx run generate-client` in a one-off frontend container. Only `schemas.gen.ts` / `sdk.gen.ts` / `types.gen.ts` are real changes; restore `core/*` and `index.ts` if they show EOL-only churn.
- **Playwright:** always `E2E_SKIP_DB_RESET=1`.
- **Never hand-edit** `frontend/src/client/` or `frontend/src/routeTree.gen.ts`.
- **Alembic head is currently `f1a2b3c4d5e6` (m034).** This plan adds exactly one migration, **m035**, revision id `a2b3c4d5e6f7`, `down_revision = 'f1a2b3c4d5e6'`.
- **mypy strict + ruff + biome must pass.** Annotate everything.
- **Money is `Decimal`,** quantized to cents (`Decimal("0.01")`) at report boundaries only — never mid-calculation.
- **Permissions:** every new endpoint is admin-only via `AdminUser` / `Depends(get_admin)` from `app/api/deps.py`.
- **Refund amount is fixed** at the original `SaleLine.unit_price_thb`. No discretion, no restocking fee, no editing or deleting a recorded return.

### Corrections to the design doc (verified against the code)

Two statements in the approved design are wrong about the current codebase. The plan below uses the corrected versions:

1. **`MovementType` is a native PostgreSQL ENUM type**, not a string column. `backend/app/alembic/versions/79e9c3acbe2f_m008_...py:45` creates `sa.Enum(..., name='movementtype')`. Adding `RETURNED` therefore requires `ALTER TYPE movementtype ADD VALUE`, which must run in an Alembic `autocommit_block()`. PostgreSQL cannot remove an enum value, so the downgrade leaves it in place.
2. **Batch locks are taken in `(received_at, id)` order, not `id` order.** `consume_quantity_fifo` (crud.py:1166) orders `FOR UPDATE` by `(PartBatch.received_at, PartBatch.id)`. A return that locked by `id` alone could deadlock against a concurrent sale. The return path uses the same `(received_at, id)` order.

Additionally, the design's migration is numbered m034, which is already taken — this plan uses **m035**.

### Interfaces produced by this plan (quick reference)

```python
# backend/app/models.py
class MovementType(str, enum.Enum): ...  # + RETURNED = "RETURNED"
class SaleReturn(SQLModel, table=True): ...
class SaleReturnLine(SQLModel, table=True): ...
class SaleReturnLineInput(SQLModel): sale_line_id: uuid.UUID; quantity: int
class SaleReturnCreateRequest(SQLModel): idempotency_key: uuid.UUID; reason: str; lines: list[SaleReturnLineInput]
class SaleReturnLinePublic(SQLModel): ...
class SaleReturnPublic(SQLModel): ...
class ReturnableLinePublic(SQLModel): ...
class ReturnableSalePublic(SQLModel): ...
class ReturnableSalesPublic(SQLModel): sales: list[ReturnableSalePublic]

# backend/app/crud.py
def create_sale_return(*, session: Session, sale_id: uuid.UUID,
                       payload: SaleReturnCreateRequest,
                       created_by_user_id: uuid.UUID) -> SaleReturn
def list_returnable_sales(*, session: Session, castranova_barcode: str | None = None,
                          sku: str | None = None, limit: int = 20) -> ReturnableSalesPublic

# backend/app/api/routes/sales.py
POST /api/v1/sales/{sale_id}/returns   -> SaleReturnPublic          (admin)
GET  /api/v1/sales/returnable          -> ReturnableSalesPublic     (admin)

# frontend/src/lib/sale-return.ts
export interface ReturnDraft { saleId: string; saleLineId: string; quantity: string; reason: string }
export const emptyReturnDraft: ReturnDraft
export function canSubmitReturn(d: ReturnDraft, maxQuantity: number): boolean
export function buildReturnPayload(d: ReturnDraft, idempotencyKey: string): SaleReturnCreateRequest
```

---

### Task 1: Enum value, state-machine edge, models, migration m035

Schema foundation. Nothing else can be written until `RETURNED` exists and the two tables are creatable.

**Files:**
- Modify: `backend/app/models.py:56-62` (MovementType), and append a new section after `SaleCreateRequest` (~line 1423)
- Modify: `backend/app/core/state_machine.py:16-22`
- Create: `backend/app/alembic/versions/a2b3c4d5e6f7_m035_sale_return.py`
- Modify: `backend/tests/test_enums.py:39-47`
- Create: `backend/tests/core/test_return_transition.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `MovementType.RETURNED`; the `(UnitState.SOLD, MovementType.RETURNED) -> UnitState.IN_STOCK` edge; tables `salereturn` / `salereturnline`; the model + schema classes listed in the quick reference above.

- [ ] **Step 1: Verify the test harness runs against `app_test` before touching anything**

Build the env file and run the existing enum suite. If this fails, stop and fix the harness — do not fall back to the dev `app` DB.

```bash
docker exec castranova-pos-backend-1 printenv \
  | grep -E "^(POSTGRES|SECRET_KEY|FIRST_SUPERUSER|ENVIRONMENT|PROJECT_NAME|EMAIL|SMTP|DOMAIN|FRONTEND|BACKEND_CORS|SENTRY)" \
  | sed 's/^POSTGRES_DB=.*/POSTGRES_DB=app_test/' > backend/.test.env
echo "backend/.test.env" >> .gitignore

MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/test_enums.py -q
```

Expected: PASS, and `grep POSTGRES_DB backend/.test.env` shows `app_test`.

- [ ] **Step 2: Write the failing enum + transition tests**

In `backend/tests/test_enums.py`, extend `test_movement_types`:

```python
def test_movement_types():
    assert {m.value for m in MovementType} == {
        "RECEIVED",
        "SOLD",
        "MAINTENANCE_OUT",
        "PROJECT_OUT",
        "ADJUSTED_OUT",
        "RETURNED",
    }
```

Create `backend/tests/core/test_return_transition.py`:

```python
"""The SOLD -> IN_STOCK edge, reachable only via a sale return (m035)."""

import pytest

from app.core.state_machine import IllegalTransition, assert_unit_transition
from app.models import MovementType, UnitState


def test_sold_unit_returns_to_stock():
    assert (
        assert_unit_transition(UnitState.SOLD, MovementType.RETURNED)
        == UnitState.IN_STOCK
    )


def test_in_stock_unit_cannot_be_returned():
    with pytest.raises(IllegalTransition):
        assert_unit_transition(UnitState.IN_STOCK, MovementType.RETURNED)


def test_adjusted_out_unit_cannot_be_returned():
    with pytest.raises(IllegalTransition):
        assert_unit_transition(UnitState.ADJUSTED_OUT, MovementType.RETURNED)
```

- [ ] **Step 3: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/test_enums.py tests/core/test_return_transition.py -q
```

Expected: FAIL — `AttributeError: RETURNED` / assertion mismatch on the enum set.

- [ ] **Step 4: Add the enum value and the state-machine edge**

`backend/app/models.py`:

```python
class MovementType(str, enum.Enum):
    RECEIVED = "RECEIVED"
    SOLD = "SOLD"
    MAINTENANCE_OUT = "MAINTENANCE_OUT"
    PROJECT_OUT = "PROJECT_OUT"
    ADJUSTED_OUT = "ADJUSTED_OUT"
    # Sale return (m035): the only inbound event besides RECEIVED. Restores a
    # SOLD unit to stock / re-credits the FIFO batches a PART line consumed.
    RETURNED = "RETURNED"
```

`backend/app/core/state_machine.py`:

```python
_TABLE: dict[tuple[UnitState, MovementType], UnitState] = {
    (UnitState.RECEIVED, MovementType.RECEIVED): UnitState.IN_STOCK,
    (UnitState.IN_STOCK, MovementType.SOLD): UnitState.SOLD,
    (UnitState.IN_STOCK, MovementType.MAINTENANCE_OUT): UnitState.MAINTENANCE_OUT,
    (UnitState.IN_STOCK, MovementType.PROJECT_OUT): UnitState.PROJECT_OUT,
    (UnitState.IN_STOCK, MovementType.ADJUSTED_OUT): UnitState.ADJUSTED_OUT,
    # Sale return only (m035). Deliberately the single edge back out of a
    # terminal-looking state: nothing else may resurrect a SOLD unit.
    (UnitState.SOLD, MovementType.RETURNED): UnitState.IN_STOCK,
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Same command as Step 3. Expected: PASS.

- [ ] **Step 6: Add the models**

Append to `backend/app/models.py` immediately after `SaleCreateRequest` (before the `# --- Service ticket` banner):

```python
# --- Sale return (m035; design 2026-07-25) ------------------------------------


class SaleReturn(SQLModel, table=True):
    # Insert-only in practice (no update/delete endpoint), but NOT trigger-
    # protected: the append-only guarantee that matters lives on the movements
    # this row produces (unit_movement / part_movement / cost_line), which the
    # M021 reject_ledger_mutation triggers already cover.
    # returned_at is the report's date key — every margin_report aggregation for
    # returns closes over [start, end) on it, so it is indexed like sale.sold_at.
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_sale_return_idempotency_key"),
        Index("ix_salereturn_returned_at", "returned_at"),
        Index("ix_salereturn_sale_id", "sale_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sale_id: uuid.UUID = Field(foreign_key="sale.id", nullable=False)
    created_by_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True
    )
    idempotency_key: uuid.UUID
    reason: str = Field(max_length=512)
    returned_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"server_default": func.now()},
    )
    total_refund_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    total_cogs_restored_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]


class SaleReturnLine(SQLModel, table=True):
    # The over-return invariant (SUM(quantity) per sale_line <= saleline.quantity)
    # spans rows, so it is enforced in crud under a FOR UPDATE lock on the sale
    # line, not by a CHECK.
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_salereturnline_quantity_positive"),
        CheckConstraint(
            "cogs_restored_thb >= 0", name="ck_salereturnline_cogs_nonneg"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sale_return_id: uuid.UUID = Field(
        foreign_key="salereturn.id", nullable=False, index=True
    )
    sale_line_id: uuid.UUID = Field(
        foreign_key="saleline.id", nullable=False, index=True
    )
    quantity: int
    # Refund basis, snapshot-copied from the sale line at return time.
    unit_price_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    # Exact cost restored, summed from the reversal cost_lines (UNIT lines: the
    # unit's purchase_cost_thb). Never a re-derived average.
    cogs_restored_thb: Decimal = Field(sa_type=Numeric(12, 2))  # type: ignore[call-overload]


class SaleReturnLineInput(SQLModel):
    sale_line_id: uuid.UUID
    # UNIT lines must be exactly 1 (checked in crud against the line kind).
    quantity: int = Field(default=1, gt=0, le=1_000_000)


class SaleReturnCreateRequest(SQLModel):
    idempotency_key: uuid.UUID
    reason: str = Field(min_length=1, max_length=512)
    lines: list[SaleReturnLineInput] = Field(min_length=1, max_length=100)


class SaleReturnLinePublic(SQLModel):
    id: uuid.UUID
    sale_line_id: uuid.UUID
    quantity: int
    unit_price_thb: Decimal
    cogs_restored_thb: Decimal


class SaleReturnPublic(SQLModel):
    # Admin-only surface (returns are an admin desk action), so cost fields are
    # exposed here deliberately — unlike SaleStaffPublic there is no staff variant.
    id: uuid.UUID
    sale_id: uuid.UUID
    reason: str
    returned_at: datetime
    total_refund_thb: Decimal
    total_cogs_restored_thb: Decimal
    created_by_user_id: uuid.UUID
    lines: list[SaleReturnLinePublic]


class ReturnableLinePublic(SQLModel):
    sale_line_id: uuid.UUID
    line_kind: SaleLineKind
    product_id: uuid.UUID | None
    unit_id: uuid.UUID | None
    label: str  # "SKU — Model name"
    quantity_sold: int
    quantity_returned: int
    quantity_returnable: int
    unit_price_thb: Decimal


class ReturnableSalePublic(SQLModel):
    sale_id: uuid.UUID
    sold_at: datetime
    customer_id: uuid.UUID
    customer_name: str
    lines: list[ReturnableLinePublic]


class ReturnableSalesPublic(SQLModel):
    sales: list[ReturnableSalePublic]
```

- [ ] **Step 7: Write the migration**

Create `backend/app/alembic/versions/a2b3c4d5e6f7_m035_sale_return.py`:

```python
"""m035 sale return

Two insert-only tables recording a customer return of sale lines, plus the
RETURNED value on the native `movementtype` enum.

ENUM NOTE: movementtype is a real PostgreSQL enum (created in m008,
79e9c3acbe2f). ALTER TYPE ... ADD VALUE cannot be used in the same
transaction that adds it, so it runs in an autocommit_block. PostgreSQL
offers no way to remove an enum value — the downgrade drops the tables and
deliberately leaves 'RETURNED' on the type.

GRANT NOTE: no explicit grants here. m026's ALTER DEFAULT PRIVILEGES already
gives the app role SELECT/INSERT/UPDATE on tables created by later
migrations. These are NOT append-only ledger tables (m026's REVOKE list is
for unitmovement/partmovement/costline/pricechange/notificationlog), so the
same posture as sale/saleline applies: no trigger, no REVOKE, no update or
delete endpoint.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6

"""
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE movementtype ADD VALUE IF NOT EXISTS 'RETURNED'")

    op.create_table(
        'salereturn',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sale_id', sa.Uuid(), nullable=False),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.Uuid(), nullable=False),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column(
            'returned_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('total_refund_thb', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            'total_cogs_restored_thb', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sale.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_sale_return_idempotency_key'),
    )
    op.create_index('ix_salereturn_returned_at', 'salereturn', ['returned_at'])
    op.create_index('ix_salereturn_sale_id', 'salereturn', ['sale_id'])
    op.create_index(
        'ix_salereturn_created_by_user_id', 'salereturn', ['created_by_user_id']
    )

    op.create_table(
        'salereturnline',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sale_return_id', sa.Uuid(), nullable=False),
        sa.Column('sale_line_id', sa.Uuid(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price_thb', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            'cogs_restored_thb', sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.CheckConstraint('quantity > 0', name='ck_salereturnline_quantity_positive'),
        sa.CheckConstraint(
            'cogs_restored_thb >= 0', name='ck_salereturnline_cogs_nonneg'
        ),
        sa.ForeignKeyConstraint(['sale_line_id'], ['saleline.id']),
        sa.ForeignKeyConstraint(['sale_return_id'], ['salereturn.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_salereturnline_sale_return_id', 'salereturnline', ['sale_return_id']
    )
    op.create_index(
        'ix_salereturnline_sale_line_id', 'salereturnline', ['sale_line_id']
    )


def downgrade() -> None:
    op.drop_index('ix_salereturnline_sale_line_id', table_name='salereturnline')
    op.drop_index('ix_salereturnline_sale_return_id', table_name='salereturnline')
    op.drop_table('salereturnline')
    op.drop_index('ix_salereturn_created_by_user_id', table_name='salereturn')
    op.drop_index('ix_salereturn_sale_id', table_name='salereturn')
    op.drop_index('ix_salereturn_returned_at', table_name='salereturn')
    op.drop_table('salereturn')
    # 'RETURNED' stays on movementtype: PostgreSQL cannot drop an enum value.
```

- [ ] **Step 8: Apply the migration to `app_test` and verify it is head**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest alembic upgrade head

MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest alembic current
```

Expected: `a2b3c4d5e6f7 (head)`.

Then confirm the model matches the DB — an autogenerate diff must be empty:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest alembic check
```

Expected: "No new upgrade operations detected." If it reports a diff, reconcile the migration with `models.py` before proceeding.

- [ ] **Step 9: Run the full backend suite to confirm nothing regressed**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/ -q
```

Expected: 0 failed (the baseline on `dev_wth` is fully green).

- [ ] **Step 10: Commit**

```bash
git add backend/app/models.py backend/app/core/state_machine.py \
  backend/app/alembic/versions/a2b3c4d5e6f7_m035_sale_return.py \
  backend/tests/test_enums.py backend/tests/core/test_return_transition.py .gitignore
git commit -m "feat(returns): SaleReturn schema, RETURNED movement type, m035"
```

---

### Task 2: `create_sale_return` — validation, idempotency, and exact FIFO rollback for PART lines

The heart of the feature. Restores QUANTITY stock to the exact batches the sale consumed, at the exact cost.

**Files:**
- Modify: `backend/app/crud.py` — new section after `create_sale` (ends line 2730), before the `# --- Maintenance / service tickets` banner
- Create: `backend/tests/api/routes/test_sale_returns.py`

**Interfaces:**
- Consumes: `SaleReturn`, `SaleReturnLine`, `SaleReturnCreateRequest`, `MovementType.RETURNED` (Task 1); `_assert_replay_actor` (crud.py:206).
- Produces: `crud.create_sale_return(*, session, sale_id, payload, created_by_user_id) -> SaleReturn`, and the private helper `_return_part_line(...) -> Decimal` returning the exact cost restored.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/routes/test_sale_returns.py`. Follow `test_stock_adjustments.py` for fixture style.

```python
"""Sale returns (design 2026-07-25): FIFO rollback + margin reversal.

PART lines restore the exact batches the sale consumed, in reverse consumption
order, at the original unit_cost_thb. Over-return is a 409; replay is idempotent.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    ProductCreate,
    Sale,
    SaleCreateRequest,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SaleReturn,
    SaleReturnCreateRequest,
    SaleReturnLine,
    SaleReturnLineInput,
    SupplierCreate,
    TrackingMode,
)


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _seed(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _rand() -> str:
    return uuid.uuid4().hex[:8]


def _customer(db: Session) -> uuid.UUID:
    from app.models import CustomerCreate, CustomerType

    c = crud.create_customer(
        session=db,
        customer_in=CustomerCreate(
            name=f"Cust {_rand()}", type=CustomerType.END_CUSTOMER
        ),
    )
    return c.id


def _part_product(db: Session, *, price: str = "100.00") -> tuple[uuid.UUID, str]:
    sku = f"PART-{_rand()}"
    p = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku,
            model_name="Returnable part",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal(price),
        ),
    )
    return p.id, sku


def _receive(db: Session, *, product_id: uuid.UUID, qty: int, cost: str) -> PartBatch:
    """Receive one QUANTITY batch and return it."""
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup {_rand()}")
    )
    return crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier.id,
        received_qty=qty,
        purchase_cost_thb=Decimal(cost),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )


def _sell_parts(db: Session, *, sku: str, qty: int, customer_id: uuid.UUID) -> Sale:
    return crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=qty)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )


def _return(
    db: Session, *, sale: Sale, sale_line_id: uuid.UUID, quantity: int
) -> SaleReturn:
    return crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="customer changed their mind",
            lines=[
                SaleReturnLineInput(sale_line_id=sale_line_id, quantity=quantity)
            ],
        ),
        created_by_user_id=_user_id(db),
    )


def _line_of(db: Session, sale: Sale) -> SaleLine:
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).first()
    assert line is not None
    return line


# --- exact multi-batch rollback ---------------------------------------------


def test_return_restores_batches_in_reverse_consumption_order(db: Session) -> None:
    """5 sold from two batches (3 @ 10 + 2 @ 20); returning 4 restores the
    newest-consumed units first: all 2 from the second batch, 2 from the first."""
    _seed(db)
    product_id, sku = _part_product(db)
    b1 = _receive(db, product_id=product_id, qty=3, cost="10.00")
    b2 = _receive(db, product_id=product_id, qty=2, cost="20.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    assert db.get(PartBatch, b1.id).remaining_qty == 0
    assert db.get(PartBatch, b2.id).remaining_qty == 0

    ret = _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=4)

    db.refresh(b1)
    db.refresh(b2)
    assert b2.remaining_qty == 2  # newest batch fully restored first
    assert b1.remaining_qty == 2  # then 2 of the 3 older units
    # 2 * 20 + 2 * 10 = 60.00 restored, exactly the cost those units carried.
    assert ret.total_cogs_restored_thb == Decimal("60.00")
    assert ret.total_refund_thb == Decimal("400.00")  # 4 * retail 100


def test_second_partial_return_continues_where_the_first_stopped(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    b1 = _receive(db, product_id=product_id, qty=3, cost="10.00")
    b2 = _receive(db, product_id=product_id, qty=2, cost="20.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    line_id = _line_of(db, sale).id

    _return(db, sale=sale, sale_line_id=line_id, quantity=4)
    ret2 = _return(db, sale=sale, sale_line_id=line_id, quantity=1)

    db.refresh(b1)
    db.refresh(b2)
    assert b1.remaining_qty == 3  # the last unit comes from the oldest batch
    assert b2.remaining_qty == 2
    assert ret2.total_cogs_restored_thb == Decimal("10.00")


def test_return_appends_a_movement_and_cost_lines_at_original_cost(
    db: Session,
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="15.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))

    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)

    movement = db.exec(
        select(PartMovement).where(
            PartMovement.sale_id == sale.id,
            PartMovement.event_type == MovementType.RETURNED,
        )
    ).first()
    assert movement is not None
    assert movement.quantity == 2
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == movement.id)
    ).all()
    assert [cl.unit_cost_thb for cl in cost_lines] == [Decimal("15.00")]
    assert cost_lines[0].total_cost_thb == Decimal("30.00")


# --- guards ------------------------------------------------------------------


def test_over_return_is_409_and_restores_nothing(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    batch = _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    _return(db, sale=sale, sale_line_id=line_id, quantity=2)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=line_id, quantity=1)
    assert exc.value.status_code == 409

    db.refresh(batch)
    assert batch.remaining_qty == 2  # unchanged by the rejected return


def test_line_from_another_sale_is_404(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=4, cost="10.00")
    customer_id = _customer(db)
    sale_a = _sell_parts(db, sku=sku, qty=2, customer_id=customer_id)
    sale_b = _sell_parts(db, sku=sku, qty=2, customer_id=customer_id)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale_a, sale_line_id=_line_of(db, sale_b).id, quantity=1)
    assert exc.value.status_code == 404


def test_duplicate_sale_line_in_one_payload_is_422(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id

    with pytest.raises(HTTPException) as exc:
        crud.create_sale_return(
            session=db,
            sale_id=sale.id,
            payload=SaleReturnCreateRequest(
                idempotency_key=uuid.uuid4(),
                reason="x",
                lines=[
                    SaleReturnLineInput(sale_line_id=line_id, quantity=1),
                    SaleReturnLineInput(sale_line_id=line_id, quantity=1),
                ],
            ),
            created_by_user_id=_user_id(db),
        )
    assert exc.value.status_code == 422


def test_replay_returns_the_same_row_and_restocks_once(db: Session) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    batch = _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    key = uuid.uuid4()

    payload = SaleReturnCreateRequest(
        idempotency_key=key,
        reason="replay",
        lines=[SaleReturnLineInput(sale_line_id=line_id, quantity=2)],
    )
    first = crud.create_sale_return(
        session=db, sale_id=sale.id, payload=payload, created_by_user_id=_user_id(db)
    )
    second = crud.create_sale_return(
        session=db, sale_id=sale.id, payload=payload, created_by_user_id=_user_id(db)
    )

    assert first.id == second.id
    db.refresh(batch)
    assert batch.remaining_qty == 2  # restocked once, not twice
    assert (
        len(db.exec(select(SaleReturnLine).where(
            SaleReturnLine.sale_return_id == first.id
        )).all())
        == 1
    )
```

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_sale_returns.py -q
```

Expected: FAIL with `AttributeError: module 'app.crud' has no attribute 'create_sale_return'`.

> If `_receive` or `_sell_parts` fail for signature reasons, fix the helper against the real `crud.receive_quantity` / `crud.create_sale` signatures — do not weaken the assertions.

- [ ] **Step 3: Implement the PART path**

Add to `backend/app/crud.py` after `create_sale` (line 2730), and add `SaleReturn`, `SaleReturnLine`, `SaleReturnCreateRequest` to the `app.models` import block at the top.

```python
# --- Sale returns (design 2026-07-25) -----------------------------------------


def _sale_return_by_key(
    *, session: Session, idempotency_key: uuid.UUID
) -> SaleReturn | None:
    return session.exec(
        select(SaleReturn).where(SaleReturn.idempotency_key == idempotency_key)
    ).first()


def _returned_so_far(*, session: Session, sale_line_id: uuid.UUID) -> int:
    """Units of a sale line already returned. Only meaningful while the sale
    line is held FOR UPDATE — that lock is the serialization point."""
    total = session.exec(
        select(func.coalesce(func.sum(SaleReturnLine.quantity), 0)).where(
            SaleReturnLine.sale_line_id == sale_line_id
        )
    ).one()
    return int(total)


def _return_part_line(
    *,
    session: Session,
    ret: SaleReturn,
    sale_line: SaleLine,
    already_returned: int,
    quantity: int,
    actor_user_id: uuid.UUID,
    from_location_id: uuid.UUID,
    to_location_id: uuid.UUID,
) -> Decimal:
    """Roll back ``quantity`` units of a PART sale line onto the exact batches
    the sale consumed, at the exact cost, and return the cost restored.

    The sale's cost_lines record which batch supplied each unit. We walk them in
    REVERSE consumption order (newest-received batch first) and skip the units a
    prior partial return already restored, so repeated partial returns are
    deterministic and never restore the same unit twice. The batch is a cost
    bucket, not a physical bin: nobody knows which piece came back, and FIFO was
    itself an accounting convention — the return reverses that convention.
    """
    assert sale_line.product_id is not None  # PART lines always carry a product
    sold = session.exec(
        select(PartMovement).where(
            PartMovement.sale_id == sale_line.sale_id,
            PartMovement.product_id == sale_line.product_id,
            PartMovement.event_type == MovementType.SOLD,
        )
    ).first()
    if sold is None:
        raise HTTPException(
            status_code=409, detail="Original consumption movement not found"
        )

    # Reverse consumption order == reverse FIFO. Ordering by the batch's
    # (received_at, id) is deterministic across re-reads; cost_line.created_at
    # is not (same-transaction inserts).
    consumed = session.exec(
        select(CostLine, PartBatch)
        .join(PartBatch, col(CostLine.part_batch_id) == col(PartBatch.id))
        .where(CostLine.part_movement_id == sold.id)
        .order_by(col(PartBatch.received_at).desc(), col(PartBatch.id).desc())
    ).all()

    plan: list[tuple[uuid.UUID, int, Decimal]] = []  # (batch_id, qty, unit_cost)
    to_skip, to_restore = already_returned, quantity
    for cost_line, batch in consumed:
        avail = cost_line.quantity
        if to_skip:
            skipped = min(to_skip, avail)
            to_skip -= skipped
            avail -= skipped
        if avail and to_restore:
            take = min(avail, to_restore)
            plan.append((batch.id, take, cost_line.unit_cost_thb))
            to_restore -= take
        if to_restore == 0:
            break
    if to_restore:
        # Belt-and-suspenders: the caller's over-return check should have caught
        # this. Reaching here means the sale line and its cost lines disagree.
        raise HTTPException(
            status_code=409, detail="Return exceeds the quantity originally consumed"
        )

    # Re-lock the target batches in the SAME (received_at, id) order that
    # consume_quantity_fifo uses, so a concurrent sale and return on this product
    # acquire batch locks in one global order and cannot deadlock.
    locked = {
        b.id: b
        for b in session.exec(
            select(PartBatch)
            .where(col(PartBatch.id).in_([bid for bid, _, _ in plan]))
            .order_by(col(PartBatch.received_at), col(PartBatch.id))
            .with_for_update()
        ).all()
    }

    movement = PartMovement(
        product_id=sale_line.product_id,
        event_type=MovementType.RETURNED,
        quantity=quantity,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        sale_id=sale_line.sale_id,
        actor_user_id=actor_user_id,
        idempotency_key=uuid.uuid5(ret.idempotency_key, f"part:{sale_line.id}"),
    )
    session.add(movement)
    session.flush()

    restored = Decimal("0.00")
    for batch_id, qty, unit_cost in plan:
        batch = locked[batch_id]
        # Safe against ck_part_batch_qty_bounds (remaining_qty <= received_qty):
        # a batch is only ever credited back units it supplied to THIS sale.
        batch.remaining_qty += qty
        batch.updated_at = get_datetime_utc()
        session.add(batch)
        session.add(
            CostLine(
                part_movement_id=movement.id,
                part_batch_id=batch_id,
                quantity=qty,
                unit_cost_thb=unit_cost,
                total_cost_thb=qty * unit_cost,
            )
        )
        restored += qty * unit_cost
    return restored


def create_sale_return(
    *,
    session: Session,
    sale_id: uuid.UUID,
    payload: SaleReturnCreateRequest,
    created_by_user_id: uuid.UUID,
) -> SaleReturn:
    """Record a customer return of one or more sale lines, admin-only.

    Restores stock by APPENDING reversal movements (never mutating the ledgers):
    PART lines re-credit the exact batches the sale consumed at the original
    cost; UNIT lines walk SOLD -> IN_STOCK. Refund is fixed at the sale line's
    unit_price_thb. Everything commits in one transaction — any failing line
    rolls the whole return back. Idempotent on ``idempotency_key``.
    """
    replay = _sale_return_by_key(
        session=session, idempotency_key=payload.idempotency_key
    )
    if replay is not None:
        _assert_replay_actor(
            stored_user_id=replay.created_by_user_id,
            caller_user_id=created_by_user_id,
        )
        if replay.sale_id != sale_id:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used for a different sale",
            )
        return replay

    if session.get(Sale, sale_id) is None:
        raise HTTPException(status_code=404, detail="Sale not found")

    line_ids: set[uuid.UUID] = set()
    for line in payload.lines:
        if line.sale_line_id in line_ids:
            raise HTTPException(
                status_code=422,
                detail="Duplicate sale_line_id; merge into one line",
            )
        line_ids.add(line.sale_line_id)

    # Lock the cited sale lines in id order. This is the ONLY serialization point
    # for two concurrent returns of the same line: SaleReturnLine rows may not
    # exist yet, so FOR UPDATE on them would lock nothing.
    sale_lines = {
        sl.id: sl
        for sl in session.exec(
            select(SaleLine)
            .where(col(SaleLine.id).in_(line_ids))
            .order_by(col(SaleLine.id))
            .with_for_update()
        ).all()
    }
    for line in payload.lines:
        sl = sale_lines.get(line.sale_line_id)
        if sl is None or sl.sale_id != sale_id:
            raise HTTPException(
                status_code=404, detail="Sale line not part of this sale"
            )

    ygn = session.exec(select(Location).where(Location.code == "YGN_WH")).first()
    customer_loc = session.exec(
        select(Location).where(Location.code == "CUSTOMER")
    ).first()
    if not ygn or not customer_loc:
        raise HTTPException(status_code=500, detail="Locations not seeded")

    ret = SaleReturn(
        sale_id=sale_id,
        created_by_user_id=created_by_user_id,
        idempotency_key=payload.idempotency_key,
        reason=payload.reason,
        total_refund_thb=Decimal("0.00"),
        total_cogs_restored_thb=Decimal("0.00"),
    )
    session.add(ret)
    session.flush()

    total_refund = Decimal("0.00")
    total_cogs = Decimal("0.00")
    # Deterministic line order so concurrent returns take unit/batch locks in the
    # same order (mirrors create_sale's sorted part_reqs).
    for line in sorted(payload.lines, key=lambda ln: str(ln.sale_line_id)):
        sl = sale_lines[line.sale_line_id]
        already = _returned_so_far(session=session, sale_line_id=sl.id)
        if already + line.quantity > sl.quantity:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Over-return: {sl.quantity - already} returnable, "
                    f"requested {line.quantity}"
                ),
            )
        if sl.line_kind == SaleLineKind.UNIT:
            raise HTTPException(
                status_code=422, detail="UNIT line returns land in Task 3"
            )
        cogs = _return_part_line(
            session=session,
            ret=ret,
            sale_line=sl,
            already_returned=already,
            quantity=line.quantity,
            actor_user_id=created_by_user_id,
            from_location_id=customer_loc.id,
            to_location_id=ygn.id,
        )
        session.add(
            SaleReturnLine(
                sale_return_id=ret.id,
                sale_line_id=sl.id,
                quantity=line.quantity,
                unit_price_thb=sl.unit_price_thb,
                cogs_restored_thb=cogs,
            )
        )
        total_refund += sl.unit_price_thb * line.quantity
        total_cogs += cogs

    ret.total_refund_thb = total_refund
    ret.total_cogs_restored_thb = total_cogs
    session.add(ret)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = _sale_return_by_key(
            session=session, idempotency_key=payload.idempotency_key
        )
        if winner is None:
            raise
        _assert_replay_actor(
            stored_user_id=winner.created_by_user_id,
            caller_user_id=created_by_user_id,
        )
        return winner
    session.refresh(ret)
    return ret
```

> The `UNIT line returns land in Task 3` branch is a deliberate temporary stub, replaced in the very next task. Do not ship it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_sale_returns.py -q
```

Expected: PASS.

- [ ] **Step 5: Typecheck**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest bash -c "python -m mypy app && python -m ruff check app tests"
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_sale_returns.py
git commit -m "feat(returns): exact FIFO rollback for PART sale lines"
```

---

### Task 3: `create_sale_return` — UNIT lines

**Files:**
- Modify: `backend/app/crud.py` (replace the Task 2 stub; add `_return_unit_line` above `create_sale_return`)
- Modify: `backend/tests/api/routes/test_sale_returns.py`

**Interfaces:**
- Consumes: `create_sale_return` and its helpers (Task 2); `assert_unit_transition` (state_machine.py).
- Produces: `_return_unit_line(...) -> Decimal` (the unit's `purchase_cost_thb`); a returned unit is `IN_STOCK` and sellable again.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/routes/test_sale_returns.py`:

```python
# --- UNIT lines ---------------------------------------------------------------


def _serialized_unit(
    db: Session, *, price: str = "5000.00", cost: str = "3000.00"
) -> tuple[str, uuid.UUID]:
    """Receive one SERIALIZED unit; return (barcode, unit_id)."""
    from app.models import ReceivePiece

    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"UNIT-{_rand()}",
            model_name="Returnable unit",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb=Decimal(price),
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup {_rand()}")
    )
    # receive_serialized returns list[Unit] directly (crud.py:883).
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"S-{_rand()}", purchase_cost_thb=Decimal(cost)
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    return units[0].castranova_barcode, units[0].id


def _sell_unit(db: Session, *, barcode: str, customer_id: uuid.UUID) -> Sale:
    return crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )


def test_returned_unit_is_back_in_stock_and_sellable(db: Session) -> None:
    from app.models import Unit, UnitMovement, UnitState

    _seed(db)
    barcode, unit_id = _serialized_unit(db)
    customer_id = _customer(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=customer_id)
    sold_movement = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit_id,
            UnitMovement.event_type == MovementType.SOLD,
        )
    ).one()

    ret = _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    unit = db.get(Unit, unit_id)
    assert unit is not None
    assert unit.current_state == UnitState.IN_STOCK
    # Back where it stood before the sale, not left at the CUSTOMER location.
    assert unit.current_location_id == sold_movement.from_location_id
    assert ret.total_cogs_restored_thb == Decimal("3000.00")
    assert ret.total_refund_thb == Decimal("5000.00")

    # And it can be sold again.
    resale = _sell_unit(db, barcode=barcode, customer_id=customer_id)
    assert resale.total_thb == Decimal("5000.00")


def test_returned_unit_appends_a_returned_movement(db: Session) -> None:
    from app.models import UnitMovement

    _seed(db)
    barcode, unit_id = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    movement = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit_id,
            UnitMovement.event_type == MovementType.RETURNED,
        )
    ).first()
    assert movement is not None
    assert movement.sale_id == sale.id


def test_returning_the_same_unit_twice_is_409(db: Session) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))
    line_id = _line_of(db, sale).id
    _return(db, sale=sale, sale_line_id=line_id, quantity=1)

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=line_id, quantity=1)
    assert exc.value.status_code == 409


def test_unit_line_quantity_must_be_one(db: Session) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    with pytest.raises(HTTPException) as exc:
        _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)
    assert exc.value.status_code in (409, 422)
```

> `test_returning_the_same_unit_twice_is_409` passes via the over-return guard (`quantity_sold == 1`); the state-machine guard is the second line of defence. Both are fine — assert only the status code.

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_sale_returns.py -q -k unit
```

Expected: FAIL — `422 UNIT line returns land in Task 3`.

- [ ] **Step 3: Implement `_return_unit_line` and wire it in**

Add above `create_sale_return` in `backend/app/crud.py`:

```python
def _return_unit_line(
    *,
    session: Session,
    ret: SaleReturn,
    sale_line: SaleLine,
    quantity: int,
    actor_user_id: uuid.UUID,
    fallback_location_id: uuid.UUID,
) -> Decimal:
    """Walk a sold unit back to stock and return the cost restored.

    The unit goes back to wherever it stood before the sale (the SOLD movement's
    from_location_id), not to a generic bin, so its location history reads as a
    clean round trip.
    """
    if quantity != 1:
        raise HTTPException(
            status_code=422, detail="UNIT line return quantity must be 1"
        )
    assert sale_line.unit_id is not None  # ck_saleline_unit_requires_unit_id
    unit = session.exec(
        select(Unit).where(Unit.id == sale_line.unit_id).with_for_update()
    ).first()
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    try:
        new_state = assert_unit_transition(unit.current_state, MovementType.RETURNED)
    except IllegalTransition:
        raise HTTPException(
            status_code=409,
            detail=f"Unit cannot be returned from {unit.current_state.value}",
        )

    sold = session.exec(
        select(UnitMovement)
        .where(
            UnitMovement.unit_id == unit.id,
            UnitMovement.sale_id == sale_line.sale_id,
            UnitMovement.event_type == MovementType.SOLD,
        )
        .order_by(col(UnitMovement.occurred_at).desc())
    ).first()
    back_to = (
        sold.from_location_id
        if sold is not None and sold.from_location_id is not None
        else fallback_location_id
    )

    session.add(
        UnitMovement(
            unit_id=unit.id,
            event_type=MovementType.RETURNED,
            from_location_id=unit.current_location_id,
            to_location_id=back_to,
            sale_id=sale_line.sale_id,
            actor_user_id=actor_user_id,
            idempotency_key=uuid.uuid5(ret.idempotency_key, f"unit:{sale_line.id}"),
        )
    )
    unit.current_state = new_state
    unit.current_location_id = back_to
    unit.updated_at = get_datetime_utc()
    session.add(unit)
    return unit.purchase_cost_thb
```

Replace the stub in `create_sale_return`:

```python
        if sl.line_kind == SaleLineKind.UNIT:
            cogs = _return_unit_line(
                session=session,
                ret=ret,
                sale_line=sl,
                quantity=line.quantity,
                actor_user_id=created_by_user_id,
                fallback_location_id=ygn.id,
            )
        else:
            cogs = _return_part_line(
                session=session,
                ret=ret,
                sale_line=sl,
                already_returned=already,
                quantity=line.quantity,
                actor_user_id=created_by_user_id,
                from_location_id=customer_loc.id,
                to_location_id=ygn.id,
            )
```

- [ ] **Step 4: Run the whole return suite**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_sale_returns.py -q
```

Expected: PASS (all PART + UNIT tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_sale_returns.py
git commit -m "feat(returns): SOLD -> IN_STOCK path for serialized units"
```

---

### Task 4: `POST /sales/{sale_id}/returns` endpoint

**Files:**
- Modify: `backend/app/api/routes/sales.py`
- Modify: `backend/tests/api/routes/test_sale_returns.py`

**Interfaces:**
- Consumes: `crud.create_sale_return` (Tasks 2–3); `AdminUser` from `app.api.deps`.
- Produces: `POST /api/v1/sales/{sale_id}/returns` returning `SaleReturnPublic`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/routes/test_sale_returns.py`. Add `from fastapi.testclient import TestClient` and `PREFIX = settings.API_V1_STR` to the module's existing import block at the top — not mid-file.

```python
# --- HTTP surface -------------------------------------------------------------


def test_admin_can_post_a_return(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=2, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=2, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "faulty on arrival",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 2}],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["sale_id"] == str(sale.id)
    assert body["total_refund_thb"] == "200.00"
    assert body["total_cogs_restored_thb"] == "20.00"
    assert len(body["lines"]) == 1


def test_staff_cannot_post_a_return(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=1, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=1, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=normal_user_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "nope",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 1}],
        },
    )
    assert r.status_code == 403


def test_missing_reason_is_422(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=1, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=1, customer_id=_customer(db))

    r = client.post(
        f"{PREFIX}/sales/{sale.id}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "",
            "lines": [{"sale_line_id": str(_line_of(db, sale).id), "quantity": 1}],
        },
    )
    assert r.status_code == 422


def test_unknown_sale_is_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/sales/{uuid.uuid4()}/returns",
        headers=superuser_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "reason": "x",
            "lines": [{"sale_line_id": str(uuid.uuid4()), "quantity": 1}],
        },
    )
    assert r.status_code == 404
```

> Move the `from fastapi.testclient import TestClient` import up to the module's import block rather than leaving it mid-file; the `# noqa` above is only to keep this snippet self-contained.

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_sale_returns.py -q -k "post or staff or 404 or reason"
```

Expected: FAIL with 405/404 (route does not exist).

- [ ] **Step 3: Add the route**

In `backend/app/api/routes/sales.py`, extend the imports and append:

```python
from app.api.deps import AdminUser, CurrentUser, SessionDep, get_current_user, is_admin
from app.models import (
    ...,
    SaleReturn,
    SaleReturnCreateRequest,
    SaleReturnLine,
    SaleReturnLinePublic,
    SaleReturnPublic,
)


def _return_to_public(*, session: SessionDep, ret: SaleReturn) -> SaleReturnPublic:
    lines = session.exec(
        select(SaleReturnLine).where(SaleReturnLine.sale_return_id == ret.id)
    ).all()
    return SaleReturnPublic(
        id=ret.id,
        sale_id=ret.sale_id,
        reason=ret.reason,
        returned_at=ret.returned_at,
        total_refund_thb=ret.total_refund_thb,
        total_cogs_restored_thb=ret.total_cogs_restored_thb,
        created_by_user_id=ret.created_by_user_id,
        lines=[SaleReturnLinePublic.model_validate(line) for line in lines],
    )


@router.post("/{sale_id}/returns", response_model=SaleReturnPublic)
def create_sale_return(
    *,
    session: SessionDep,
    admin: AdminUser,
    sale_id: uuid.UUID,
    payload: SaleReturnCreateRequest,
) -> SaleReturnPublic:
    """Record a customer return against a sale (admin-only, design 2026-07-25).

    Restores stock at the original FIFO cost and reverses the sale's margin
    contribution in the RETURN month. Refund is fixed at the original line price.
    """
    ret = crud.create_sale_return(
        session=session,
        sale_id=sale_id,
        payload=payload,
        created_by_user_id=admin.id,
    )
    return _return_to_public(session=session, ret=ret)
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2, then the whole file. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sales.py backend/tests/api/routes/test_sale_returns.py
git commit -m "feat(returns): admin-only POST /sales/{id}/returns"
```

---

### Task 5: `GET /sales/returnable` lookup endpoint

Feeds the UI: resolve a scanned unit barcode to its sale, or list recent sales containing a SKU, each with per-line returnable counts.

**Files:**
- Modify: `backend/app/crud.py` (append after `create_sale_return`)
- Modify: `backend/app/api/routes/sales.py`
- Create: `backend/tests/api/routes/test_returnable_lookup.py`

**Interfaces:**
- Consumes: `ReturnableLinePublic`, `ReturnableSalePublic`, `ReturnableSalesPublic` (Task 1); `_returned_so_far` (Task 2).
- Produces: `crud.list_returnable_sales(*, session, castranova_barcode=None, sku=None, limit=20) -> ReturnableSalesPublic`; `GET /api/v1/sales/returnable?castranova_barcode=…` / `?sku=…`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/routes/test_returnable_lookup.py`. Reuse the helper style from `test_sale_returns.py` (copy the small `_seed` / `_part_product` / `_receive` / `_sell_parts` helpers — they are 5-line fixtures, not worth a shared module).

```python
"""GET /sales/returnable — the sale picker's data source."""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import SaleLine

PREFIX = settings.API_V1_STR

# ... copy _user_id / _seed / _rand / _customer / _part_product / _receive /
# _sell_parts / _serialized_unit / _sell_unit / _line_of / _return from
# test_sale_returns.py (5-line fixtures — not worth a shared module)


def test_barcode_resolves_a_sold_unit_to_its_sale(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": barcode},
    )

    assert r.status_code == 200
    sales = r.json()["sales"]
    assert len(sales) == 1
    assert sales[0]["sale_id"] == str(sale.id)
    line = sales[0]["lines"][0]
    assert line["quantity_sold"] == 1
    assert line["quantity_returned"] == 0
    assert line["quantity_returnable"] == 1


def test_a_fully_returned_unit_disappears_from_the_lookup(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))
    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": barcode},
    )
    assert r.json()["sales"] == []


def test_sku_lists_recent_sales_with_partial_returnable_counts(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=10, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"sku": sku},
    )

    line = r.json()["sales"][0]["lines"][0]
    assert line["quantity_sold"] == 5
    assert line["quantity_returned"] == 2
    assert line["quantity_returnable"] == 3
    assert line["unit_price_thb"] == "100.00"


def test_lookup_requires_exactly_one_selector(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(
            f"{PREFIX}/sales/returnable", headers=superuser_token_headers
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{PREFIX}/sales/returnable",
            headers=superuser_token_headers,
            params={"sku": "A", "castranova_barcode": "B"},
        ).status_code
        == 422
    )


def test_staff_cannot_use_the_lookup(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=normal_user_token_headers,
        params={"sku": "anything"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_returnable_lookup.py -q
```

Expected: FAIL (404 — no route).

- [ ] **Step 3: Implement the crud lookup**

Append to `backend/app/crud.py` after `create_sale_return`:

```python
_RETURNABLE_SALE_LIMIT = 20  # bounded, most-recent-first (hardening spec §7)


def list_returnable_sales(
    *,
    session: Session,
    castranova_barcode: str | None = None,
    sku: str | None = None,
    limit: int = _RETURNABLE_SALE_LIMIT,
) -> ReturnableSalesPublic:
    """Recent sales holding still-returnable lines for one unit or one SKU.

    Fully-returned lines are omitted, so an empty result means "nothing here can
    be returned" — which is exactly what the UI needs to decide between offering
    a return and offering a write-off.
    """
    if (castranova_barcode is None) == (sku is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of castranova_barcode or sku",
        )

    stmt = (
        select(SaleLine, Sale)
        .join(Sale, col(SaleLine.sale_id) == col(Sale.id))
        .order_by(col(Sale.sold_at).desc(), col(Sale.id))
    )
    if castranova_barcode is not None:
        stmt = stmt.join(Unit, col(SaleLine.unit_id) == col(Unit.id)).where(
            Unit.castranova_barcode == castranova_barcode
        )
    else:
        product = session.exec(select(Product).where(Product.sku == sku)).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        stmt = stmt.where(SaleLine.product_id == product.id)

    # Over-fetch: fully-returned lines are filtered out below, so the raw row
    # count is an upper bound on the sales we can actually offer.
    rows = session.exec(stmt.limit(limit * 4)).all()

    # Batched label lookups. A UNIT line carries unit_id, not product_id, so the
    # product comes through Unit — same recovery the margin report does.
    unit_ids = [sl.unit_id for sl, _ in rows if sl.unit_id is not None]
    unit_product = {
        u.id: u.product_id
        for u in session.exec(
            select(Unit).where(col(Unit.id).in_(unit_ids))
        ).all()
    } if unit_ids else {}

    def _product_of(sale_line: SaleLine) -> uuid.UUID | None:
        if sale_line.product_id is not None:
            return sale_line.product_id
        if sale_line.unit_id is None:
            return None
        return unit_product.get(sale_line.unit_id)

    labels = _product_labels(
        session,
        [pid for pid in {_product_of(sl) for sl, _ in rows} if pid is not None],
    )
    customers = _customer_labels(session, [s.customer_id for _, s in rows])

    by_sale: dict[uuid.UUID, ReturnableSalePublic] = {}
    for sale_line, sale in rows:
        returned = _returned_so_far(session=session, sale_line_id=sale_line.id)
        returnable = sale_line.quantity - returned
        if returnable <= 0:
            continue
        pid = _product_of(sale_line)
        entry = by_sale.get(sale.id)
        if entry is None:
            if len(by_sale) >= limit:
                continue
            entry = ReturnableSalePublic(
                sale_id=sale.id,
                sold_at=sale.sold_at,
                customer_id=sale.customer_id,
                customer_name=customers.get(sale.customer_id, ""),
                lines=[],
            )
            by_sale[sale.id] = entry
        entry.lines.append(
            ReturnableLinePublic(
                sale_line_id=sale_line.id,
                line_kind=sale_line.line_kind,
                product_id=pid,
                unit_id=sale_line.unit_id,
                label=labels.get(pid, "") if pid else "",
                quantity_sold=sale_line.quantity,
                quantity_returned=returned,
                quantity_returnable=returnable,
                unit_price_thb=sale_line.unit_price_thb,
            )
        )
    return ReturnableSalesPublic(sales=list(by_sale.values()))
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes/sales.py`, **above** the `/{sale_id}/receipt.pdf` route (literal paths must be declared before the `{sale_id}` parameterized ones, or `returnable` is parsed as a sale id):

```python
@router.get("/returnable", response_model=ReturnableSalesPublic)
def read_returnable_sales(
    *,
    session: SessionDep,
    admin: AdminUser,
    castranova_barcode: str | None = None,
    sku: str | None = None,
) -> ReturnableSalesPublic:
    """Recent sales with still-returnable lines for one unit or one SKU.
    Admin-only — it feeds the return flow and exposes line prices."""
    return crud.list_returnable_sales(
        session=session, castranova_barcode=castranova_barcode, sku=sku
    )
```

Import `ReturnableSalesPublic` from `app.models`.

- [ ] **Step 5: Run the tests to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/app/api/routes/sales.py \
  backend/tests/api/routes/test_returnable_lookup.py
git commit -m "feat(returns): GET /sales/returnable lookup for the return UI"
```

---

### Task 6: Margin report — `SALE_RETURN` channel row and exports

**Files:**
- Modify: `backend/app/crud.py:3525-3609` (`_channel_rows`), plus a new `_sale_return_totals` helper
- Modify: `backend/tests/api/routes/test_margin_report.py`
- Modify: `backend/tests/api/routes/test_report_exports.py`

**Interfaces:**
- Consumes: `SaleReturn` (Task 1), `crud.create_sale_return` (Tasks 2–3), `_month_window`, `_q`.
- Produces: `_sale_return_totals(session, start, end) -> tuple[Decimal, Decimal]`; a `MarginBreakdownRow` with `key="SALE_RETURN"`, `label="SALE RETURNS"` in the channel grouping.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/api/routes/test_margin_report.py`. This module already imports the `seed` fixture and `_pin_sale` from `test_reports.py` — reuse them. `seed["make_part"](retail, repair, [(qty, cost), ...])` creates a QUANTITY product with batches; `_pin_sale` rewrites `Sale.sold_at` so a test owns a dedicated month (the isolation convention this file already uses, since `db` is session-scoped and shared).

```python
# --- Sale returns (design 2026-07-25) ----------------------------------------

# Dedicated months so concurrently-seeded tests in the shared session db cannot
# collide, matching test_reports.test_short_pull_counted's convention.
_RET_M1 = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)   # sale + return
_RET_M2 = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)   # return-only month
_RET_M3 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)   # reconciliation
_RET_M4 = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)   # serialized return


def _pin_return(db: Session, sale_return_id: uuid.UUID, when: datetime) -> None:
    """Rewrite returned_at so a test owns a month. salereturn is not a ledger
    table, so a plain UPDATE is allowed (unlike part_movement)."""
    from app.models import SaleReturn

    row = db.get(SaleReturn, sale_return_id)
    assert row is not None
    row.returned_at = when
    db.add(row)
    db.commit()


def _sell_and_return_part(
    db: Session,
    seed: dict[str, Any],  # noqa: F811
    *,
    sold_when: datetime,
    returned_when: datetime,
    sell_qty: int = 2,
    return_qty: int = 1,
) -> Any:
    """Sell `sell_qty` of a fresh part (retail 100, single batch @ cost 10) and
    return `return_qty` of it. Returns the part product so callers can find its
    row. Hand-checkable: revenue 100/unit, COGS 10/unit."""
    from app.models import SaleLine, SaleReturnCreateRequest, SaleReturnLineInput

    admin, customer = seed["admin"], seed["customer"]
    part = seed["make_part"]("100.00", "20.00", [(10, "10.00")])
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.PART, sku=part.sku, quantity=sell_qty
            )
        ],
    )
    _pin_sale(db, sale.id, sold_when)
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).one()
    ret = crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="customer returned it",
            lines=[
                SaleReturnLineInput(sale_line_id=line.id, quantity=return_qty)
            ],
        ),
        created_by_user_id=admin.id,
    )
    _pin_return(db, ret.id, returned_when)
    return part


def test_channel_view_shows_a_negative_sale_return_row(db: Session, seed) -> None:  # noqa: F811
    """Sell 2 @ 100 (cost 10 each), return 1: a separate SALE RETURNS row with
    negative revenue and COGS. The SALE row itself is untouched; totals net."""
    _sell_and_return_part(
        db, seed, sold_when=_RET_M1, returned_when=_RET_M1
    )

    report = crud.margin_report(session=db, year=2026, month=5)
    rows = {r.key: r for r in report.rows}

    assert rows["SALE"].revenue_thb == Decimal("200.00")
    assert rows["SALE"].cogs_thb == Decimal("20.00")
    assert rows["SALE_RETURN"].label == "SALE RETURNS"
    assert rows["SALE_RETURN"].revenue_thb == Decimal("-100.00")
    assert rows["SALE_RETURN"].cogs_thb == Decimal("-10.00")
    assert rows["SALE_RETURN"].margin_thb == Decimal("-90.00")
    assert report.total_revenue_thb == Decimal("100.00")
    assert report.total_cogs_thb == Decimal("10.00")
    assert report.total_margin_thb == Decimal("90.00")


def test_no_sale_return_row_when_no_returns_that_month(db: Session, seed) -> None:  # noqa: ARG001, F811
    report = crud.margin_report(session=db, year=2099, month=2)
    assert all(r.key != "SALE_RETURN" for r in report.rows)
    # And the three fixed channel rows are still exactly what they were.
    assert [r.key for r in report.rows] == ["SALE", "MAINTENANCE", "PROJECT"]


def test_a_return_only_moves_the_return_month(db: Session, seed) -> None:  # noqa: F811
    """A sale in May returned in June leaves May's report identical forever."""
    _sell_and_return_part(db, seed, sold_when=_RET_M2, returned_when=_RET_M3)

    may = crud.margin_report(session=db, year=2026, month=6)
    assert all(r.key != "SALE_RETURN" for r in may.rows)
    assert may.total_revenue_thb == Decimal("200.00")  # untouched by the return

    june = crud.margin_report(session=db, year=2026, month=7)
    rows = {r.key: r for r in june.rows}
    assert rows["SALE_RETURN"].revenue_thb == Decimal("-100.00")
    assert rows["SALE"].revenue_thb == Decimal("0.00")


def test_maintenance_channel_filter_excludes_returns(db: Session, seed) -> None:  # noqa: F811
    _sell_and_return_part(db, seed, sold_when=_RET_M1, returned_when=_RET_M1)
    report = crud.margin_report(
        session=db, year=2026, month=5, channel=Channel.MAINTENANCE
    )
    assert all(r.key != "SALE_RETURN" for r in report.rows)


def test_sale_channel_filter_includes_returns(db: Session, seed) -> None:  # noqa: F811
    """Returns are an event ON the SALE channel, so scoping to SALE keeps them
    — otherwise the filtered view would not reconcile with the unfiltered one."""
    _sell_and_return_part(db, seed, sold_when=_RET_M1, returned_when=_RET_M1)
    report = crud.margin_report(
        session=db, year=2026, month=5, channel=Channel.SALE
    )
    assert [r.key for r in report.rows] == ["SALE", "SALE_RETURN"]
```

The dates in `_RET_M1`.. must not collide with months other tests in this module already claim — grep for `datetime(2026` in the file first and pick free months if any clash.

And in `backend/tests/api/routes/test_report_exports.py`, one test that the channel-grouping export carries the row. Read the module first and reuse its existing response-inspection helper; if it only inspects PDFs, assert on the PDF variant.

```python
def test_channel_margin_export_includes_the_sale_return_row(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, seed
) -> None:
    """Exports render row.label, so the new row rides along with no export-code
    change. This test locks that in."""
    # Seed a sale + a return in the export month using the same helper shape as
    # test_margin_report._sell_and_return_part.
    r = client.get(
        f"{PREFIX}/reports/channel-margin.xlsx",
        headers=superuser_token_headers,
        params={"month": "2026-05", "group_by": "channel"},
    )
    assert r.status_code == 200
    assert "SALE RETURNS" in _sheet_text(r.content)
```

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_margin_report.py tests/api/routes/test_report_exports.py -q -k return
```

Expected: FAIL — `KeyError: 'SALE_RETURN'`.

- [ ] **Step 3: Implement**

In `backend/app/crud.py`, add above `_channel_rows`:

```python
# Synthetic channel-row key for returns. Deliberately NOT a Channel enum member:
# Channel drives the report's channel FILTER, and "returns" is an event on the
# SALE channel, not a fourth channel to slice by.
_SALE_RETURN_KEY = "SALE_RETURN"
_SALE_RETURN_LABEL = "SALE RETURNS"


def _sale_return_totals(
    session: Session, start: datetime, end: datetime
) -> tuple[Decimal, Decimal]:
    """(refund, cogs_restored) for returns RECORDED in the window. Keyed on
    returned_at, never sold_at — that is what keeps past months immutable."""
    refund, cogs = session.exec(
        select(
            func.coalesce(func.sum(SaleReturn.total_refund_thb), Decimal("0")),
            func.coalesce(
                func.sum(SaleReturn.total_cogs_restored_thb), Decimal("0")
            ),
        ).where(
            col(SaleReturn.returned_at) >= start, col(SaleReturn.returned_at) < end
        )
    ).one()
    return refund, cogs
```

At the end of `_channel_rows`, replace the bare `return [...]` with:

```python
    rows = [
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
    # Returns are an event on the SALE channel, so they appear whenever SALE
    # does. Omitted entirely in a month with no returns — unlike the three
    # channels, a zero row here is noise, not parity.
    if channel in (None, Channel.SALE):
        refund, restored = _sale_return_totals(session, start, end)
        if refund or restored:
            rows.append(
                MarginBreakdownRow(
                    key=_SALE_RETURN_KEY,
                    label=_SALE_RETURN_LABEL,
                    revenue_thb=_q(-refund),
                    cogs_thb=_q(-restored),
                    margin_thb=_q(-refund) - _q(-restored),
                )
            )
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2, then the full `test_margin_report.py` and `test_report_exports.py`. Expected: PASS with no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_margin_report.py \
  backend/tests/api/routes/test_report_exports.py
git commit -m "feat(reports): SALE RETURNS row in the channel margin view"
```

---

### Task 7: Margin report — product and customer netting

**Files:**
- Modify: `backend/app/crud.py:3620-3756` (`_product_rows`) and `:3768-3860` (`_customer_rows`)
- Modify: `backend/tests/api/routes/test_margin_report.py`

**Interfaces:**
- Consumes: `SaleReturn`, `SaleReturnLine` (Task 1); `_merge` (crud.py:3612); the `_sell_and_return_part` test helper from Task 6. Deliberately *not* `_sale_return_totals` — that aggregates across all sales, while these groupings need per-product / per-customer sums.
- Produces: returns netted into the matching product/customer row for the return month. No new public names.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/api/routes/test_margin_report.py`:

```python
def test_returns_net_into_the_product_row(db: Session, seed) -> None:  # noqa: F811
    """Sell 2 @ 100 (cost 10), return 1: the product's row reads 100 revenue /
    10 COGS. One netted row — no separate returns row at this grain."""
    part = _sell_and_return_part(
        db, seed, sold_when=_RET_M3, returned_when=_RET_M3
    )

    report = crud.margin_report(
        session=db, year=2026, month=7, group_by=MarginDimension.PRODUCT
    )
    row = next(r for r in report.rows if r.key == str(part.id))
    assert row.revenue_thb == Decimal("100.00")
    assert row.cogs_thb == Decimal("10.00")
    assert row.margin_thb == Decimal("90.00")
    assert all(r.key != "SALE_RETURN" for r in report.rows)


def test_returns_net_into_the_customer_row(db: Session, seed) -> None:  # noqa: F811
    _sell_and_return_part(db, seed, sold_when=_RET_M3, returned_when=_RET_M3)

    report = crud.margin_report(
        session=db, year=2026, month=7, group_by=MarginDimension.CUSTOMER
    )
    row = next(r for r in report.rows if r.key == str(seed["customer"].id))
    assert row.revenue_thb == Decimal("100.00")
    assert row.cogs_thb == Decimal("10.00")


def test_all_groupings_reconcile_to_the_same_totals_with_returns(
    db: Session, seed  # noqa: F811
) -> None:
    """The report's core promise: for a fixed (month, channel) every grouping
    sums to the same revenue/COGS. Returns must not break it. The month is
    seeded with SALE activity only, like the file's other reconciliation tests."""
    _sell_and_return_part(db, seed, sold_when=_RET_M3, returned_when=_RET_M3)

    by_channel = crud.margin_report(session=db, year=2026, month=7)
    by_product = crud.margin_report(
        session=db, year=2026, month=7, group_by=MarginDimension.PRODUCT
    )
    by_customer = crud.margin_report(
        session=db, year=2026, month=7, group_by=MarginDimension.CUSTOMER
    )

    assert by_channel.total_revenue_thb == by_product.total_revenue_thb
    assert by_channel.total_revenue_thb == by_customer.total_revenue_thb
    assert by_channel.total_cogs_thb == by_product.total_cogs_thb
    assert by_channel.total_cogs_thb == by_customer.total_cogs_thb


def test_a_serialized_return_nets_into_its_product_row(db: Session, seed) -> None:  # noqa: F811
    """A UNIT sale line carries unit_id, NOT product_id — the netting query has
    to recover the product through Unit, exactly like the SALE revenue query
    above it. Without the outer join this row would be keyed on NULL."""
    from app.models import SaleLine, SaleReturnCreateRequest, SaleReturnLineInput

    admin, customer = seed["admin"], seed["customer"]
    barcode = seed["make_unit"]("300.00")  # serialized product, retail 500.00
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)
        ],
    )
    _pin_sale(db, sale.id, _RET_M4)
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).one()
    ret = crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="dead on arrival",
            lines=[SaleReturnLineInput(sale_line_id=line.id, quantity=1)],
        ),
        created_by_user_id=admin.id,
    )
    _pin_return(db, ret.id, _RET_M4)

    report = crud.margin_report(
        session=db, year=2026, month=8, group_by=MarginDimension.PRODUCT
    )
    row = next(r for r in report.rows if r.key == str(seed["serialized"].id))
    # Sold for 500 (cost 300) then fully returned: both sides cancel.
    assert row.revenue_thb == Decimal("0.00")
    assert row.cogs_thb == Decimal("0.00")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/api/routes/test_margin_report.py -q -k "net or reconcile"
```

Expected: FAIL — product/customer rows still show the gross sale.

- [ ] **Step 3: Implement product netting**

Inside `_product_rows`, at the end of the `if channel in (None, Channel.SALE):` block:

```python
        # Returns net into the product's row for the RETURN month (no separate
        # returns row at this grain). A UNIT line carries unit_id not product_id,
        # so the product is recovered through Unit — same COALESCE as above.
        pid_r = func.coalesce(SaleLine.product_id, Unit.product_id)
        for product_id, refund, restored in session.exec(
            select(
                pid_r,
                func.coalesce(
                    func.sum(
                        SaleReturnLine.quantity * SaleReturnLine.unit_price_thb
                    ),
                    Decimal("0"),
                ),
                func.coalesce(
                    func.sum(SaleReturnLine.cogs_restored_thb), Decimal("0")
                ),
            )
            .join(SaleLine, col(SaleReturnLine.sale_line_id) == col(SaleLine.id))
            .join(
                SaleReturn, col(SaleReturnLine.sale_return_id) == col(SaleReturn.id)
            )
            .join(Unit, col(SaleLine.unit_id) == col(Unit.id), isouter=True)
            .where(
                col(SaleReturn.returned_at) >= start,
                col(SaleReturn.returned_at) < end,
            )
            .group_by(pid_r)
        ).all():
            _merge(acc, product_id, -refund, -restored)
```

- [ ] **Step 4: Implement customer netting**

Inside `_customer_rows`, at the end of the `if channel in (None, Channel.SALE):` block:

```python
        # Returns net into the customer's row for the RETURN month. Uses the
        # SaleReturn header totals (exact, and identical to the sum of its lines
        # used by the PRODUCT grouping — so the two groupings reconcile).
        for cust_id, refund, restored in session.exec(
            select(
                Sale.customer_id,
                func.coalesce(func.sum(SaleReturn.total_refund_thb), Decimal("0")),
                func.coalesce(
                    func.sum(SaleReturn.total_cogs_restored_thb), Decimal("0")
                ),
            )
            .join(Sale, col(SaleReturn.sale_id) == col(Sale.id))
            .where(
                col(SaleReturn.returned_at) >= start,
                col(SaleReturn.returned_at) < end,
            )
            .group_by(col(Sale.customer_id))
        ).all():
            _merge(acc, cust_id, -refund, -restored)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run the whole `test_margin_report.py`. Expected: PASS, including the pre-existing reconciliation tests.

- [ ] **Step 6: Run the full backend suite**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/ -q
```

Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_margin_report.py
git commit -m "feat(reports): net returns into product and customer margin rows"
```

---

### Task 8: Concurrency — a return and a sale on the same product must not deadlock or corrupt stock

Mandatory before any PR touching consumption (CLAUDE.md §5). This is the test that justifies the `(received_at, id)` lock-order correction.

**Files:**
- Create: `backend/tests/crud/test_return_concurrency.py`

**Interfaces:**
- Consumes: `crud.create_sale_return`, `crud.create_sale`, `crud.consume_quantity_fifo`.
- Produces: nothing — a regression guard.

- [ ] **Step 1: Write the test**

This mirrors `backend/tests/crud/test_fifo_concurrency.py` exactly: `ThreadPoolExecutor`, one `Session(engine)` per worker against the real Postgres test DB (row locks are the thing under test), and the `"ok"` / `"conflict"` / `"error:<repr>"` result protocol so a deadlock surfaces as a failed assertion rather than a hang.

`backend/tests/crud/test_return_concurrency.py`:

```python
"""Returns racing sales on the same product (plan Task 8).

Both paths take PartBatch row locks. consume_quantity_fifo locks in
(received_at, id) order (crud.py:1166); _return_part_line MUST use the same
order or the two can deadlock. A divergence shows up here as an "error:" result
(DeadlockDetected), never a silent pass.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    CustomerCreate,
    Location,
    PartBatch,
    Product,
    ProductCreate,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SaleReturnCreateRequest,
    SaleReturnLineInput,
    SupplierCreate,
    TrackingMode,
)

# Two batches, 20 units. Four seed sales of 3 consume 12 across the batch
# boundary (b1 8 -> 0, b2 12 -> 8), so the returns below have to credit BOTH
# batches while the concurrent sales are draining them.
SEED_SALES = 4
SALE_QTY = 3
RECEIVED_TOTAL = 20
SEEDED_CONSUMED = SEED_SALES * SALE_QTY  # 12


@pytest.fixture
def sold_product(db: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]]:
    """A QUANTITY product with two batches and SEED_SALES committed sales.
    Yields (product_id, customer_id, actor_user_id, [sale_id...])."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RET-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    for qty, cost in ((8, "10.00"), (12, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=user.id,
        )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Conc Returns")
    )
    sale_ids = [
        crud.create_sale(
            session=db,
            customer_id=customer.id,
            created_by_user_id=user.id,
            idempotency_key=uuid.uuid4(),
            lines=[
                SaleLineInput(
                    line_kind=SaleLineKind.PART,
                    sku=product.sku,
                    quantity=SALE_QTY,
                )
            ],
        ).id
        for _ in range(SEED_SALES)
    ]
    db.commit()  # visible to the worker sessions (separate connections)
    yield product.id, customer.id, user.id, sale_ids


def _line_id(db: Session, sale_id: uuid.UUID) -> uuid.UUID:
    return db.exec(select(SaleLine).where(SaleLine.sale_id == sale_id)).one().id


def _return_once(
    sale_id: uuid.UUID, sale_line_id: uuid.UUID, qty: int, actor_user_id: uuid.UUID
) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale_return(
                session=session,
                sale_id=sale_id,
                payload=SaleReturnCreateRequest(
                    idempotency_key=uuid.uuid4(),
                    reason="concurrent return",
                    lines=[
                        SaleReturnLineInput(sale_line_id=sale_line_id, quantity=qty)
                    ],
                ),
                created_by_user_id=actor_user_id,
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:  # deadlock / 500 / anything unexpected
            session.rollback()
            return f"error:{exc!r}"


def _sell_once(customer_id: uuid.UUID, sku: str, actor_user_id: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale(
                session=session,
                customer_id=customer_id,
                created_by_user_id=actor_user_id,
                idempotency_key=uuid.uuid4(),
                lines=[
                    SaleLineInput(
                        line_kind=SaleLineKind.PART, sku=sku, quantity=SALE_QTY
                    )
                ],
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:
            session.rollback()
            return f"error:{exc!r}"


def test_concurrent_returns_and_sales_neither_deadlock_nor_corrupt_stock(
    db: Session,
    sold_product: tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]],
) -> None:
    product_id, customer_id, actor_user_id, sale_ids = sold_product
    product = db.get(Product, product_id)
    assert product is not None
    line_ids = [_line_id(db, sid) for sid in sale_ids]

    # SEED_SALES returns (each on its own sale line, so all should win) racing
    # SEED_SALES fresh sales on the same two batches.
    jobs = [
        (lambda sid=sid, lid=lid: _return_once(sid, lid, SALE_QTY, actor_user_id))
        for sid, lid in zip(sale_ids, line_ids, strict=True)
    ] + [
        (lambda: _sell_once(customer_id, product.sku, actor_user_id))
        for _ in range(SEED_SALES)
    ]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda job: job(), jobs))

    return_results, sale_results = results[:SEED_SALES], results[SEED_SALES:]

    # No deadlock, no 500, from either side.
    errors = [r for r in results if r.startswith("error:")]
    assert not errors, errors
    # Every return targets a distinct line with nothing returned yet — all win.
    assert return_results == ["ok"] * SEED_SALES
    # Sales either win or take a clean 409; never anything else.
    assert all(r in ("ok", "conflict") for r in sale_results)

    db.expire_all()
    batches = db.exec(
        select(PartBatch).where(PartBatch.product_id == product_id)
    ).all()
    # Bounds hold on every batch (the ck_part_batch_qty_bounds invariant).
    assert all(0 <= b.remaining_qty <= b.received_qty for b in batches)
    # Stock is conserved exactly: received - consumed + restored.
    restored = SEED_SALES * SALE_QTY
    consumed = SEEDED_CONSUMED + sale_results.count("ok") * SALE_QTY
    assert sum(b.remaining_qty for b in batches) == (
        RECEIVED_TOTAL - consumed + restored
    )


def test_two_concurrent_returns_of_the_same_line_cannot_over_return(
    db: Session,
    sold_product: tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]],
) -> None:
    """The FOR UPDATE lock on the sale line is the ONLY serialization point for
    two returns of the same line — SaleReturnLine rows do not exist yet, so
    locking those would lock nothing. Exactly one thread may win."""
    product_id, _customer_id, actor_user_id, sale_ids = sold_product
    sale_id = sale_ids[0]
    line_id = _line_id(db, sale_id)

    before = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product_id)
        ).all()
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _return_once(sale_id, line_id, SALE_QTY, actor_user_id),
                range(2),
            )
        )

    assert not [r for r in results if r.startswith("error:")], results
    assert results.count("ok") == 1
    assert results.count("conflict") == 1

    db.expire_all()
    after = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product_id)
        ).all()
    )
    assert after - before == SALE_QTY  # restocked once, not twice
```

- [ ] **Step 2: Run it**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/crud/test_return_concurrency.py -q
```

Expected: PASS. If it deadlocks, the lock ordering in `_return_part_line` diverged from `consume_quantity_fifo` — fix the ordering, not the test.

- [ ] **Step 4: Re-run the pre-existing FIFO concurrency test (plan Task 2.3), which is mandatory for consumption changes**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/crud/ -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/crud/test_return_concurrency.py
git commit -m "test(returns): concurrent return + sale keep FIFO stock consistent"
```

---

### Task 9: Regenerate the SDK and add the frontend pure logic

**Files:**
- Modify (generated): `frontend/src/client/schemas.gen.ts`, `sdk.gen.ts`, `types.gen.ts`
- Create: `frontend/src/lib/sale-return.ts`
- Create: `frontend/src/lib/sale-return.test.ts`

**Interfaces:**
- Consumes: the endpoints from Tasks 4–5, via the generated `SalesService`.
- Produces: `ReturnDraft`, `emptyReturnDraft`, `canSubmitReturn(d, maxQuantity)`, `buildReturnPayload(d, idempotencyKey)`, and the generated `SalesService.createSaleReturn` / `SalesService.readReturnableSales`.

- [ ] **Step 1: Regenerate the SDK from the live backend**

Restart the dev backend so the new routes are served, dump the schema, and regenerate outside the frontend container:

```bash
docker compose restart backend
curl -s http://localhost:8000/api/v1/openapi.json > frontend/openapi.json   # adjust host/port to your stack
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend \
  frontend:latest bunx run generate-client
git diff --stat frontend/src/client
```

Expected: `types.gen.ts` / `sdk.gen.ts` / `schemas.gen.ts` gain `SaleReturnCreateRequest`, `SaleReturnPublic`, `ReturnableSalesPublic`, `createSaleReturn`, `readReturnableSales`. Restore `core/*` and `index.ts` if they show only line-ending churn.

- [ ] **Step 2: Write the failing vitest**

`frontend/src/lib/sale-return.test.ts`:

```typescript
import { describe, expect, it } from "vitest"

import {
  buildReturnPayload,
  canSubmitReturn,
  emptyReturnDraft,
  type ReturnDraft,
} from "./sale-return"

const KEY = "11111111-1111-1111-1111-111111111111"

function draft(over: Partial<ReturnDraft>): ReturnDraft {
  return { ...emptyReturnDraft, ...over }
}

describe("sale return form logic", () => {
  it("requires a sale line, a reason, and a quantity", () => {
    expect(canSubmitReturn(draft({ saleLineId: "", reason: "x", quantity: "1" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "", quantity: "1" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "1" }), 5)).toBe(true)
  })

  it("caps the quantity at what is still returnable", () => {
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "5" }), 5)).toBe(true)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "6" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "0" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "-1" }), 5)).toBe(false)
  })

  it("rejects non-integer quantities", () => {
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "1.5" }), 5)).toBe(false)
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "abc" }), 5)).toBe(false)
  })

  it("nothing is returnable when the cap is zero", () => {
    expect(canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "1" }), 0)).toBe(false)
  })

  it("builds a single-line payload with the trimmed reason", () => {
    expect(
      buildReturnPayload(
        draft({ saleId: "S", saleLineId: "L", quantity: "3", reason: "  faulty  " }),
        KEY,
      ),
    ).toEqual({
      idempotency_key: KEY,
      reason: "faulty",
      lines: [{ sale_line_id: "L", quantity: 3 }],
    })
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend \
  frontend:latest bun run test:unit
```

Expected: FAIL — cannot resolve `./sale-return`.

- [ ] **Step 4: Implement**

`frontend/src/lib/sale-return.ts`:

```typescript
import type { SaleReturnCreateRequest } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for recording a sale return from the Stock Adjustment screen
// (design 2026-07-25). Mirrors the backend guards so the UI never POSTs a body
// the server will reject:
//   - a sale line must be picked
//   - quantity is a positive integer, capped at what is still returnable
//   - a reason is required, like every stock adjustment
// The refund is NOT part of the draft: it is fixed at the original sale price
// and is display-only.
// ---------------------------------------------------------------------------

export interface ReturnDraft {
  saleId: string
  saleLineId: string
  /** Positive integer as typed; parsed at submit. */
  quantity: string
  reason: string
}

export const emptyReturnDraft: ReturnDraft = {
  saleId: "",
  saleLineId: "",
  quantity: "1",
  reason: "",
}

/** Parsed positive integer, or null if not a valid one. */
function parseQuantity(raw: string): number | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const n = Number.parseInt(trimmed, 10)
  return n > 0 ? n : null
}

export function canSubmitReturn(d: ReturnDraft, maxQuantity: number): boolean {
  if (d.saleLineId.trim() === "") return false
  if (d.reason.trim() === "") return false
  const qty = parseQuantity(d.quantity)
  if (qty === null) return false
  return qty <= maxQuantity
}

export function buildReturnPayload(
  d: ReturnDraft,
  idempotencyKey: string,
): SaleReturnCreateRequest {
  return {
    idempotency_key: idempotencyKey,
    reason: d.reason.trim(),
    lines: [
      {
        sale_line_id: d.saleLineId.trim(),
        quantity: parseQuantity(d.quantity) ?? 0,
      },
    ],
  }
}
```

- [ ] **Step 5: Run the tests + typecheck + lint**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest \
  bash -c "bun run test:unit && bunx tsc --noEmit && bunx biome check src/lib/sale-return.ts src/lib/sale-return.test.ts"
```

Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/client frontend/src/lib/sale-return.ts frontend/src/lib/sale-return.test.ts
git commit -m "feat(returns): regenerate SDK and add return form logic"
```

---

### Task 10: Stock-adjustment screen — "Return to stock" on the Serialized unit tab

**Files:**
- Modify: `frontend/src/routes/_layout/stock-adjustment.tsx`

**Interfaces:**
- Consumes: `SalesService.readReturnableSales`, `SalesService.createSaleReturn`, `canSubmitReturn`, `buildReturnPayload`, `emptyReturnDraft` (Task 9).
- Produces: on the UNIT tab, a scanned barcode that resolves to a still-returnable sale line renders a "Return to stock" panel instead of only the write-off action.

- [ ] **Step 1: Add the lookup query**

Inside the `StockAdjustment` component, after the existing `draft` state:

```tsx
const [returnDraft, setReturnDraft] = useState<ReturnDraft>(emptyReturnDraft)
const setReturn = (patch: Partial<ReturnDraft>) =>
  setReturnDraft((d) => ({ ...d, ...patch }))

// A scanned barcode that resolves to a still-returnable sale line means the
// unit is SOLD and can come back; an empty result means write-off is the only
// action. Debounce-free: ScanField fires once per scan/blur.
const barcode = draft.barcode.trim()
const returnableQuery = useQuery({
  queryKey: ["returnable-sales", "barcode", barcode],
  queryFn: () =>
    SalesService.readReturnableSales({ castranovaBarcode: barcode }),
  enabled: draft.targetKind === "UNIT" && barcode.length > 0,
})

const unitReturn = returnableQuery.data?.sales[0]
const unitReturnLine = unitReturn?.lines[0]
```

Import `useQuery` from `@tanstack/react-query`, `SalesService` from `@/client`, and the Task 9 helpers.

- [ ] **Step 2: Add the return mutation**

The mutation takes the draft as a variable rather than reading component state, so a click that both selects a line and submits cannot post a stale draft:

```tsx
const returnMutation = useMutation({
  mutationFn: (vars: { saleId: string; draft: ReturnDraft }) =>
    SalesService.createSaleReturn({
      saleId: vars.saleId,
      requestBody: buildReturnPayload(vars.draft, crypto.randomUUID()),
    }),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["stock-on-hand"] })
    queryClient.invalidateQueries({ queryKey: ["search-sku"] })
    queryClient.invalidateQueries({ queryKey: ["search-serial"] })
    queryClient.invalidateQueries({ queryKey: ["returnable-sales"] })
    showSuccessToast("Return recorded. The item is back in stock.")
    setReturnDraft(emptyReturnDraft)
    setDraft({ ...emptyAdjustmentDraft, targetKind: draft.targetKind })
  },
  onError: (err) => {
    const detail =
      err instanceof ApiError && err.body && typeof err.body === "object"
        ? (err.body as { detail?: string }).detail
        : undefined
    showErrorToast(detail ?? "Could not record the return.")
  },
})
```

- [ ] **Step 3: Render the panel on the UNIT tab**

Replace the UNIT branch's trailing hint paragraph with a conditional panel. Keep the write-off path exactly as it is when there is nothing returnable:

```tsx
{unitReturn && unitReturnLine ? (
  <div className="border-primary/30 bg-primary/5 space-y-3 rounded-lg border p-4">
    <p className="font-medium">This unit was sold — you can return it.</p>
    <p className="text-muted-foreground text-sm">
      {unitReturnLine.label} · sold {new Date(unitReturn.sold_at).toLocaleDateString()}{" "}
      to {unitReturn.customer_name}
    </p>
    <p className="text-sm">
      Refund: <span className="num">{unitReturnLine.unit_price_thb}</span> THB
      {" "}(the original sale price — it cannot be changed here)
    </p>
    <div className="space-y-2">
      <Label htmlFor={returnReasonId}>Reason for the return</Label>
      <Input
        id={returnReasonId}
        value={returnDraft.reason}
        maxLength={512}
        onChange={(e) => setReturn({ reason: e.target.value })}
        placeholder="Why is the customer returning this?"
      />
    </div>
    <Button
      type="button"
      disabled={
        !canSubmitReturn(unitPending, unitReturnLine.quantity_returnable) ||
        returnMutation.isPending
      }
      onClick={() =>
        returnMutation.mutate({
          saleId: unitReturn.sale_id,
          draft: unitPending,
        })
      }
    >
      {returnMutation.isPending ? "Returning…" : "Return to stock"}
    </Button>
  </div>
) : (
  <p className="text-muted-foreground text-sm">
    The unit moves to the terminal ADJUSTED_OUT state.
  </p>
)}
```

where `unitPending` is derived, not stored — the unit tab has nothing to choose, so only the reason is real state:

```tsx
const unitPending: ReturnDraft = {
  ...returnDraft,
  saleId: unitReturn?.sale_id ?? "",
  saleLineId: unitReturnLine?.sale_line_id ?? "",
  quantity: "1",
}
```

Also hide/disable the "Record adjustment" (write-off) button while a return is on offer, so the admin cannot write off a unit that is actually a return.

- [ ] **Step 4: Typecheck and lint**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest \
  bash -c "bunx tsc --noEmit && bunx biome check src/routes/_layout/stock-adjustment.tsx"
```

Expected: clean.

- [ ] **Step 5: Verify by hand against the running stack**

Sell a serialized unit, then scan its barcode on `/stock-adjustment` (Serialized unit tab). Expected: the return panel appears with the sale, the customer, and the fixed refund; recording it puts the unit back to `IN_STOCK` (confirm on `/search`).

> The :5173 surface serves committed branch code, not the working tree — commit before checking.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/_layout/stock-adjustment.tsx
git commit -m "feat(returns): return a sold unit to stock from the adjustment screen"
```

---

### Task 11: Stock-adjustment screen — "Return" action and sale picker on the Quantity tab

**Files:**
- Modify: `frontend/src/routes/_layout/stock-adjustment.tsx`

**Interfaces:**
- Consumes: everything from Task 10.
- Produces: on the QUANTITY tab, a third action ("Return") that lists recent sales of the SKU with per-line returnable counts and posts a single-line return.

- [ ] **Step 1: Add the action selector**

Above the SKU field on the QUANTITY branch, add a three-way action control (`Tabs` or a `Select`, matching the page's existing shadcn usage):

```tsx
const [qtyAction, setQtyAction] = useState<"ADJUST" | "RETURN">("ADJUST")
```

`ADJUST` keeps today's signed-delta form verbatim (Found = positive, Lost = negative). `RETURN` swaps in the picker below. Reset both drafts on switch, the same way the target-kind tabs already do.

- [ ] **Step 2: Add the SKU-scoped lookup**

```tsx
const sku = draft.sku.trim()
const returnableBySkuQuery = useQuery({
  queryKey: ["returnable-sales", "sku", sku],
  queryFn: () => SalesService.readReturnableSales({ sku }),
  enabled: draft.targetKind === "QUANTITY" && qtyAction === "RETURN" && sku.length > 0,
})
```

- [ ] **Step 3: Render the picker**

A `Select` of the returned sales, one option per sale/line:

```tsx
<Select
  value={returnDraft.saleLineId}
  onValueChange={(saleLineId) => {
    const hit = returnableBySkuQuery.data?.sales.find((s) =>
      s.lines.some((l) => l.sale_line_id === saleLineId),
    )
    setReturn({ saleLineId, saleId: hit?.sale_id ?? "", quantity: "1" })
  }}
>
  <SelectTrigger id={saleId}>
    <SelectValue placeholder="Pick the sale this is coming back from…" />
  </SelectTrigger>
  <SelectContent>
    {returnableBySkuQuery.data?.sales.flatMap((s) =>
      s.lines.map((l) => (
        <SelectItem key={l.sale_line_id} value={l.sale_line_id}>
          {new Date(s.sold_at).toLocaleDateString()} · {s.customer_name} ·{" "}
          {l.quantity_returnable} of {l.quantity_sold} returnable
        </SelectItem>
      )),
    )}
  </SelectContent>
</Select>
```

`list_returnable_sales` already omits fully-returned lines, so there is nothing to render disabled — an empty list means "nothing from this SKU can be returned", and the UI should say exactly that.

Then a quantity `Input` (capped, with a helper line showing the cap), the reason `Input`, and a "Record return" button:

```tsx
const selectedLine = returnableBySkuQuery.data?.sales
  .flatMap((s) => s.lines)
  .find((l) => l.sale_line_id === returnDraft.saleLineId)

<Button
  type="button"
  disabled={
    !selectedLine ||
    !canSubmitReturn(returnDraft, selectedLine.quantity_returnable) ||
    returnMutation.isPending
  }
  onClick={() =>
    returnMutation.mutate({ saleId: returnDraft.saleId, draft: returnDraft })
  }
>
  {returnMutation.isPending ? "Recording…" : "Record return"}
</Button>
```

Here the draft *is* the state (the admin picks the line and types the quantity), so passing `returnDraft` straight through is correct — no derived object needed, unlike the unit tab.

Show the computed refund (`quantity × selectedLine.unit_price_thb`) as read-only text, and when `returnableBySkuQuery.data?.sales` is empty say so plainly ("Nothing from this SKU can be returned") rather than rendering an empty picker.

- [ ] **Step 4: Typecheck and lint**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest \
  bash -c "bunx tsc --noEmit && bunx biome check src/routes/_layout/stock-adjustment.tsx"
```

Expected: clean.

- [ ] **Step 5: Verify by hand**

Sell 5 of a QUANTITY SKU, then on `/stock-adjustment` → Quantity SKU → Return: pick the sale, return 2. Expected: success toast; `/stock` shows on-hand up by 2; re-opening the picker shows "3 of 5 returnable".

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/_layout/stock-adjustment.tsx
git commit -m "feat(returns): quantity return with a sale picker"
```

---

### Task 12: Surface `RETURNED` in the audit log

Returns write real movements, so they already appear in the audit log — but the event-type filter cannot select them and the detail drawer falls back to a generic icon. Small, and the design's third stated goal is a complete audit trail.

**Files:**
- Modify: `frontend/src/lib/labels.ts`
- Modify: `frontend/src/routes/_layout/audit.tsx:53-59`
- Modify: `frontend/src/components/audit/AuditDetailSheet.tsx:37-44`
- Modify: `frontend/src/routes/_layout/search.tsx:31-42`

**Interfaces:**
- Consumes: the regenerated `MovementType` union (Task 9).
- Produces: no new exports — three map entries and one filter entry.

- [ ] **Step 1: Add the label**

In `frontend/src/lib/labels.ts`, in the movement-type switch (the one alongside `"ADJUSTED_OUT"`), add:

```typescript
    case "RETURNED":
      return "Returned by customer"
```

Add the matching case to `consumptionLabel` in `frontend/src/routes/_layout/search.tsx`:

```typescript
    case "RETURNED":
      return "Return"
```

- [ ] **Step 2: Add the audit filter option**

`frontend/src/routes/_layout/audit.tsx`:

```typescript
const EVENT_TYPES: MovementType[] = [
  "RECEIVED",
  "SOLD",
  "MAINTENANCE_OUT",
  "PROJECT_OUT",
  "ADJUSTED_OUT",
  "RETURNED",
]
```

- [ ] **Step 3: Add the icon + direction**

`frontend/src/components/audit/AuditDetailSheet.tsx` — a return is stock **in**:

```typescript
  RETURNED: { icon: Undo2, dir: "in" },
```

Import `Undo2` from `lucide-react` alongside the existing icons.

- [ ] **Step 4: Typecheck, lint, and run the label spec**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest \
  bash -c "bunx tsc --noEmit && bunx biome check src && bun run test:unit"
```

Expected: clean. `frontend/tests/labels.spec.ts` is a Playwright-run pure-logic spec — if it enumerates movement types, extend it with the `RETURNED` case.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/labels.ts frontend/src/routes/_layout/audit.tsx \
  frontend/src/routes/_layout/search.tsx frontend/src/components/audit/AuditDetailSheet.tsx
git commit -m "feat(returns): show RETURNED movements in audit and search"
```

---

### Task 13: Playwright E2E

**Files:**
- Create: `frontend/tests/sale-return.spec.ts`

**Interfaces:**
- Consumes: the whole stack.
- Produces: two browser journeys.

- [ ] **Step 1: Write the spec**

Model the Node-side seeding on `frontend/tests/sale.spec.ts` (SDK seeding as the superuser via `OpenAPI.TOKEN`, `rand()` suffixes to dodge shared-DB collisions, role-based selectors — never `getByLabel`, which collides with the TanStack Router devtools in dev mode).

```typescript
import { expect, test } from "@playwright/test"
// ... SDK imports mirroring sale.spec.ts

test("a sold unit can be returned to stock and sold again", async ({ page }) => {
  // Seed: SERIALIZED product + supplier + customer + received piece, then a sale
  // of that unit via SalesService (Node-side, as the superuser).
  // Then in the browser, as an admin:
  await page.goto("/stock-adjustment")
  await page.getByRole("tab", { name: "Serialized unit" }).click()
  await page.getByRole("textbox", { name: /barcode/i }).fill(barcode)
  await expect(page.getByText(/this unit was sold/i)).toBeVisible()
  await page.getByRole("textbox", { name: /reason for the return/i }).fill("faulty")
  await page.getByRole("button", { name: "Return to stock" }).click()
  await expect(page.getByText(/back in stock/i)).toBeVisible()

  // And it really is sellable again.
  await page.goto("/search")
  // ... assert the unit shows as In stock
})

test("a quantity sale line can be partially returned via the sale picker", async ({
  page,
}) => {
  // Seed: QUANTITY product + a received batch + a sale of 5.
  await page.goto("/stock-adjustment")
  await page.getByRole("tab", { name: "Quantity SKU" }).click()
  await page.getByRole("tab", { name: "Return" }).click()
  await page.getByRole("textbox", { name: /sku/i }).fill(sku)
  await page.getByRole("combobox", { name: /sale/i }).click()
  await page.getByRole("option", { name: /5 of 5 returnable/ }).click()
  await page.getByRole("textbox", { name: /quantity/i }).fill("2")
  await page.getByRole("textbox", { name: /reason/i }).fill("wrong part")
  await page.getByRole("button", { name: "Record return" }).click()
  await expect(page.getByText(/return recorded/i)).toBeVisible()
  // Re-open the picker: the line now reads 3 of 5 returnable.
})
```

- [ ] **Step 2: Run it against `app_test`, never the dev `app` DB**

Follow the E2E-on-`app_test` recipe: reseed `app_test` via a one-off prestart, start a throwaway `e2e-backend` on `POSTGRES_DB=app_test`, and run Playwright against it with `E2E_SKIP_DB_RESET=1`:

```bash
docker compose run --rm -e POSTGRES_DB=app_test prestart
# start a throwaway e2e-backend on the compose network with POSTGRES_DB=app_test, then:
docker run --rm --network castranova-pos_default \
  -e VITE_API_URL=http://e2e-backend:8000 -e E2E_SKIP_DB_RESET=1 -e CI=1 \
  -v "$PWD:/app" -v /app/node_modules -w /app/frontend \
  castranova-pos-playwright:latest bunx playwright test tests/sale-return.spec.ts
```

Expected: 2 passed. Tear the throwaway backend down afterwards.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/sale-return.spec.ts
git commit -m "test(returns): E2E for unit and quantity return flows"
```

---

### Task 14: Review and ship

High-risk change (append-only ledgers, FIFO, money) — CLAUDE.md §5 makes the extra reviewers mandatory, not optional.

**Files:** none — this task gates the PR.

- [ ] **Step 1: Run the full backend suite against `app_test`**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file backend/.test.env -v "$PWD/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/ -q
```

Expected: 0 failed.

- [ ] **Step 2: Run the frontend unit suite, typecheck, and lint**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest \
  bash -c "bun run test:unit && bunx tsc --noEmit && bunx biome check src"
```

Expected: clean.

- [ ] **Step 3: Apply m035 to the dev `app` database**

```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic current
```

Expected: `a2b3c4d5e6f7 (head)`.

- [ ] **Step 4: Run the review stage**

Invoke `superpowers:requesting-code-review`, and additionally dispatch `ecc:database-reviewer` and `ecc:security-reviewer` — both are required for changes to stock movements, ledgers, and money. Focus their attention on:
- the FIFO rollback's reverse-order mapping and its behaviour across repeated partial returns
- batch lock ordering vs `consume_quantity_fifo` (deadlock surface)
- the sale-line `FOR UPDATE` as the only over-return serialization point
- admin-only enforcement on both new endpoints, and cost data exposure on `SaleReturnPublic` / `ReturnableLinePublic`
- report reconciliation across all four groupings

Fix everything they raise before the PR.

- [ ] **Step 5: Open the PR**

Use `superpowers:create-pr`. One PR, into `dev`, titled `feat: sale returns (FIFO rollback + margin reversal)`. Body should state: the migration (m035) must be applied on deploy; returns are online-only and admin-only; and the out-of-scope list from the design (ticket-part returns, return-to-supplier, defective/write-off returns, refund payment processing, editing a recorded return).

---

## Notes for the implementer

- **`SaleReturn` / `SaleReturnLine` have no append-only trigger, by design.** The guarantee that matters lives on the movements they produce, which the M021 triggers already protect. There is no update or delete endpoint, and none should be added — a mistake is corrected with a compensating sale or adjustment.
- **Returns do not appear in the SKU consumption history.** `_CONSUMING_EVENTS` (crud.py:1837) whitelists the four outbound events, and `RETURNED` is inbound. That is correct — the history answers "where did this stock go", not "what came back". Stock-on-hand and batch remaining quantities do reflect returns immediately, because both derive from `PartBatch.remaining_qty` / `Unit.current_state`.
- **Returns never fire a low-stock alert.** They only add stock, and `consume_quantity_fifo` is not on the return path — so `session.info["low_stock_crossed"]` is never populated and the route has nothing to dispatch.
- **`ServiceTicketPart` still has no `idempotency_key`** (known backlog, CLAUDE.md). Untouched by this work; do not fold a fix into this PR.
