# FR-015 Comprehensive Consumption History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add role-tiered SKU consumption history (QUANTITY products) and enrich the serialized-unit lifecycle view on the Search page, fulfilling PRD FR-015's batch-attribution + consumption requirements.

**Architecture:** Read-only over the existing `part_movement → cost_line → part_batch` and `unit_movement` ledgers — **no Alembic migration**. New Pydantic response schemas with omission-based staff/admin redaction (mirroring `SaleStaffPublic`). All DB access in `crud.py`; the `/search/sku` route branches on `is_admin` and returns the admin or staff variant. Frontend renders a new Consumption section (SKU) and richer History columns (serial).

**Tech Stack:** FastAPI, SQLModel, Pydantic v2, psycopg3, pytest (backend); React + TanStack Query/Router, shadcn/ui, `@hey-api/openapi-ts` SDK (frontend).

**Risk class:** High (FIFO/append-only ledger + cost reads on a both-roles surface). TDD is mandatory; the Review stage MUST run `requesting-code-review` + `ecc:database-reviewer` + `ecc:security-reviewer` before the PR into `dev`.

**Spec:** `docs/superpowers/specs/2026-06-17-fr015-consumption-history-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/models.py` | New SKU consumption + admin-batch schemas; serial movement enrichment fields | Modify |
| `backend/app/crud.py` | `search_sku` (consumption + role-tiered cost), `search_serial` (enrichment), private resolver helpers | Modify |
| `backend/app/api/routes/search.py` | Pass `current_user`/`is_admin`; union response model | Modify |
| `backend/tests/api/routes/test_search.py` | Behavior tests (consumption, FIFO draws, resolution, serial enrichment, bounds) | Modify |
| `backend/tests/api/test_staff_redaction_lock.py` | Extend staff cost-redaction lock to a consumed SKU | Modify |
| `frontend/src/client/` | Regenerated SDK (never hand-edit) | Regenerate |
| `frontend/src/routes/_layout/search.tsx` | Consumption section (SKU) + enriched History (serial) | Modify |

---

## Task 1: Backend response schemas

**Files:**
- Modify: `backend/app/models.py` (after `SkuSearchResult`, currently `models.py:1735-1740`; and `SerialMovementPublic`, `models.py:1704-1714`)

- [ ] **Step 1: Add serial enrichment fields to `SerialMovementPublic`**

Replace the existing `SerialMovementPublic` (`models.py:1704`) body's trailing `notes: str | None` so the class becomes:

```python
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
```

- [ ] **Step 2: Add SKU consumption schemas**

Insert immediately AFTER the `SkuSearchResult` class (`models.py:1740`). Add `consumption` to the existing `SkuSearchResult` and add the new classes:

```python
# Modify the existing SkuSearchResult to carry the staff consumption list:
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
```

> Note: `SkuSearchResult` references `SkuConsumptionEventPublic` defined below it — the forward reference string `"SkuConsumptionEventPublic"` handles that. Ensure `Decimal` and `MovementType` are already imported in `models.py` (they are — used by `Product`/`PartBatch`).

- [ ] **Step 3: Verify it imports and type-checks**

Run: `cd backend && uv run python -c "import app.models"`
Expected: no output (success). Then `uv run mypy app/models.py` — Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py
git commit -m "feat(fr015): add SKU consumption + admin-batch schemas and serial enrichment fields"
```

---

## Task 2: `crud.search_sku` — consumption history (staff path, no cost)

**Files:**
- Modify: `backend/app/crud.py` (`search_sku` at `crud.py:1282`; add helpers above it)
- Test: `backend/tests/api/routes/test_search.py`

- [ ] **Step 1: Write the failing test (staff consumption attribution)**

Add to `test_search.py`:

```python
def test_sku_search_staff_consumption_attribution(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    uid = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"CONS-{uuid.uuid4().hex[:8]}",
            model_name="Part",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=uid,
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Acme Buyer")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=product.sku, quantity=4)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=uid,
    )

    r = client.get(f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_on_hand"] == 6
    assert len(body["consumption"]) == 1
    ev = body["consumption"][0]
    assert ev["event_type"] == "SOLD"
    assert ev["reference_kind"] == "SALE"
    assert ev["quantity"] == 4
    assert ev["customer_name"] == "Acme Buyer"
    # Staff: NO cost anywhere.
    assert "total_cost_thb" not in ev
    assert "draws" not in ev
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py::test_sku_search_staff_consumption_attribution -v`
Expected: FAIL — `KeyError: 'consumption'` (field not yet returned).

- [ ] **Step 3: Add module constants + resolver helpers above `search_sku`**

Insert in `crud.py` immediately before `def search_sku` (`crud.py:1282`). Ensure these names are imported at the top of `crud.py`: `PartMovement, CostLine, Sale, ServiceTicket, ProjectPull, StockAdjustment, Customer, Project, User, SkuConsumptionEventPublic, SkuConsumptionEventAdminPublic, SkuConsumptionDrawAdminPublic, SkuBatchAdminPublic, SkuSearchAdminResult` (add any missing to the existing `from app.models import (...)` block).

```python
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
            select(CostLine).where(col(CostLine.part_movement_id).in_(movement_ids))
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
        common = dict(
            event_type=m.event_type,
            occurred_at=m.occurred_at,
            quantity=m.quantity,
            reference_kind=kind,
            reference_id=ref_id,
            customer_name=cust_name,
            project_name=proj_name,
            project_code=proj_code,
            actor_name=(actor.full_name if actor else None),
            notes=notes,
        )
        if is_admin:
            draws = draws_by_movement.get(m.id, [])
            events.append(
                SkuConsumptionEventAdminPublic(
                    **common,
                    total_cost_thb=sum(
                        (d.total_cost_thb for d in draws), Decimal("0")
                    ),
                    draws=draws,
                )
            )
        else:
            events.append(SkuConsumptionEventPublic(**common))
    return events
```

> `Any` is already imported in `crud.py`. If not, add `from typing import Any`.

- [ ] **Step 4: Rewrite `search_sku` to fetch consuming movements + branch on role**

Replace the whole `search_sku` function (`crud.py:1282-1315`) with:

```python
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
```

> `cast` keeps mypy happy on the admin branch. Add `from typing import cast` if not already imported in `crud.py`.

- [ ] **Step 5: Run the test (it still fails — route not updated yet)**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py::test_sku_search_staff_consumption_attribution -v`
Expected: still FAIL — the route calls `crud.search_sku(session=..., sku=...)` without `is_admin`, raising `TypeError`. Task 4 fixes the route; this confirms the crud signature changed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_search.py
git commit -m "feat(fr015): crud.search_sku builds role-tiered consumption history"
```

---

## Task 3: `crud.search_serial` — lifecycle enrichment

**Files:**
- Modify: `backend/app/crud.py` (`search_serial` at `crud.py:1255`; add helper above it)
- Test: `backend/tests/api/routes/test_search.py`

- [ ] **Step 1: Write the failing test (serial names + reference label)**

Add to `test_search.py`:

```python
def test_serial_search_enriches_names_and_reference(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    uid = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SREN-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[ReceivePiece(supplier_serial="SN-EN1", purchase_cost_thb=Decimal("600.00"))],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=uid,
    )
    barcode = units[0].castranova_barcode
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Buyer Co")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=uid,
    )

    r = client.get(f"{PREFIX}/search/serial/{barcode}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    moves = r.json()["movements"]
    received = next(m for m in moves if m["event_type"] == "RECEIVED")
    assert received["to_location_name"]  # resolved, not null
    assert received["actor_name"]  # resolved
    sold = next(m for m in moves if m["event_type"] == "SOLD")
    assert sold["reference_kind"] == "SALE"
    assert sold["reference_label"] == "Buyer Co"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py::test_serial_search_enriches_names_and_reference -v`
Expected: FAIL — `assert received["to_location_name"]` is `None` (field defaults to null).

- [ ] **Step 3: Add the serial-movement builder helper above `search_serial`**

Insert in `crud.py` immediately before `def search_serial` (`crud.py:1255`). Ensure `Location` is imported in `crud.py` (add to the models import if missing).

```python
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
        l.id: l.name
        for l in (
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
            s = sales.get(m.sale_id)
            label = customers.get(s.customer_id) if s else None
        elif m.service_ticket_id is not None:
            kind = "SERVICE_TICKET"
            t = tickets.get(m.service_ticket_id)
            label = customers.get(t.customer_id) if t else None
        elif m.project_pull_id is not None:
            kind = "PROJECT_PULL"
            p = pulls.get(m.project_pull_id)
            proj = projects.get(p.project_id) if p else None
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
```

- [ ] **Step 4: Use the helper in `search_serial`**

In `search_serial` (`crud.py:1255`), replace the line:

```python
        movements=[SerialMovementPublic.model_validate(m) for m in movements],
```

with:

```python
        movements=_build_serial_movements(session=session, movements=list(movements)),
```

- [ ] **Step 5: Run the test (still fails — route signature change pending)**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py::test_serial_search_enriches_names_and_reference -v`
Expected: PASS (the serial route signature is unchanged, so this one passes now).

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_search.py
git commit -m "feat(fr015): enrich serial lifecycle with resolved names and reference labels"
```

---

## Task 4: Route wiring + admin/staff HTTP redaction test

**Files:**
- Modify: `backend/app/api/routes/search.py`
- Test: `backend/tests/api/routes/test_search.py`

- [ ] **Step 1: Write the failing test (admin sees FIFO cost; staff does not)**

Add to `test_search.py` (use `superuser_token_headers`, the standard admin fixture in this suite):

```python
def test_sku_search_admin_sees_fifo_cost_breakdown(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    _seed(db)
    uid = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"FIFO-{uuid.uuid4().hex[:8]}",
            model_name="Part",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    # Two batches at different costs so a 7-unit sale spans both (FIFO 5 + 2).
    for qty, cost in ((5, "10.00"), (5, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=uid,
        )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Buyer")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=product.sku, quantity=7)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=uid,
    )

    ra = client.get(
        f"{PREFIX}/search/sku/{product.sku}", headers=superuser_token_headers
    )
    assert ra.status_code == 200, ra.text
    ev = ra.json()["consumption"][0]
    assert ev["quantity"] == 7
    assert len(ev["draws"]) == 2  # FIFO spanned two batches
    assert sum(d["quantity"] for d in ev["draws"]) == 7
    # 5*10 + 2*12 = 74
    assert Decimal(ev["total_cost_thb"]) == Decimal("74.00")
    assert "purchase_cost_thb" in ra.json()["batches"][0]

    rs = client.get(f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers)
    sev = rs.json()["consumption"][0]
    assert "draws" not in sev
    assert "total_cost_thb" not in sev
    assert "purchase_cost_thb" not in rs.json()["batches"][0]
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py::test_sku_search_admin_sees_fifo_cost_breakdown -v`
Expected: FAIL — route still calls `crud.search_sku` without `is_admin` (TypeError), or `draws` absent.

- [ ] **Step 3: Update the route**

Replace the entire contents of `backend/app/api/routes/search.py` with:

```python
from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import CurrentUser, get_current_user, is_admin
from app.models import (
    SerialSearchResult,
    SkuSearchAdminResult,
    SkuSearchResult,
)

router = APIRouter(
    prefix="/search",
    tags=["search"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/serial/{barcode}", response_model=SerialSearchResult)
def search_serial(*, session: SessionDep, barcode: str) -> SerialSearchResult:
    """Full lifecycle of a serialized unit by barcode, chronological (FR-015).
    Available to both roles; carries no cost fields."""
    return crud.search_serial(session=session, barcode=barcode)


@router.get(
    "/sku/{sku}", response_model=SkuSearchAdminResult | SkuSearchResult
)
def search_sku(
    *, session: SessionDep, current_user: CurrentUser, sku: str
) -> SkuSearchAdminResult | SkuSearchResult:
    """Batch attribution + QOH + consumption history for a SKU (FR-015). Admins
    see FIFO cost; staff see attribution without cost (spec §6.5)."""
    return crud.search_sku(
        session=session, sku=sku, is_admin=is_admin(current_user)
    )
```

> `SessionDep` is imported via the existing `from app.api.deps import SessionDep, get_current_user` — keep that import. The new line adds `CurrentUser` and `is_admin`. Verify `SessionDep` stays imported (the snippet above drops it from the import line — re-add it):
> `from app.api.deps import CurrentUser, SessionDep, get_current_user, is_admin`
> The admin variant is listed FIRST in the union so a returned admin object serializes with its cost fields (the proven `SalePublic | SaleStaffPublic` ordering in `sales.py`).

- [ ] **Step 4: Run the route + crud tests (now green)**

Run: `cd backend && uv run pytest tests/api/routes/test_search.py -v`
Expected: PASS — all search tests including the two new ones and `test_sku_search_staff_consumption_attribution`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/search.py backend/tests/api/routes/test_search.py
git commit -m "feat(fr015): /search/sku returns admin cost vs staff attribution"
```

---

## Task 5: Extend the staff redaction lock to a consumed SKU

**Files:**
- Modify: `backend/tests/api/test_staff_redaction_lock.py`

- [ ] **Step 1: Add a test that consumes stock, then sweeps the staff SKU search**

The existing `test_staff_sku_search_keeps_attribution_without_cost` only receives stock (no consumption). Add a sibling that also SELLS, so a consuming event with cost exists, then asserts the staff payload is cost-free yet keeps attribution. Append:

```python
def test_staff_sku_search_consumption_carries_no_cost(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    uid = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLCC-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=uid,
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Lock Buyer")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=product.sku, quantity=4)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=uid,
    )

    r = client.get(f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_no_forbidden_keys(body)  # NO cogs/cost/margin keys at any depth
    # Non-vacuous: the consuming event is present with attribution.
    assert body["consumption"], "consumption must be populated"
    ev = body["consumption"][0]
    assert ev["reference_kind"] == "SALE"
    assert ev["customer_name"] == "Lock Buyer"
```

> `SaleLineInput`, `SaleLineKind` are already imported in this test module (used elsewhere). If not, add them to the `from app.models import (...)` block.

- [ ] **Step 2: Run it**

Run: `cd backend && uv run pytest tests/api/test_staff_redaction_lock.py -v`
Expected: PASS — `_assert_no_forbidden_keys` finds no `cost`/`cogs`/`margin` key in the staff consumption payload.

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && bash ../scripts/test.sh` (or `uv run pytest -q`)
Expected: PASS (no regressions). If the FIFO concurrency test or other ledger tests run, they must stay green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_staff_redaction_lock.py
git commit -m "test(fr015): lock staff SKU consumption history against cost leakage"
```

---

## Task 6: Regenerate the frontend SDK

**Files:**
- Regenerate: `frontend/src/client/` (auto-generated — never hand-edit)

- [ ] **Step 1: Ensure the backend is importable and regenerate**

Run: `cd frontend && bun run generate-client` (or `./scripts/generate-client.sh` from repo root with the stack running per project convention).
Expected: `frontend/src/client/` updates — `SearchService.searchSku` return type becomes the `SkuSearchAdminResult | SkuSearchResult` union; `SerialMovementPublic` gains the new fields; new `SkuConsumptionEventPublic`/`...Admin`/`SkuConsumptionDrawAdminPublic`/`SkuBatchAdminPublic` types appear.

- [ ] **Step 2: Verify the new types exist**

Run: `cd frontend && grep -r "SkuConsumptionEvent" src/client/ | head`
Expected: matches in the generated types.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/client
git commit -m "chore(fr015): regenerate SDK for consumption-history schemas"
```

---

## Task 7: Frontend — SKU consumption section

**Files:**
- Modify: `frontend/src/routes/_layout/search.tsx` (`SkuSearch`, currently `search.tsx:136-228`)

- [ ] **Step 1: Render a Consumption section under Batches**

Inside `SkuSearch`, after the closing of the `tracking_mode === "QUANTITY"` Batches block (before the final `</div>`), add a consumption block. The payload's `consumption[]` items may or may not carry `draws`/`total_cost_thb` (admin vs staff) — render cost columns only when present (defensive double-guard atop server redaction):

```tsx
{data.tracking_mode === "QUANTITY" ? (
  <div>
    <h3 className="mb-2 text-sm font-medium">Consumption</h3>
    {data.consumption.length === 0 ? (
      <p className="text-muted-foreground text-sm">No consumption yet.</p>
    ) : (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead>Customer / Project</TableHead>
            <TableHead>By</TableHead>
            {"total_cost_thb" in data.consumption[0] ? (
              <TableHead className="text-right">COGS (฿)</TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.consumption.map((c) => (
            <TableRow key={c.reference_id + c.occurred_at}>
              <TableCell className="text-muted-foreground">
                {new Date(c.occurred_at).toLocaleString()}
              </TableCell>
              <TableCell>
                <Badge variant="outline">{consumptionLabel(c.event_type)}</Badge>
              </TableCell>
              <TableCell className="num text-right">{c.quantity}</TableCell>
              <TableCell className="text-muted-foreground">
                {c.project_name
                  ? `${c.project_code ?? ""} ${c.project_name}`.trim()
                  : (c.customer_name ?? "—")}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {c.actor_name ?? "—"}
              </TableCell>
              {"total_cost_thb" in c ? (
                <TableCell className="num text-right">
                  {(c as { total_cost_thb: string }).total_cost_thb}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    )}
  </div>
) : null}
```

- [ ] **Step 2: Add the `consumptionLabel` helper**

Near the top of `search.tsx` (module scope, beside the imports):

```tsx
function consumptionLabel(eventType: string): string {
  switch (eventType) {
    case "SOLD":
      return "Sale"
    case "MAINTENANCE_OUT":
      return "Service"
    case "PROJECT_OUT":
      return "Project"
    case "ADJUSTED_OUT":
      return "Adjustment"
    default:
      return eventType
  }
}
```

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && bun run build` (or `bunx tsc --noEmit`) then `bunx biome check src/routes/_layout/search.tsx`
Expected: no type errors, no lint errors. (If the generated union type makes `"total_cost_thb" in c` a type error, narrow via the generated admin type name instead.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/search.tsx
git commit -m "feat(fr015): SKU search shows consumption history (admin COGS, staff attribution)"
```

---

## Task 8: Frontend — serial History enrichment

**Files:**
- Modify: `frontend/src/routes/_layout/search.tsx` (`SerialSearch`, History table `search.tsx:104-127`)

- [ ] **Step 1: Add Location, By, and Reference columns**

Replace the History `<Table>` in `SerialSearch` with:

```tsx
<Table>
  <TableHeader>
    <TableRow>
      <TableHead>Event</TableHead>
      <TableHead>When</TableHead>
      <TableHead>Location</TableHead>
      <TableHead>By</TableHead>
      <TableHead>Reference</TableHead>
      <TableHead>Notes</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    {data.movements.map((m, i) => (
      <TableRow key={`${m.event_type}-${m.occurred_at}-${i}`}>
        <TableCell>
          <Badge variant="outline">{m.event_type}</Badge>
        </TableCell>
        <TableCell className="text-muted-foreground">
          {new Date(m.occurred_at).toLocaleString()}
        </TableCell>
        <TableCell className="text-muted-foreground">
          {m.from_location_name && m.to_location_name
            ? `${m.from_location_name} → ${m.to_location_name}`
            : (m.to_location_name ?? m.from_location_name ?? "—")}
        </TableCell>
        <TableCell className="text-muted-foreground">
          {m.actor_name ?? "—"}
        </TableCell>
        <TableCell className="text-muted-foreground">
          {m.reference_label ?? (m.reference_kind ?? "—")}
        </TableCell>
        <TableCell className="text-muted-foreground">{m.notes ?? "—"}</TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/routes/_layout/search.tsx`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/_layout/search.tsx
git commit -m "feat(fr015): serial search History shows location, actor, and reference"
```

---

## Task 9: Full verification + mandatory review

**Files:** none (gates)

- [ ] **Step 1: Backend suite + type/lint**

Run: `cd backend && uv run pytest -q && uv run mypy app && uv run ruff check app`
Expected: all green.

- [ ] **Step 2: Frontend build + lint**

Run: `cd frontend && bun run build && bunx biome check src`
Expected: all green.

- [ ] **Step 3 (optional): E2E smoke**

Run: `cd frontend && bun run test` (Playwright) — verify the SKU search shows a Consumption section and serial search shows enriched columns. (Per project memory, the E2E suite manages its own DB reset.)

- [ ] **Step 4: Mandatory high-risk review (CLAUDE.md §5)**

Invoke `superpowers:requesting-code-review`, AND because this touches FIFO/ledger/cost reads, also dispatch `ecc:database-reviewer` and `ecc:security-reviewer` (Agent tool, model `opus`). Focus the security review on: staff payloads carry zero cost keys (the redaction lock); admin/staff union serialization can't leak; no new N+1 under the 200-row cap.

- [ ] **Step 5: Address review findings, then ship**

Apply fixes, re-run Steps 1–2, then use `create-pr` to open a scoped PR into `dev` (never `master`/`production`). Title: `feat(fr015): comprehensive consumption history`.

---

## Self-Review

- **Spec coverage:** §2 SKU consumption → Tasks 2,4,7; §3 serial enrichment → Tasks 3,8; §4 role tiering → Tasks 1,2,4 + lock Task 5; §5 schemas → Task 1; §6 crud/N+1 → Tasks 2,3; §7 bounds (200, ordered) → Task 2 `_CONSUMPTION_LIMIT`; §8 frontend → Tasks 6,7,8; §9 testing → Tasks 2,3,4,5,9. All covered.
- **Placeholder scan:** no TBD/TODO; every code step carries full code.
- **Type consistency:** `search_sku(session, sku, is_admin)` signature consistent across crud (Task 2) and route (Task 4); `SkuSearchAdminResult | SkuSearchResult` union ordering identical in route + serialization note; `_build_consumption_events`/`_resolve_counterparty`/`_build_serial_movements` names consistent between definition and call sites; frontend `consumptionLabel`/`data.consumption` consistent across Tasks 7.
