# Receive Date Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin set the receive date on both Receive tabs (defaulting to today) so the holding-period report is accurate for deliveries entered late.

**Architecture:** The client sends a calendar date (`"2026-07-10"`), never a timestamp. The server validates it is not in the future and composes `received_at` as *picked date + the server's current clock time*, then passes it into the existing `Unit` / `PartBatch` constructors. No schema change and no Alembic migration — both `received_at` columns already exist; only the source of the value changes. `received_at` is also the FIFO sort key, so FIFO order follows the picked date by design.

**Tech Stack:** FastAPI + SQLModel + Pydantic v2 (backend), pytest, React + TypeScript + TanStack Query (frontend), vitest, Playwright, `@hey-api/openapi-ts` for the SDK.

**Spec:** `docs/superpowers/specs/2026-07-25-receive-date-picker-design.md`

## Global Constraints

- **No Alembic migration.** `Unit.received_at` (`models.py:650`) and `PartBatch.received_at` (`models.py:845`) already exist as NOT NULL timestamps with `now()` server defaults. If you find yourself writing a migration, stop — you have misread the design.
- **`received_date` is optional with a `None` default on both request models.** Omitting it must reproduce today's behaviour byte for byte. `seed_demo.py` has 3 call sites and the whole existing test suite calls these functions without it; none may be edited.
- **`occurred_at` on `UnitMovement` / `PartMovement` is never backdated.** The movement ledger is append-only audit truth. Only `received_at` moves.
- **The future-date check carries a one-day tolerance:** `received_date > date.today() + timedelta(days=1)` → 422. This is exactly the maximum timezone skew for Yangon (UTC+6:30) / Bangkok (UTC+7), which run ahead of UTC. A strict `> date.today()` check would reject the client's default date between local midnight and ~06:30. Do not "tighten" it.
- **The client's date helper must use the LOCAL date**, not `toISOString()` (which is UTC and would show yesterday's date to an operator after 17:00 UTC).
- **Never run `generate-client` inside the frontend container** — it regenerates from a stale image-baked `openapi.json` and silently drops new fields. Run it on the host.
- **Backend baseline is 0 failed.** Any pre-existing failure you see is something you introduced.
- Strict mypy and biome must pass; `prek` runs on commit.
- Money stays as strings/Decimal across the boundary — do not introduce floats.

---

### Task 1: `crud.receive_quantity` accepts an explicit `received_at`

**Files:**
- Modify: `backend/app/crud.py:1042-1097` (`receive_quantity`)
- Test: `backend/tests/crud/test_batch_no.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `crud.receive_quantity(..., received_at: datetime | None = None) -> PartBatch`. When `received_at` is supplied it becomes both `PartBatch.received_at` and the source of the `batch_no` date prefix. Task 3 calls this with a composed timestamp; Task 4 calls it with a backdated one.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/crud/test_batch_no.py`. The file already has the `quantity_setup` fixture and imports `date`; add `datetime`/`timedelta`/`timezone` and `Decimal` to its imports.

```python
def test_receive_quantity_backdates_received_at_and_batch_no(
    db: Session, quantity_setup: tuple[Product, Supplier, User]
) -> None:
    """An explicit received_at drives BOTH the stored timestamp and the
    YYYYMMDD prefix of batch_no, so the label matches the arrival date."""
    product, supplier, user = quantity_setup
    backdated = datetime(2026, 7, 10, 14, 32, tzinfo=timezone.utc)

    batch = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("5.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=backdated,
    )

    assert batch.received_at == backdated
    assert batch.batch_no == f"20260710-{product.sku}-001"


def test_receive_quantity_without_received_at_uses_now(
    db: Session, quantity_setup: tuple[Product, Supplier, User]
) -> None:
    """Omitting received_at reproduces the pre-existing behaviour: the batch is
    stamped ~now and numbered with today's date."""
    product, supplier, user = quantity_setup
    before = datetime.now(timezone.utc)

    batch = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("5.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )

    assert before - timedelta(seconds=5) <= batch.received_at
    assert batch.received_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert batch.batch_no.startswith(date.today().strftime("%Y%m%d"))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && pytest tests/crud/test_batch_no.py -v -k "backdates or without_received_at"
```

Expected: `test_receive_quantity_backdates_received_at_and_batch_no` FAILS with `TypeError: receive_quantity() got an unexpected keyword argument 'received_at'`. The `without_received_at` test PASSES already — that is intentional, it is the regression guard proving Step 3 changes nothing on the default path.

- [ ] **Step 3: Add the parameter**

In `backend/app/crud.py`, change the `receive_quantity` signature (currently ending at `note: str | None = None,`) to add one more keyword-only parameter:

```python
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
    received_at: datetime | None = None,
) -> PartBatch:
```

Then, immediately before the `batch = PartBatch(` construction (currently `crud.py:1083`), normalise the value:

```python
    # An operator-picked receive date arrives already composed with a clock time
    # (routes/receipts.py). Normalising to a concrete timestamp here — rather
    # than leaving the column default to fire — lets batch_no share the same
    # date, so a backdated receipt's label matches its received_at.
    if received_at is None:
        received_at = get_datetime_utc()
```

And change the construction to use it in both places:

```python
    batch = PartBatch(
        product_id=product_id,
        batch_no=next_batch_no(
            session=session,
            product_id=product_id,
            sku=product.sku,
            today=received_at.date(),
        ),
        supplier_id=supplier_id,
        supplier_batch_ref=supplier_batch_ref,
        received_qty=received_qty,
        remaining_qty=received_qty,
        purchase_cost_thb=purchase_cost_thb,
        received_by_user_id=received_by_user_id,
        received_at=received_at,
    )
```

Note the `today=date.today()` argument is replaced by `today=received_at.date()`. `get_datetime_utc` returns UTC, so on the UTC application container this is the same date `date.today()` produced; the change only bites when a date is explicitly supplied.

`get_datetime_utc` is already imported in `crud.py` (used at line 1588) and `datetime` is already imported (used at line 1518) — verify both before adding imports, and do not add duplicates.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && pytest tests/crud/test_batch_no.py -v
```

Expected: all tests PASS, including the 5 pre-existing `next_batch_no` tests.

- [ ] **Step 5: Run the wider suite for regressions**

```bash
cd backend && pytest tests/crud/ tests/api/routes/test_receipts_quantity.py tests/api/routes/test_holding_period.py -q
```

Expected: 0 failed. These exercise `receive_quantity` without `received_at`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/crud/test_batch_no.py
git commit -m "feat(receive): receive_quantity accepts explicit received_at

Drives both PartBatch.received_at and the batch_no date prefix, so a
backdated receipt's label matches its arrival date. Omitting the
argument reproduces prior behaviour exactly."
```

---

### Task 2: `crud.receive_serialized` accepts an explicit `received_at`

**Files:**
- Modify: `backend/app/crud.py:883-970` (`receive_serialized`)
- Test: `backend/tests/crud/test_idempotency.py` (append) — or a new `backend/tests/crud/test_receive_backdate.py` if you prefer isolation; either is acceptable, but do not create both.

**Interfaces:**
- Consumes: nothing from Task 1 (independent function, same file).
- Produces: `crud.receive_serialized(..., received_at: datetime | None = None) -> list[Unit]`. All pieces in one call share the timestamp — one receipt is one delivery.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/crud/test_receive_backdate.py`:

```python
"""Explicit received_at on serialized receives (design 2026-07-25).

One receipt is one delivery, so every piece in a call shares the timestamp."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    Product,
    ProductCreate,
    ReceivePiece,
    Supplier,
    SupplierCreate,
    TrackingMode,
    User,
)


@pytest.fixture
def serialized_setup(db: Session) -> tuple[Product, Supplier, User]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    return product, supplier, user


def test_receive_serialized_backdates_all_pieces(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = serialized_setup
    backdated = datetime(2026, 7, 10, 14, 32, tzinfo=timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-B1", purchase_cost_thb=Decimal("900.00")),
            ReceivePiece(supplier_serial="SN-B2", purchase_cost_thb=Decimal("900.00")),
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=backdated,
    )

    assert len(units) == 2
    assert all(u.received_at == backdated for u in units)


def test_receive_serialized_without_received_at_uses_now(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = serialized_setup
    before = datetime.now(timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-N1", purchase_cost_thb=Decimal("900.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )

    assert before - timedelta(seconds=5) <= units[0].received_at
    assert units[0].received_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_receive_serialized_movement_occurred_at_is_not_backdated(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    """The ledger records WHEN WE RECORDED IT, never the arrival date — the gap
    between the two is itself the audit signal."""
    from app.models import UnitMovement

    product, supplier, user = serialized_setup
    backdated = datetime(2026, 7, 10, 14, 32, tzinfo=timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-M1", purchase_cost_thb=Decimal("900.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=backdated,
    )

    movement = db.exec(
        select(UnitMovement).where(UnitMovement.unit_id == units[0].id)
    ).one()
    assert movement.occurred_at > backdated + timedelta(days=1)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && pytest tests/crud/test_receive_backdate.py -v
```

Expected: the two tests passing `received_at=` FAIL with `TypeError: receive_serialized() got an unexpected keyword argument 'received_at'`. `test_receive_serialized_without_received_at_uses_now` PASSES already — the regression guard.

- [ ] **Step 3: Add the parameter**

In `backend/app/crud.py`, change the `receive_serialized` signature to add the keyword-only parameter:

```python
def receive_serialized(
    *,
    session: Session,
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    pieces: list[ReceivePiece],
    idempotency_key: uuid.UUID,
    received_by_user_id: uuid.UUID,
    received_at: datetime | None = None,
) -> list[Unit]:
```

Then, immediately after the `state = assert_unit_transition(...)` line (currently `crud.py:929`), normalise:

```python
    # One receipt is one delivery: every piece shares the arrival timestamp.
    if received_at is None:
        received_at = get_datetime_utc()
```

And add one field to the `Unit(...)` construction inside the loop:

```python
        unit = Unit(
            product_id=product_id,
            supplier_id=supplier_id,
            supplier_serial=piece.supplier_serial,
            castranova_barcode="CN-" + uuid.uuid4().hex[:16].upper(),
            current_state=state,
            current_location_id=ygn.id,
            purchase_cost_thb=piece.purchase_cost_thb,
            received_by_user_id=received_by_user_id,
            received_at=received_at,
        )
```

Leave the `UnitMovement(...)` construction untouched — `occurred_at` stays real-time.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && pytest tests/crud/test_receive_backdate.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the wider suite for regressions**

```bash
cd backend && pytest tests/crud/ tests/api/routes/test_receipts_serialized.py tests/api/routes/test_holding_period.py -q
```

Expected: 0 failed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/crud/test_receive_backdate.py
git commit -m "feat(receive): receive_serialized accepts explicit received_at

All pieces in one receipt share the arrival timestamp. Movement
occurred_at stays real-time — the ledger records when we recorded it."
```

---

### Task 3: `received_date` on the request models + route composition and validation

**Files:**
- Modify: `backend/app/models.py:794-798` (`ReceiveSerializedRequest`), `backend/app/models.py:998-1010` (`ReceiveQuantityRequest`)
- Modify: `backend/app/api/routes/receipts.py:1-56`
- Test: `backend/tests/api/routes/test_receipts_quantity.py` (append), `backend/tests/api/routes/test_receipts_serialized.py` (append)

**Interfaces:**
- Consumes: `crud.receive_quantity(..., received_at=...)` from Task 1; `crud.receive_serialized(..., received_at=...)` from Task 2.
- Produces: both endpoints accept an optional `received_date` JSON field (ISO `YYYY-MM-DD`). This is the field name the generated SDK will expose to Tasks 5 and 6.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/routes/test_receipts_quantity.py`. Add `from datetime import date, time, timedelta` to its imports; `PartBatch` is already imported.

```python
def test_receive_quantity_accepts_received_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """A picked date drives received_at and the batch_no prefix."""
    product_id, supplier_id, sku = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date="2026-07-10"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_no"] == f"20260710-{sku}-001"

    db.expire_all()
    batch = db.get(PartBatch, uuid.UUID(body["id"]))
    assert batch is not None
    assert batch.received_at.date() == date(2026, 7, 10)


def test_receive_quantity_composes_current_clock_time(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Two same-day receives get DISTINCT timestamps, so FIFO between them
    follows entry order rather than the random uuid tiebreaker."""
    product_id, supplier_id, _ = seed_quantity_product
    stamps = []
    for _i in range(2):
        r = client.post(
            f"{PREFIX}/receipts/quantity",
            headers=superuser_token_headers,
            json=_body(product_id, supplier_id, received_date="2026-07-10"),
        )
        assert r.status_code == 200, r.text
        db.expire_all()
        batch = db.get(PartBatch, uuid.UUID(r.json()["id"]))
        assert batch is not None
        stamps.append(batch.received_at)

    assert stamps[0] != stamps[1]
    assert stamps[0] < stamps[1]
    # Neither collapsed to midnight — that is the tie that would hand FIFO
    # ordering over to the random uuid4 primary key.
    assert stamps[0].timetz().replace(tzinfo=None) != time(0, 0)


def test_receive_quantity_rejects_future_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    future = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date=future),
    )
    assert r.status_code == 422
    assert "future" in r.json()["detail"].lower()


def test_receive_quantity_allows_one_day_timezone_skew(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Yangon/Bangkok run ahead of UTC, so the client's LOCAL 'today' can be one
    day past the server's UTC today. That must not be rejected."""
    product_id, supplier_id, _ = seed_quantity_product
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date=tomorrow),
    )
    assert r.status_code == 200, r.text


def test_receive_quantity_omitting_received_date_uses_today(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, sku = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["batch_no"].startswith(date.today().strftime("%Y%m%d"))
```

Append to `backend/tests/api/routes/test_receipts_serialized.py` (add `from datetime import date, timedelta`):

```python
def test_receive_serialized_accepts_received_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    r = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date="2026-07-10"),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    unit = db.get(Unit, uuid.UUID(r.json()["units"][0]["id"]))
    assert unit is not None
    assert unit.received_at.date() == date(2026, 7, 10)


def test_receive_serialized_rejects_future_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    future = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date=future),
    )
    assert r.status_code == 422
    assert "future" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && pytest tests/api/routes/test_receipts_quantity.py tests/api/routes/test_receipts_serialized.py -v -k "received_date or future or skew or clock"
```

Expected: FAIL. Pydantic ignores the unknown `received_date` field by default, so the assertions on `batch_no` / `received_at` fail rather than erroring, and the future-date tests return 200 instead of 422.

- [ ] **Step 3: Add the request-model fields**

In `backend/app/models.py`, `date` is already imported (line 3: `from datetime import date, datetime, timezone`) — do not add an import.

```python
class ReceiveSerializedRequest(SQLModel):
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    pieces: list[ReceivePiece] = Field(min_length=1, max_length=500)
    idempotency_key: uuid.UUID
    # Operator-picked arrival date; None → today. The server composes the stored
    # timestamp (routes/receipts.py) so a wrong client clock cannot forge one.
    received_date: date | None = None
```

```python
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
    # Operator-picked arrival date; None → today. Also drives the batch_no prefix.
    received_date: date | None = None
```

- [ ] **Step 4: Add composition + validation to the routes**

Replace the import block and both handlers in `backend/app/api/routes/receipts.py`:

```python
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app import crud
from app.api.deps import AdminUser, SessionDep, get_current_user
from app.models import (
    PartBatchPublic,
    ReceiveQuantityRequest,
    ReceiveSerializedRequest,
    ReceiveSerializedResponse,
    get_datetime_utc,
)
from app.services.barcode import render_label_sheet

router = APIRouter(prefix="/receipts", tags=["receipts"])


def _resolve_received_at(received_date: date | None) -> datetime | None:
    """Compose the stored ``received_at`` from an operator-picked calendar date
    and the server's *current clock time* (design 2026-07-25).

    Returning None when no date was picked lets crud fall through to its own
    default, so an omitted date behaves exactly as it did before this field
    existed.

    Composing with the clock time rather than collapsing to midnight keeps every
    receive distinct: ``received_at`` is the FIFO sort key and its tiebreaker is
    a random uuid4 primary key, so same-day midnight ties would make the choice
    of which batch a sale draws its cost from non-deterministic.

    The one-day tolerance on the future check absorbs timezone skew — the client
    sends its LOCAL date, and the local operating zones (Yangon UTC+6:30,
    Bangkok UTC+7) run ahead of UTC, so between local midnight and ~06:30 the
    picked 'today' is one day past the server's UTC today."""
    if received_date is None:
        return None
    if received_date > date.today() + timedelta(days=1):
        raise HTTPException(
            status_code=422, detail="received_date cannot be in the future"
        )
    return datetime.combine(received_date, get_datetime_utc().timetz())


@router.post("/serialized", response_model=ReceiveSerializedResponse)
def receive_serialized(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveSerializedRequest,
) -> ReceiveSerializedResponse:
    units = crud.receive_serialized(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        pieces=payload.pieces,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
        received_at=_resolve_received_at(payload.received_date),
    )
    return ReceiveSerializedResponse(units=units)


@router.post("/quantity", response_model=PartBatchPublic)
def receive_quantity(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveQuantityRequest,
) -> PartBatchPublic:
    batch = crud.receive_quantity(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        received_qty=payload.received_qty,
        purchase_cost_thb=payload.purchase_cost_thb,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
        supplier_batch_ref=payload.supplier_batch_ref,
        expected_qty=payload.expected_qty,
        note=payload.note,
        received_at=_resolve_received_at(payload.received_date),
    )
    return PartBatchPublic.model_validate(batch)
```

`datetime.combine(d, t)` carries `t`'s tzinfo, and `get_datetime_utc().timetz()` is UTC-aware, so the result is a tz-aware UTC timestamp matching the column type. Leave `read_unit_label` below untouched.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && pytest tests/api/routes/test_receipts_quantity.py tests/api/routes/test_receipts_serialized.py -v
```

Expected: all pass, including the ~18 pre-existing tests in those two files.

- [ ] **Step 6: Typecheck and run the full backend suite**

```bash
cd backend && mypy app && pytest -q
```

Expected: mypy clean; 0 failed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/api/routes/receipts.py \
        backend/tests/api/routes/test_receipts_quantity.py \
        backend/tests/api/routes/test_receipts_serialized.py
git commit -m "feat(receive): accept received_date on both receive endpoints

Server composes received_at from the picked date + current clock time;
future dates are rejected with a one-day timezone-skew tolerance."
```

---

### Task 4: Prove the FIFO and holding-period behaviour

**Files:**
- Test: `backend/tests/crud/test_fifo_backdate.py` (create)

This task adds **no production code**. It is the high-risk verification the design exists to justify: that a backdated receipt actually reorders FIFO consumption and actually fixes the holding-period figure. Per `CLAUDE.md`, FIFO-touching work must carry this proof before a PR.

**Interfaces:**
- Consumes: `crud.receive_quantity(..., received_at=...)` (Task 1), `crud.receive_serialized(..., received_at=...)` (Task 2).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the tests**

Create `backend/tests/crud/test_fifo_backdate.py`:

```python
"""A backdated receipt must reorder FIFO consumption and correct the
holding-period figure — the two behaviours the receive date picker exists for
(design 2026-07-25). received_at is BOTH the FIFO sort key (crud.py:1152) and
the holding-period basis (crud.py:1632), so these move together by design."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    PartBatch,
    Product,
    ProductCreate,
    ReceivePiece,
    Supplier,
    SupplierCreate,
    TrackingMode,
    User,
    get_datetime_utc,
)


@pytest.fixture
def qty_setup(db: Session) -> tuple[Product, Supplier, User]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"FIFOBD-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    return product, supplier, user


def test_backdated_batch_is_consumed_before_existing_newer_stock(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """THE core behavioural claim of this feature. Stock already on the shelf is
    received today at 100; a delivery that physically arrived 15 days ago is then
    keyed in at 80. The next sale must draw from the 80 batch, because it arrived
    first."""
    product, supplier, user = qty_setup

    newer = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("100.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    older = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=15),
    )

    crud.consume_quantity_fifo(session=db, product_id=product.id, quantity_needed=5)
    db.expire_all()

    drained = db.get(PartBatch, older.id)
    untouched = db.get(PartBatch, newer.id)
    assert drained is not None and untouched is not None
    assert drained.remaining_qty == 0, "the backdated batch must be consumed first"
    assert untouched.remaining_qty == 5, "today's batch must be left alone"


def test_backdated_batch_reports_its_real_holding_age(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """The bug this feature fixes: a delivery entered late used to report ~0
    holding days instead of its true age."""
    product, supplier, user = qty_setup
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=120),
    )

    report = crud.holding_period_report(session=db)
    rows = [r for r in report.rows if r.sku == product.sku]
    assert len(rows) == 1
    assert rows[0].holding_days >= 119
    assert rows[0].over_threshold is True


def test_backdated_serialized_unit_reports_its_real_holding_age(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    _product, supplier, user = qty_setup
    sproduct = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SERBD-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=sproduct.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-BD1", purchase_cost_thb=Decimal("600.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=120),
    )

    report = crud.holding_period_report(session=db)
    rows = [r for r in report.rows if r.reference == units[0].castranova_barcode]
    assert len(rows) == 1
    assert rows[0].holding_days >= 119
    assert rows[0].over_threshold is True


def test_replay_of_a_backdated_receive_does_not_redate_it(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """Idempotent replay returns the stored row untouched — a retry days later
    must not shift the arrival date it already recorded."""
    product, supplier, user = qty_setup
    key = uuid.uuid4()
    backdated = get_datetime_utc() - timedelta(days=30)

    first = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=key,
        received_by_user_id=user.id,
        received_at=backdated,
    )
    replay = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=key,
        received_by_user_id=user.id,
        received_at=get_datetime_utc(),
    )

    assert replay.id == first.id
    assert replay.received_at == first.received_at
```

- [ ] **Step 2: Run them**

```bash
cd backend && pytest tests/crud/test_fifo_backdate.py -v
```

Expected: 4 passed. If `test_backdated_batch_is_consumed_before_existing_newer_stock` fails, **stop** — the feature does not work and Tasks 1/3 need revisiting, not the test.

- [ ] **Step 3: Run the mandatory FIFO concurrency test**

`CLAUDE.md` requires this before any PR touching consumption.

```bash
cd backend && pytest tests/crud/test_fifo.py tests/crud/test_fifo_concurrency.py -v
```

Expected: 0 failed.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/crud/test_fifo_backdate.py
git commit -m "test(receive): prove backdating reorders FIFO and fixes holding age

Covers the two behaviours the date picker exists for, plus that an
idempotent replay never re-dates an already-stored receipt."
```

---

### Task 5: Frontend form logic — `todayISO`, builders, submit guards

**Files:**
- Modify: `frontend/src/lib/receive-form.ts`
- Test: `frontend/src/lib/receive-form.test.ts` (create)
- Regenerate: `frontend/src/client/` (via script — never hand-edit)

**Interfaces:**
- Consumes: the `received_date` field on the generated `ReceiveQuantityRequest` / `ReceiveSerializedRequest` types (Task 3).
- Produces:
  - `todayISO(): string` — local date as `YYYY-MM-DD`
  - `isValidReceivedDate(value: string): boolean`
  - `QuantityDraft` gains `receivedDate: string`
  - `buildReceiveSerializedRequest(pieces, productId, supplierId, idempotencyKey, receivedDate)` — `receivedDate` **appended last** so no existing positional argument moves
  - `canSubmitSerialized(pieces, productId, supplierId, receivedDate)` — `receivedDate` appended last

- [ ] **Step 1: Regenerate the SDK**

The backend now advertises `received_date` in its OpenAPI schema. Run this **on the host, not in the frontend container** — the container regenerates from a stale image-baked `openapi.json` and would silently drop the new field.

```bash
cd frontend && bun run generate-client
```

Verify the field landed before going further:

```bash
grep -n "received_date" frontend/src/client/types.gen.ts
```

Expected: matches inside both `ReceiveQuantityRequest` and `ReceiveSerializedRequest`. If there are no matches, the backend was not running the new code — restart it and re-run.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/lib/receive-form.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  buildReceiveQuantityRequest,
  buildReceiveSerializedRequest,
  canSubmitQuantity,
  canSubmitSerialized,
  isValidReceivedDate,
  type QuantityDraft,
  todayISO,
} from "./receive-form"

const VALID_DRAFT: QuantityDraft = {
  productId: "p1",
  supplierId: "s1",
  receivedQty: "10",
  purchaseCostThb: "5.00",
  supplierBatchRef: "",
  expectedQty: "",
  note: "",
  receivedDate: "2026-07-10",
}

describe("todayISO", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("returns the LOCAL date as YYYY-MM-DD", () => {
    // 23:30 local on 25 Jul. toISOString() would report the 26th in any zone
    // west of UTC and the 25th in Bangkok — we always want the wall-clock date.
    vi.setSystemTime(new Date(2026, 6, 25, 23, 30))
    expect(todayISO()).toBe("2026-07-25")
  })

  it("zero-pads single-digit months and days", () => {
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0))
    expect(todayISO()).toBe("2026-01-05")
  })
})

describe("isValidReceivedDate", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 25, 12, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("accepts today", () => {
    expect(isValidReceivedDate("2026-07-25")).toBe(true)
  })

  it("accepts a past date", () => {
    expect(isValidReceivedDate("2026-07-10")).toBe(true)
  })

  it("rejects a future date", () => {
    expect(isValidReceivedDate("2026-07-26")).toBe(false)
  })

  it("rejects an empty or malformed value", () => {
    expect(isValidReceivedDate("")).toBe(false)
    expect(isValidReceivedDate("10/07/2026")).toBe(false)
  })
})

describe("buildReceiveQuantityRequest", () => {
  it("passes received_date through untouched", () => {
    const req = buildReceiveQuantityRequest(VALID_DRAFT, "idem-1")
    expect(req.received_date).toBe("2026-07-10")
  })
})

describe("buildReceiveSerializedRequest", () => {
  it("passes received_date through untouched", () => {
    const req = buildReceiveSerializedRequest(
      [{ key: "k1", supplierSerial: "SN-1", purchaseCostThb: "900" }],
      "p1",
      "s1",
      "idem-1",
      "2026-07-10",
    )
    expect(req.received_date).toBe("2026-07-10")
  })
})

describe("submit guards reject a bad date", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 25, 12, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("canSubmitQuantity is false when the date is cleared", () => {
    expect(canSubmitQuantity(VALID_DRAFT)).toBe(true)
    expect(canSubmitQuantity({ ...VALID_DRAFT, receivedDate: "" })).toBe(false)
  })

  it("canSubmitQuantity is false when the date is in the future", () => {
    expect(
      canSubmitQuantity({ ...VALID_DRAFT, receivedDate: "2026-08-01" }),
    ).toBe(false)
  })

  it("canSubmitSerialized is false when the date is cleared", () => {
    const pieces = [
      { key: "k1", supplierSerial: "SN-1", purchaseCostThb: "900" },
    ]
    expect(canSubmitSerialized(pieces, "p1", "s1", "2026-07-10")).toBe(true)
    expect(canSubmitSerialized(pieces, "p1", "s1", "")).toBe(false)
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

```bash
cd frontend && bun run test:unit src/lib/receive-form.test.ts
```

Expected: FAIL — `todayISO` and `isValidReceivedDate` are not exported.

- [ ] **Step 4: Implement**

In `frontend/src/lib/receive-form.ts`, add `receivedDate` to the draft type:

```ts
/** In-progress state of the quantity-receive form (all strings from inputs). */
export type QuantityDraft = {
  productId: string
  supplierId: string
  receivedQty: string
  purchaseCostThb: string
  supplierBatchRef: string
  expectedQty: string
  note: string
  receivedDate: string
}
```

Add the two date helpers below the type declarations:

```ts
// ---------------------------------------------------------------------------
// Receive date
// ---------------------------------------------------------------------------

/** Today as `YYYY-MM-DD` in the operator's LOCAL timezone — the shape an
 * `<input type="date">` emits. Deliberately not `toISOString()`, which is UTC
 * and would show the wrong calendar day either side of midnight. */
export function todayISO(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** A well-formed, non-future receive date. ISO dates compare correctly as
 * strings, so no Date parsing is needed. The server re-checks this — the guard
 * here only stops an obviously-bad submit. */
export function isValidReceivedDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value <= todayISO()
}
```

Thread the field through both builders:

```ts
export function buildReceiveSerializedRequest(
  pieces: DraftPiece[],
  productId: string,
  supplierId: string,
  idempotencyKey: string,
  receivedDate: string,
): ReceiveSerializedRequest {
  return {
    product_id: productId,
    supplier_id: supplierId,
    pieces: pieces.map((p) => ({
      supplier_serial: p.supplierSerial.trim(),
      purchase_cost_thb: p.purchaseCostThb.trim(),
    })),
    idempotency_key: idempotencyKey,
    received_date: receivedDate,
  }
}
```

```ts
export function buildReceiveQuantityRequest(
  draft: QuantityDraft,
  idempotencyKey: string,
): ReceiveQuantityRequest {
  return {
    product_id: draft.productId,
    supplier_id: draft.supplierId,
    received_qty: Number(draft.receivedQty),
    purchase_cost_thb: draft.purchaseCostThb.trim(),
    supplier_batch_ref: draft.supplierBatchRef.trim() || null,
    expected_qty:
      draft.expectedQty.trim() !== "" ? Number(draft.expectedQty.trim()) : null,
    note: draft.note.trim() || null,
    idempotency_key: idempotencyKey,
    received_date: draft.receivedDate,
  }
}
```

And into both guards:

```ts
export function canSubmitSerialized(
  pieces: DraftPiece[],
  productId: string,
  supplierId: string,
  receivedDate: string,
): boolean {
  return (
    Boolean(productId) &&
    Boolean(supplierId) &&
    isValidReceivedDate(receivedDate) &&
    pieces.length >= 1 &&
    pieces.every(
      (p) =>
        p.supplierSerial.trim().length > 0 && isPositiveCost(p.purchaseCostThb),
    )
  )
}

export function canSubmitQuantity(draft: QuantityDraft): boolean {
  const qty = Number(draft.receivedQty)
  return (
    Boolean(draft.productId) &&
    Boolean(draft.supplierId) &&
    isValidReceivedDate(draft.receivedDate) &&
    Number.isInteger(qty) &&
    qty >= 1 &&
    isPositiveCost(draft.purchaseCostThb)
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd frontend && bun run test:unit src/lib/receive-form.test.ts
```

Expected: all pass. `receive.tsx` will not typecheck yet — Task 6 fixes it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/receive-form.ts frontend/src/lib/receive-form.test.ts frontend/src/client/
git commit -m "feat(receive): receivedDate in form logic + regenerate SDK

todayISO uses the LOCAL date, not toISOString (UTC), so the default
matches the operator's wall clock. Guards reject empty/future dates."
```

---

### Task 6: Date input on both Receive tabs

**Files:**
- Modify: `frontend/src/routes/_layout/receive.tsx` — `SerializedTab` (lines ~116-262), `EMPTY_QUANTITY_DRAFT` (~430-438), `QuantityTab` (~440-565)

**Interfaces:**
- Consumes: `todayISO`, `isValidReceivedDate` (unused directly — the guards call it), the updated `QuantityDraft`, and the new 5th/4th arguments on `buildReceiveSerializedRequest` / `canSubmitSerialized` (Task 5).
- Produces: nothing consumed by later tasks except the Playwright selectors in Task 7 — the inputs must be labelled exactly **"Receive date"**.

- [ ] **Step 1: Extend the import and the empty draft**

Add `todayISO` to the existing import from `@/lib/receive-form`:

```ts
import {
  addPiece,
  buildReceiveQuantityRequest,
  buildReceiveSerializedRequest,
  canSubmitQuantity,
  canSubmitSerialized,
  type DraftPiece,
  type QuantityDraft,
  removePiece,
  todayISO,
} from "@/lib/receive-form"
```

`EMPTY_QUANTITY_DRAFT` is a module-level constant, so a `todayISO()` call in it would freeze at page-load time. Make it a function so a reset after submit re-reads the clock:

```ts
// A function, not a constant: todayISO() must be re-read on every reset, or a
// tablet left open overnight would keep defaulting to yesterday.
function emptyQuantityDraft(): QuantityDraft {
  return {
    productId: "",
    supplierId: "",
    receivedQty: "",
    purchaseCostThb: "",
    supplierBatchRef: "",
    expectedQty: "",
    note: "",
    receivedDate: todayISO(),
  }
}
```

Replace both references to the old constant: `useState<QuantityDraft>(emptyQuantityDraft())` and, in `onSuccess`, `setDraft(emptyQuantityDraft())`.

- [ ] **Step 2: Add the date input to `QuantityTab`**

In the **Delivery** grid (the `<div className="grid gap-4 sm:grid-cols-2">` holding Product and Supplier), append a third field after the Supplier block:

```tsx
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${fieldId}-received-date`}>
            Receive date
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Input
            id={`${fieldId}-received-date`}
            type="date"
            className="h-11"
            max={todayISO()}
            aria-required="true"
            disabled={mutation.isPending}
            value={draft.receivedDate}
            onChange={(e) => patch("receivedDate", e.target.value)}
          />
        </div>
```

- [ ] **Step 3: Add the date input + state to `SerializedTab`**

Add the state alongside the other `useState` calls:

```ts
  const [receivedDate, setReceivedDate] = useState(todayISO())
```

Add the same field to `SerializedTab`'s Delivery grid, after the Supplier block (this tab uses literal ids, not `useId`, matching its existing `receive-product` / `receive-supplier` pattern):

```tsx
        <div className="flex flex-col gap-2">
          <Label htmlFor="receive-date">
            Receive date
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <Input
            id="receive-date"
            type="date"
            className="h-11"
            max={todayISO()}
            aria-required="true"
            disabled={mutation.isPending}
            value={receivedDate}
            onChange={(e) => setReceivedDate(e.target.value)}
          />
        </div>
```

Pass it to the builder and the guard:

```ts
  function handleSubmit() {
    // Generate the idempotency_key ONCE per attempt, captured in the mutate
    // variables so an offline replay reuses the same key (backend dedupes).
    const request = buildReceiveSerializedRequest(
      pieces,
      productId,
      supplierId,
      crypto.randomUUID(),
      receivedDate,
    )
    mutation.mutate(queued(request, request.idempotency_key))
  }

  const canSubmit = canSubmitSerialized(pieces, productId, supplierId, receivedDate)
```

Do **not** reset `receivedDate` in `onSuccess`: a delivery is usually booked in as several consecutive receipts, so keeping the picked date across submits is the useful behaviour. The other fields still clear as they do today.

- [ ] **Step 4: Typecheck, lint, and run the unit suite**

```bash
cd frontend && bunx tsc --noEmit && bun run lint && bun run test:unit
```

Expected: clean. A `Property 'receivedDate' is missing` error means Step 1's `emptyQuantityDraft` swap was incomplete.

- [ ] **Step 5: Verify by hand**

Start the stack (`docker compose watch`), open `/receive`, and confirm on **both** tabs: the Receive date shows today, the native picker refuses dates after today, clearing it disables the Receive button, and a backdated quantity receive shows a success toast whose batch number starts with the backdated `YYYYMMDD`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/_layout/receive.tsx
git commit -m "feat(receive): date picker on both Receive tabs

Defaults to today, capped at today via the native max attribute.
emptyQuantityDraft is a function so a reset re-reads the clock."
```

---

### Task 7: E2E coverage

**Files:**
- Create: `frontend/tests/receive-date.spec.ts`

**Interfaces:**
- Consumes: the "Receive date" labels from Task 6.
- Produces: nothing.

- [ ] **Step 1: Read a neighbouring spec first**

```bash
cat frontend/tests/product-create.spec.ts
```

Match its conventions exactly — auth-state setup, `config.ts` imports, and how it selects products/suppliers in an `EntityCombobox`. Do not invent a different pattern.

- [ ] **Step 2: Write the spec**

Create `frontend/tests/receive-date.spec.ts`, following the conventions you just read. It must cover, on the **Quantity** tab:

1. The Receive date input defaults to today's local date.
2. Its `max` attribute equals today's local date (the future-date cap).
3. Backdating it to 10 days ago and completing a receive produces a success toast whose batch number begins with that backdated `YYYYMMDD`.

And on the **Serialized** tab:

4. The Receive date input is present and defaults to today.

Derive the expected dates in the spec with the same local-date arithmetic `todayISO()` uses — never `toISOString()`, or the assertion will flake either side of UTC midnight.

- [ ] **Step 3: Run it**

`E2E_SKIP_DB_RESET=1` is mandatory — without it `global.setup.ts` truncates and reseeds the shared dev database.

```bash
cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/receive-date.spec.ts
```

Expected: pass. Iterate on selectors until green; do not weaken the assertions to make it pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/receive-date.spec.ts
git commit -m "test(receive): E2E for the receive date picker

Covers the today default, the future-date cap, and that a backdated
quantity receive mints a batch_no with the backdated prefix."
```

---

### Task 8: Review and PR

**Files:** none — verification and handoff.

- [ ] **Step 1: Full green run**

```bash
cd backend && mypy app && pytest -q
cd ../frontend && bunx tsc --noEmit && bun run lint && bun run test:unit
```

Expected: backend 0 failed; frontend clean.

- [ ] **Step 2: Mandatory specialist review**

This change touches FIFO consumption ordering, so `CLAUDE.md` requires more than the standard pass. Dispatch via the Agent tool:

- `ecc:database-reviewer` — the `received_at` / `batch_no` coupling, the advisory-lock sequence under a backdated date, and FIFO ordering with ties.
- `ecc:security-reviewer` — that the client cannot forge a timestamp, and that the future-date guard cannot be bypassed.

Then run `superpowers:requesting-code-review` for the standard pass.

- [ ] **Step 3: Address findings**

Fix anything confirmed, re-run Step 1, and commit.

- [ ] **Step 4: Open the PR**

Use the `create-pr` skill. Target **`dev`** — never `master`. The PR body should state that there is no migration, that FIFO order now follows the picked date by design, and link the spec at `docs/superpowers/specs/2026-07-25-receive-date-picker-design.md`.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| No schema change / no migration | Global Constraints; asserted in Tasks 1-3 |
| `received_date` on both request models | Task 3 Step 3 |
| Picked date + current clock time | Task 3 Step 4 (`_resolve_received_at`) |
| Future dates blocked, server-side | Task 3 Step 4; tested Step 1 |
| One-day timezone-skew tolerance | Task 3 Step 4; tested by `test_receive_quantity_allows_one_day_timezone_skew` |
| Client sends a date, never a timestamp | Task 5 (`received_date: draft.receivedDate`) |
| `batch_no` follows the picked date | Task 1 Step 3 (`today=received_at.date()`) |
| `occurred_at` stays real-time | Task 2 Step 1 (`test_..._occurred_at_is_not_backdated`) |
| One date per receipt | Task 2 (`test_receive_serialized_backdates_all_pieces`) |
| Backdated batch consumed first | Task 4 |
| Holding period reflects the picked date | Task 4 (both tracking modes) |
| Replay does not re-date | Task 4 |
| Two same-day receives get distinct stamps | Task 3 (`test_..._composes_current_clock_time`) |
| `todayISO()` uses the local date | Task 5 |
| `max={todayISO()}` UI cap | Task 6 |
| Guards reject empty/future | Task 5 + Task 6 |
| SDK regenerated on the host | Task 5 Step 1 |
| Playwright coverage | Task 7 |
| `database-reviewer` + `security-reviewer` | Task 8 |
| Offline replay improvement | Incidental; no dedicated task (spec marks it "not a goal") |

**Type consistency:** `received_at: datetime | None` is the crud parameter name in Tasks 1, 2, 3 and 4. `received_date: date | None` is the request-model field in Task 3 and the JSON key in Tasks 3, 5. `receivedDate: string` is the TS draft field in Tasks 5 and 6. `todayISO()` and `isValidReceivedDate()` are defined in Task 5 and consumed in Tasks 5, 6, 7. `emptyQuantityDraft()` replaces `EMPTY_QUANTITY_DRAFT` at both of its call sites in Task 6.

**Placeholder scan:** Task 7 Step 2 describes four required behaviours rather than pasting a spec body — deliberate, because the selector and auth conventions must be copied from a neighbouring spec read in Step 1, and inventing them here would produce code that does not run. Every other code step contains complete, runnable content.
