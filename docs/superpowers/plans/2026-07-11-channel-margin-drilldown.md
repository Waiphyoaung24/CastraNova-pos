# FR-013 Channel-Margin Drill-down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins re-slice the monthly channel-margin report by product, customer, or project — optionally scoped to one channel — as flat, reconciling tables on screen and in PDF/Excel.

**Architecture:** Generalize the fixed 3-row `ChannelMarginReport` into a `MarginBreakdownReport` (rows of `{key, label, revenue, cogs, margin}` + `group_by` + `channel`). A new `crud.margin_report(...)` computes revenue/COGS at line/movement grain and groups by the chosen dimension across all three channels (SALE / MAINTENANCE / PROJECT), so any grouping of a given month reconciles to the same total. Built additively (new function + models alongside the old) through Tasks 1–4, then the route/model/tests switch over and the old code is deleted in Task 5.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy (psycopg3, Postgres), Pydantic v2, pytest; React + TanStack Query/Router, shadcn/ui (`Tabs`, `Select`), Playwright; `@hey-api/openapi-ts` generated SDK.

## Global Constraints

- **All DB access through `crud.py`** — routes never run `session.exec` directly (CLAUDE.md).
- **Read-only aggregation — NO Alembic migration** (no schema change).
- **Money:** Postgres `NUMERIC(…, 2)`; sums quantized to cents with the existing `_q()` (`ROUND_HALF_UP`). API returns decimal strings; the frontend parses at the display edge with `Number(...)`.
- **Admin-only:** the `reports` router already depends on `get_admin`; revenue/COGS stay redacted from staff. Do not change auth.
- **High-risk (financial aggregation):** stages 3–5 mandatory; the Review stage must add `ecc:database-reviewer` + `ecc:security-reviewer` (CLAUDE.md §5). The **reconciliation invariant** (below) is the primary correctness property.
- **Reconciliation invariant:** for any fixed `(month, channel-filter)`, `Σ rows` is identical across `group_by ∈ {channel, product, customer, project}` and equals the pre-change `channel_margin_report` totals for that slice.
- **Never hand-edit** `frontend/src/client/**` or `routeTree.gen.ts` — regenerate with `bun run generate-client`.
- **Strict mypy** — annotate everything. **biome** for TS format/lint.
- **Commit** after each task's tests pass. End messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- `backend/app/models.py` — add `MarginDimension`, `MarginBreakdownRow`, `MarginBreakdownReport` (Task 1); delete `ChannelMarginRow`/`ChannelMarginReport` (Task 5). `MoneyTHB` alias already exists (models.py:1526).
- `backend/app/crud.py` — add `margin_report(...)` + private per-dimension row builders + `_month_window()` helper (Tasks 1–4); delete `channel_margin_report` (Task 5).
- `backend/app/api/routes/reports.py` — add `group_by`/`channel` params + generalize `_channel_margin_table` + switch to new model (Task 5).
- `backend/tests/api/routes/test_margin_report.py` — **new** crud-level suite for the reconciliation invariant and per-dimension hand-calcs (Tasks 1–4).
- `backend/tests/api/routes/test_reports.py`, `test_report_exports.py`, `test_staff_redaction_lock.py` — adapt to the new `rows`/`label` shape + add HTTP dimension tests (Task 5).
- `frontend/src/routes/_layout/channel-margin.tsx` — Group-by + Channel controls, query, table, exports (Task 6).
- `frontend/src/lib/reports.ts` + `frontend/tests/reports.spec.ts` — export-helper signature + unit tests (Task 6).
- `frontend/src/client/**` — regenerated (Tasks 5–6).
- `frontend/tests/channel-margin-drilldown.spec.ts` — **new** Playwright E2E (Task 7).

Reuse the existing `test_reports.py` seed harness: the `seed` fixture (`test_reports.py:51`) builds a customer, supplier, one SERIALIZED product, and per-channel QUANTITY parts; `make_part(retail, repair, batches)` / `make_unit(cost)` create stock; `_pin_sale/_pin_ticket/_pin_pull(db, id, when)` pin records into the reporting window. `TARGET = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)`.

---

### Task 1: New models + `margin_report` with channel parity

Introduce the generalized model and CRUD **additively** (old code untouched), implementing only the `channel` dimension so it reproduces today's report exactly. Everything stays green.

**Files:**
- Modify: `backend/app/models.py` (after `NotificationPreferencesUpdate`, near the existing FR-013 block ~models.py:1523)
- Modify: `backend/app/crud.py` (new code near the existing `channel_margin_report`, ~crud.py:2920; add imports to the `app.models` import block)
- Test: `backend/tests/api/routes/test_margin_report.py` (new)

**Interfaces:**
- Produces:
  - `MarginDimension(str, enum.Enum)` with members `CHANNEL="channel"`, `PRODUCT="product"`, `CUSTOMER="customer"`, `PROJECT="project"`.
  - `MarginBreakdownRow(SQLModel)`: `key: str`, `label: str`, `revenue_thb: MoneyTHB`, `cogs_thb: MoneyTHB`, `margin_thb: MoneyTHB`.
  - `MarginBreakdownReport(SQLModel)`: `month: str`, `group_by: MarginDimension`, `channel: Channel | None`, `rows: list[MarginBreakdownRow]`, `total_revenue_thb: MoneyTHB`, `total_cogs_thb: MoneyTHB`, `total_margin_thb: MoneyTHB`.
  - `crud.margin_report(*, session: Session, year: int, month: int, group_by: MarginDimension = MarginDimension.CHANNEL, channel: Channel | None = None) -> MarginBreakdownReport`.
  - `crud._month_window(year: int, month: int) -> tuple[datetime, datetime]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/routes/test_margin_report.py`:

```python
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlmodel import Session

from app import crud
from app.models import Channel, MarginDimension
from tests.api.routes.test_reports import (  # reuse the multi-channel harness
    TARGET,
    _pin_pull,
    _pin_sale,
    _pin_ticket,
    seed,  # noqa: F401  (pytest fixture)
)


def _totals(report):
    return (report.total_revenue_thb, report.total_cogs_thb, report.total_margin_thb)


def test_channel_grouping_matches_legacy_report(db: Session, seed) -> None:
    """margin_report(group_by=CHANNEL) equals the legacy channel_margin_report."""
    legacy = crud.channel_margin_report(session=db, year=2099, month=2)  # empty month
    new = crud.margin_report(
        session=db, year=2099, month=2, group_by=MarginDimension.CHANNEL
    )
    # Always three channel rows, fixed order, even for an empty month.
    assert [r.key for r in new.rows] == [
        Channel.SALE.value,
        Channel.MAINTENANCE.value,
        Channel.PROJECT.value,
    ]
    assert _totals(new) == (
        legacy.total_revenue_thb,
        legacy.total_cogs_thb,
        legacy.total_margin_thb,
    )
    for legacy_row, new_row in zip(legacy.channels, new.rows):
        assert new_row.label == legacy_row.channel.value
        assert new_row.revenue_thb == legacy_row.revenue_thb
        assert new_row.cogs_thb == legacy_row.cogs_thb
        assert new_row.margin_thb == legacy_row.margin_thb


def test_channel_filter_returns_single_channel(db: Session, seed) -> None:
    report = crud.margin_report(
        session=db,
        year=2099,
        month=2,
        group_by=MarginDimension.CHANNEL,
        channel=Channel.SALE,
    )
    assert [r.key for r in report.rows] == [Channel.SALE.value]
    assert report.channel == Channel.SALE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -v`
Expected: FAIL — `ImportError: cannot import name 'MarginDimension'` (and `crud.margin_report` missing).

- [ ] **Step 3: Add the models**

In `backend/app/models.py`, immediately below the existing `ChannelMarginReport` block (~models.py:1541), add:

```python
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
```

(`enum` and `MoneyTHB` are already imported/defined in models.py.)

- [ ] **Step 4: Add the CRUD (channel dimension only)**

In `backend/app/crud.py`, add `MarginBreakdownReport`, `MarginBreakdownRow`, `MarginDimension` to the `from app.models import (...)` block. Then, just above `channel_margin_report` (~crud.py:2920), add the window helper and the new function. Reuse the existing channel aggregation bodies from `channel_margin_report` (crud.py:2946–3008) verbatim inside `_channel_rows`.

```python
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
    # SALE / MAINTENANCE / PROJECT aggregations: copy the three query blocks
    # from channel_margin_report (crud.py:2946-3003) unchanged, producing
    # sale_rev/sale_cogs, maint_rev/maint_cogs, proj_part_cogs/proj_unit_cogs.
    ...  # <-- paste the existing three aggregation blocks here verbatim
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
    else:  # dimensions added in later tasks
        raise NotImplementedError(group_by)
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
```

Leave `channel_margin_report` in place (deleted in Task 5). Optionally have it delegate is **not** required — keep it independent so the parity test compares two implementations.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -v`
Expected: PASS (2 tests). Then `uv run mypy app/crud.py app/models.py` — no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/tests/api/routes/test_margin_report.py
git commit -m "feat(reports): MarginBreakdownReport + margin_report channel parity (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Product dimension

Group the same month by product across all three channels. SALE uses `SaleLine` (revenue `qty*unit_price_thb`, COGS `qty*unit_cost_thb`); serialized sale lines carry `unit_id` not `product_id`, so recover the product via `Unit`. MAINTENANCE revenue from `ServiceTicketPart`, COGS from `CostLine→PartMovement(MAINTENANCE_OUT)`. PROJECT COGS from part `CostLine` + unit `purchase_cost_thb`, revenue 0.

**Files:**
- Modify: `backend/app/crud.py` (add `_product_rows`, wire into `margin_report`)
- Test: `backend/tests/api/routes/test_margin_report.py`

**Interfaces:**
- Consumes: `_month_window`, `_q`, `MarginBreakdownRow` (Task 1).
- Produces: `crud._product_rows(session, start, end, channel) -> list[MarginBreakdownRow]` (module-private; tested via `margin_report`).

- [ ] **Step 1: Write the failing test**

Append to `test_margin_report.py`:

```python
def _seed_full_month(db, seed) -> None:
    """One SALE (serialized unit + a part), one MAINTENANCE ticket part, and one
    PROJECT pull (unit + part), all pinned into 2026-03. Mirrors
    test_reports.test_mixed_channel_hand_calc so totals are hand-checkable."""
    from app.models import (
        ProjectCreate, ProjectPullCreate, ProjectPullFulfillLine,
        ProjectPullLineCreate, SaleLineInput, SaleLineKind,
    )
    admin, customer = seed["admin"], seed["customer"]
    # --- SALE ---
    sale_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    sale_barcode = seed["make_unit"]("100.00")
    sale = crud.create_sale(
        session=db, customer_id=customer.id, created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=sale_barcode),
            SaleLineInput(line_kind=SaleLineKind.PART, sku=sale_part.sku, quantity=5),
        ],
    )
    _pin_sale(db, sale.id, TARGET)
    db.commit()
```

(Add MAINTENANCE + PROJECT setup mirroring `test_reports.py:179-235`; capture nothing further — the test asserts on totals.)

```python
def test_product_grouping_reconciles_to_channel(db: Session, seed) -> None:
    _seed_full_month(db, seed)
    by_channel = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.CHANNEL
    )
    by_product = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.PRODUCT
    )
    # Reconciliation invariant: same month, same totals, different grouping.
    assert _totals(by_product) == _totals(by_channel)
    # Rows sum to the report totals.
    assert sum((r.revenue_thb for r in by_product.rows), Decimal("0.00")) == (
        by_product.total_revenue_thb
    )
    # Sorted revenue-desc.
    revs = [r.revenue_thb for r in by_product.rows]
    assert revs == sorted(revs, reverse=True)


def test_product_grouping_scoped_to_sale_channel(db: Session, seed) -> None:
    _seed_full_month(db, seed)
    sale_only = crud.margin_report(
        session=db, year=2026, month=3,
        group_by=MarginDimension.PRODUCT, channel=Channel.SALE,
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.CHANNEL,
        channel=Channel.SALE,
    )
    assert _totals(sale_only) == _totals(by_channel)
    # SALE has exactly two products: the serialized unit + the quantity part.
    assert len(sale_only.rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -k product -v`
Expected: FAIL — `NotImplementedError: MarginDimension.PRODUCT`.

- [ ] **Step 3: Implement `_product_rows` and wire it in**

Add to `crud.py`. Build three `dict[uuid.UUID, [rev, cogs]]` accumulators (one per channel) keyed by `product_id`, merge, attach labels, sort. Add any missing names (`Sale`, `SaleLine`, `Unit`, `ServiceTicket`, `ServiceTicketPart`, `ProjectPull`, `UnitMovement`) to the models import block if absent.

```python
def _merge(acc: dict[uuid.UUID, list[Decimal]], key: uuid.UUID, rev: Decimal, cogs: Decimal) -> None:
    slot = acc.setdefault(key, [Decimal("0"), Decimal("0")])
    slot[0] += rev
    slot[1] += cogs


def _product_rows(
    session: Session, start: datetime, end: datetime, channel: Channel | None
) -> list[MarginBreakdownRow]:
    acc: dict[uuid.UUID, list[Decimal]] = {}

    if channel in (None, Channel.SALE):
        # SALE product = COALESCE(SaleLine.product_id, Unit.product_id).
        pid = func.coalesce(SaleLine.product_id, Unit.product_id)
        for product_id, rev, cogs in session.exec(
            select(
                pid,
                func.coalesce(func.sum(SaleLine.quantity * SaleLine.unit_price_thb), Decimal("0")),
                func.coalesce(func.sum(SaleLine.quantity * SaleLine.unit_cost_thb), Decimal("0")),
            )
            .join(Sale, col(SaleLine.sale_id) == col(Sale.id))
            .join(Unit, col(SaleLine.unit_id) == col(Unit.id), isouter=True)
            .where(col(Sale.sold_at) >= start, col(Sale.sold_at) < end)
            .group_by(pid)
        ).all():
            _merge(acc, product_id, rev, cogs)

    if channel in (None, Channel.MAINTENANCE):
        # revenue by ServiceTicketPart.product_id
        for product_id, rev in session.exec(
            select(
                ServiceTicketPart.product_id,
                func.coalesce(func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb), Decimal("0")),
            )
            .join(ServiceTicket, col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id))
            .where(col(ServiceTicket.closed_at) >= start, col(ServiceTicket.closed_at) < end)
            .group_by(ServiceTicketPart.product_id)
        ).all():
            _merge(acc, product_id, rev, Decimal("0"))
        # COGS by PartMovement.product_id (MAINTENANCE_OUT)
        for product_id, cogs in session.exec(
            select(
                PartMovement.product_id,
                func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")),
            )
            .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
            .join(ServiceTicket, col(PartMovement.service_ticket_id) == col(ServiceTicket.id))
            .where(
                PartMovement.event_type == MovementType.MAINTENANCE_OUT,
                col(ServiceTicket.closed_at) >= start,
                col(ServiceTicket.closed_at) < end,
            )
            .group_by(PartMovement.product_id)
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
            .group_by(PartMovement.product_id)
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
            .group_by(Unit.product_id)
        ).all():
            _merge(acc, product_id, Decimal("0"), cogs)

    labels = _product_labels(session, list(acc))
    return _sorted_rows(
        (str(pid), labels[pid], _q(rev), _q(cogs)) for pid, (rev, cogs) in acc.items()
    )
```

Add label + sort helpers (reused by Tasks 3–4):

```python
def _product_labels(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        p.id: f"{p.sku} — {p.model_name}"
        for p in session.exec(select(Product).where(col(Product.id).in_(ids))).all()
    }


def _sorted_rows(
    triples: "Iterable[tuple[str, str, Decimal, Decimal]]",
) -> list[MarginBreakdownRow]:
    rows = [
        MarginBreakdownRow(
            key=key, label=label, revenue_thb=rev, cogs_thb=cogs, margin_thb=rev - cogs
        )
        for key, label, rev, cogs in triples
    ]
    rows.sort(key=lambda r: (-r.revenue_thb, -r.margin_thb, r.label))
    return rows
```

(`Iterable` is already imported via `collections.abc.Callable` line — add `Iterable` there.)

Wire into `margin_report`: replace the `PRODUCT` branch of the `NotImplementedError` with `rows = _product_rows(session, start, end, channel)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -v`
Expected: PASS (all product + Task-1 tests). Then `uv run mypy app/crud.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_margin_report.py
git commit -m "feat(reports): product-dimension grouping for margin_report (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Customer dimension

Group by customer. SALE→`Sale.customer_id` (non-null; every sale has a customer), MAINTENANCE→`ServiceTicket.customer_id`, PROJECT→`ProjectPull.customer_id`. No walk-in/None bucket needed.

**Files:**
- Modify: `backend/app/crud.py` (add `_customer_rows`, `_customer_labels`, wire in)
- Test: `backend/tests/api/routes/test_margin_report.py`

**Interfaces:**
- Consumes: `_merge`, `_sorted_rows`, `_month_window` (Task 2).
- Produces: `crud._customer_rows(session, start, end, channel) -> list[MarginBreakdownRow]`.

- [ ] **Step 1: Write the failing test**

```python
def test_customer_grouping_reconciles_and_labels(db: Session, seed) -> None:
    _seed_full_month(db, seed)
    by_customer = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.CUSTOMER
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.CHANNEL
    )
    assert _totals(by_customer) == _totals(by_channel)
    # All activity in the seed belongs to the one seeded customer.
    assert len(by_customer.rows) == 1
    assert by_customer.rows[0].label == "Report Cust"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -k customer -v`
Expected: FAIL — `NotImplementedError: MarginDimension.CUSTOMER`.

- [ ] **Step 3: Implement `_customer_rows`**

```python
def _customer_labels(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        c.id: c.name
        for c in session.exec(select(Customer).where(col(Customer.id).in_(ids))).all()
    }


def _customer_rows(
    session: Session, start: datetime, end: datetime, channel: Channel | None
) -> list[MarginBreakdownRow]:
    acc: dict[uuid.UUID, list[Decimal]] = {}

    if channel in (None, Channel.SALE):
        for cust_id, rev, cogs in session.exec(
            select(
                Sale.customer_id,
                func.coalesce(func.sum(SaleLine.quantity * SaleLine.unit_price_thb), Decimal("0")),
                func.coalesce(func.sum(SaleLine.quantity * SaleLine.unit_cost_thb), Decimal("0")),
            )
            .join(SaleLine, col(SaleLine.sale_id) == col(Sale.id))
            .where(col(Sale.sold_at) >= start, col(Sale.sold_at) < end)
            .group_by(Sale.customer_id)
        ).all():
            _merge(acc, cust_id, rev, cogs)

    if channel in (None, Channel.MAINTENANCE):
        for cust_id, rev in session.exec(
            select(
                ServiceTicket.customer_id,
                func.coalesce(func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb), Decimal("0")),
            )
            .join(ServiceTicketPart, col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id))
            .where(col(ServiceTicket.closed_at) >= start, col(ServiceTicket.closed_at) < end)
            .group_by(ServiceTicket.customer_id)
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
            .group_by(ServiceTicket.customer_id)
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
            .group_by(ProjectPull.customer_id)
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
            .group_by(ProjectPull.customer_id)
        ).all():
            _merge(acc, cust_id, Decimal("0"), cogs)

    labels = _customer_labels(session, list(acc))
    return _sorted_rows(
        (str(cid), labels[cid], _q(rev), _q(cogs)) for cid, (rev, cogs) in acc.items()
    )
```

Wire `CUSTOMER` into `margin_report`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -v` then `uv run mypy app/crud.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_margin_report.py
git commit -m "feat(reports): customer-dimension grouping for margin_report (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Project dimension + `(not project work)` bucket

Only PROJECT pulls carry a project. When `channel=None`, SALE + MAINTENANCE money lands in one `(not project work)` bucket (`key=""`) so totals still reconcile; when `channel=PROJECT`, that bucket is absent.

**Files:**
- Modify: `backend/app/crud.py` (add `_project_rows`, `_project_labels`, wire in)
- Test: `backend/tests/api/routes/test_margin_report.py`

**Interfaces:**
- Consumes: `_channel_rows` (to compute the non-project remainder), `_merge`, `_sorted_rows`.
- Produces: `crud._project_rows(session, start, end, channel) -> list[MarginBreakdownRow]`.

- [ ] **Step 1: Write the failing test**

```python
def test_project_grouping_all_channels_has_bucket(db: Session, seed) -> None:
    _seed_full_month(db, seed)
    by_project = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.PROJECT
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=3, group_by=MarginDimension.CHANNEL
    )
    assert _totals(by_project) == _totals(by_channel)
    labels = {r.label for r in by_project.rows}
    assert "(not project work)" in labels  # SALE + MAINTENANCE remainder
    bucket = next(r for r in by_project.rows if r.key == "")
    # The bucket equals SALE + MAINTENANCE margin.
    sale = next(r for r in by_channel.rows if r.key == Channel.SALE.value)
    maint = next(r for r in by_channel.rows if r.key == Channel.MAINTENANCE.value)
    assert bucket.margin_thb == sale.margin_thb + maint.margin_thb


def test_project_grouping_scoped_to_project_has_no_bucket(db: Session, seed) -> None:
    _seed_full_month(db, seed)
    scoped = crud.margin_report(
        session=db, year=2026, month=3,
        group_by=MarginDimension.PROJECT, channel=Channel.PROJECT,
    )
    assert all(r.key != "" for r in scoped.rows)
    assert len(scoped.rows) == 1  # the single seeded project
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -k project -v`
Expected: FAIL — `NotImplementedError: MarginDimension.PROJECT`.

- [ ] **Step 3: Implement `_project_rows`**

```python
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
            .group_by(ProjectPull.project_id)
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
            .group_by(ProjectPull.project_id)
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
            r for r in _channel_rows(session, start, end, None)
            if r.key in (Channel.SALE.value, Channel.MAINTENANCE.value)
        ]
        rev = sum((r.revenue_thb for r in remainder), Decimal("0.00"))
        cogs = sum((r.cogs_thb for r in remainder), Decimal("0.00"))
        if rev or cogs:
            rows.append(
                MarginBreakdownRow(
                    key="", label="(not project work)",
                    revenue_thb=_q(rev), cogs_thb=_q(cogs), margin_thb=_q(rev - cogs),
                )
            )
    return rows
```

Wire `PROJECT` into `margin_report`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/routes/test_margin_report.py -v` then `uv run mypy app/crud.py`
Expected: PASS (full crud suite).

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_margin_report.py
git commit -m "feat(reports): project-dimension grouping + non-project bucket (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Route params, export generalization, model swap, SDK regen

Expose the drill-down over HTTP, delete the legacy model/function, adapt the existing route/export/redaction tests, regenerate the SDK.

**Files:**
- Modify: `backend/app/api/routes/reports.py` (params + `_channel_margin_table` + imports)
- Modify: `backend/app/crud.py` (delete `channel_margin_report`), `backend/app/models.py` (delete `ChannelMarginRow`/`ChannelMarginReport`; update crud import block)
- Modify: `backend/tests/api/routes/test_reports.py`, `test_report_exports.py`, `test_staff_redaction_lock.py`
- Regen: `frontend/src/client/**` via `bun run generate-client`

**Interfaces:**
- Consumes: `crud.margin_report`, `MarginBreakdownReport`, `MarginDimension`, `Channel`.
- Produces: `GET /reports/channel-margin[.pdf|.xlsx]?month=&group_by=&channel=` returning `MarginBreakdownReport`; `reports._channel_margin_table(report: MarginBreakdownReport) -> tuple[str, list[str], list[list[str]]]`.

- [ ] **Step 1: Update the route tests first (they define the new HTTP contract)**

In `test_reports.py`: replace the `_channel(report, name)` helper and the two existing tests to read `report["rows"]` with `row["key"]`/`row["label"]`. Add new HTTP tests:

```python
def test_http_reconciles_across_groupings(client, superuser_token_headers, db, seed):
    _seed_full_month(db, seed)  # import from test_margin_report
    def total(gb):
        r = client.get(
            f"{PREFIX}/reports/channel-margin?month=2026-03&group_by={gb}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        return r.json()["total_margin_thb"]
    base = total("channel")
    for gb in ("product", "customer", "project"):
        assert total(gb) == base


def test_http_channel_filter_scopes_rows(client, superuser_token_headers, db, seed):
    _seed_full_month(db, seed)
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-03&group_by=product&channel=SALE",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 2


def test_http_rejects_bad_group_by(client, superuser_token_headers):
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-03&group_by=bogus",
        headers=superuser_token_headers,
    )
    assert r.status_code == 422
```

In `test_report_exports.py` and `test_staff_redaction_lock.py`: update any `channels`/`channel` field references to `rows`/`label` (grep for `"channels"` and `channel_margin`).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/api/routes/test_reports.py tests/api/routes/test_report_exports.py -v`
Expected: FAIL (route still returns legacy model; `group_by` param unknown).

- [ ] **Step 3: Update the route**

In `reports.py`: import `MarginBreakdownReport`, `MarginDimension`, `Channel`; drop `ChannelMarginReport`. Generalize the table builder and add params to all three channel-margin routes:

```python
_DIM_HEADER = {
    MarginDimension.CHANNEL: "Channel",
    MarginDimension.PRODUCT: "Product",
    MarginDimension.CUSTOMER: "Customer",
    MarginDimension.PROJECT: "Project",
}


def _channel_margin_table(
    report: MarginBreakdownReport,
) -> tuple[str, list[str], list[list[str]]]:
    first = _DIM_HEADER[report.group_by]
    headers = [first, "Revenue (THB)", "COGS (THB)", "Margin (THB)"]
    rows = [
        [r.label, str(r.revenue_thb), str(r.cogs_thb), str(r.margin_thb)]
        for r in report.rows
    ]
    rows.append(
        ["TOTAL", str(report.total_revenue_thb), str(report.total_cogs_thb), str(report.total_margin_thb)]
    )
    scope = f" — {report.channel.value}" if report.channel else ""
    title = f"Channel Margin — {report.month} — by {first}{scope}"
    return title, headers, rows


@router.get("/channel-margin", response_model=MarginBreakdownReport)
def channel_margin(
    *,
    session: SessionDep,
    month: _Month,
    group_by: MarginDimension = MarginDimension.CHANNEL,
    channel: Channel | None = None,
) -> MarginBreakdownReport:
    """Monthly revenue/COGS/margin grouped by ``group_by`` (channel default),
    optionally scoped to one ``channel``; admin-only (FR-013, spec §8)."""
    return crud.margin_report(
        session=session, year=int(month[:4]), month=int(month[5:7]),
        group_by=group_by, channel=channel,
    )
```

Give `.pdf`/`.xlsx` the same `group_by`/`channel` params, call `crud.margin_report(...)`, and fold the dimension/channel into the filename, e.g.:

```python
suffix = f"-by-{group_by.value}" + (f"-{channel.value}" if channel else "")
filename=f"channel-margin-{month}{suffix}"
```

Then delete `crud.channel_margin_report` (crud.py:2930) and remove `ChannelMarginRow`/`ChannelMarginReport` from models.py and the crud import block. Update any lingering imports (the parity test in Task 1 referenced `crud.channel_margin_report` — change it to compare `margin_report(group_by=CHANNEL)` against hand values, or delete that single assertion; keep the reconciliation tests).

- [ ] **Step 4: Run backend tests + regen SDK**

Run:
```bash
cd backend && uv run pytest tests/api/routes/test_reports.py tests/api/routes/test_report_exports.py tests/api/routes/test_margin_report.py tests/api/test_staff_redaction_lock.py -v && uv run mypy app
cd ../frontend && bun run generate-client
```
Expected: backend PASS + clean mypy; SDK regenerated (`git diff --stat frontend/src/client` shows `channelMargin` gaining `group_by`/`channel` params and the `MarginBreakdownReport` type).

- [ ] **Step 5: Commit**

```bash
git add backend/app frontend/src/client backend/tests
git commit -m "feat(reports): expose margin drill-down params; drop legacy model (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Frontend controls, table, exports

Add **Group by** (`Tabs`) + **Channel** (`Select`) controls to the report screen; drive the query and export links from them; switch the table's first column with the dimension; show the channel revenue-mix bar only for the channel grouping.

**Files:**
- Modify: `frontend/src/routes/_layout/channel-margin.tsx`
- Modify: `frontend/src/lib/reports.ts`, `frontend/tests/reports.spec.ts`

**Interfaces:**
- Consumes: regenerated `ReportsService.channelMargin({ month, groupBy, channel })`, `MarginBreakdownReport` type, `Tabs`/`Select` from `@/components/ui`.
- Produces: `channelMarginExport(month, fmt, groupBy, channel?)` in `lib/reports.ts`.

- [ ] **Step 1: Update the export-helper test first**

In `frontend/tests/reports.spec.ts`, replace the `channelMarginExport` test:

```ts
test("channelMarginExport encodes group_by and optional channel", () => {
  expect(channelMarginExport("2026-03", "pdf", "channel")).toEqual({
    path: "/api/v1/reports/channel-margin.pdf?month=2026-03&group_by=channel",
    filename: "channel-margin-2026-03-by-channel.pdf",
  })
  expect(channelMarginExport("2026-03", "xlsx", "product", "SALE")).toEqual({
    path: "/api/v1/reports/channel-margin.xlsx?month=2026-03&group_by=product&channel=SALE",
    filename: "channel-margin-2026-03-by-product-SALE.xlsx",
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && bun run test tests/reports.spec.ts`
Expected: FAIL — `channelMarginExport` takes 2 args / wrong output.

- [ ] **Step 3: Update `lib/reports.ts`**

```ts
export type MarginGroupBy = "channel" | "product" | "customer" | "project"
export type MarginChannel = "SALE" | "MAINTENANCE" | "PROJECT"

export function channelMarginExport(
  month: string,
  fmt: ReportFormat,
  groupBy: MarginGroupBy,
  channel?: MarginChannel,
): ReportExport {
  const q = `month=${month}&group_by=${groupBy}${channel ? `&channel=${channel}` : ""}`
  const suffix = `-by-${groupBy}${channel ? `-${channel}` : ""}`
  return {
    path: `/api/v1/reports/channel-margin.${fmt}?${q}`,
    filename: `channel-margin-${month}${suffix}.${fmt}`,
  }
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && bun run test tests/reports.spec.ts`
Expected: PASS.

- [ ] **Step 5: Wire the controls into `channel-margin.tsx`**

- Add state: `const [groupBy, setGroupBy] = useState<MarginGroupBy>("channel")` and `const [channel, setChannel] = useState<MarginChannel | undefined>(undefined)`.
- Query key `["channel-margin", month, groupBy, channel ?? "all"]`; call `ReportsService.channelMargin({ month, groupBy, channel })`. Do the same for the prior-month query so deltas track the current view.
- Render a `Tabs` (values `channel|product|customer|project`) bound to `groupBy`, and a `Select` (`All`, `SALE`, `MAINTENANCE`, `PROJECT`) bound to `channel` (empty → `undefined`).
- The data rows come from `data?.rows ?? []`; the table/mobile card first column shows `row.label`; keep the total footer from `data.total_*`.
- Change the table's first `TableHead` from the literal "Channel" to a label derived from `groupBy` (`Channel`/`Product`/`Customer`/`Project`).
- Render the **"Revenue mix by channel"** `MetricBar` block **only when `groupBy === "channel"`** (share-of-channel is meaningless for other dimensions).
- `handleExport(fmt)` calls `channelMarginExport(month, fmt, groupBy, channel)`.
- `key` on rows becomes `row.key` (falls back fine for the `""` bucket).

- [ ] **Step 6: Verify build + typecheck + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/routes/_layout/channel-margin.tsx src/lib/reports.ts`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/_layout/channel-margin.tsx frontend/src/lib/reports.ts frontend/tests/reports.spec.ts
git commit -m "feat(reports): drill-down controls on channel-margin screen (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: E2E + review handoff

**Files:**
- Create: `frontend/tests/channel-margin-drilldown.spec.ts`

**Interfaces:**
- Consumes: the running dev stack; admin auth helper used by existing specs (mirror an existing admin-authed spec, e.g. `frontend/tests/reports.spec.ts` siblings that hit the app).

- [ ] **Step 1: Write the E2E**

Mirror an existing admin-authed Playwright spec. Assert: admin opens `/channel-margin`; default shows the 3-channel table + revenue-mix bar; switching **Group by → Product** re-renders a flat ranked table (first header cell reads "Product") whose total footer is unchanged; setting **Channel → SALE** narrows the rows and the mix bar is hidden; the Excel button's link carries `group_by=product&channel=SALE`. Staff (non-admin) is redirected away (existing `requireAdmin` guard).

- [ ] **Step 2: Run the E2E**

Run: `cd frontend && bun run test tests/channel-margin-drilldown.spec.ts`
Expected: PASS. (Bring the stack up per CLAUDE.md — `docker compose watch` — and ensure the DB is migrated to head first.)

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/channel-margin-drilldown.spec.ts
git commit -m "test(reports): E2E for channel-margin drill-down (FR-013)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Full suite + review**

Run: `cd backend && bash scripts/test.sh` (or `uv run pytest`) and `cd frontend && bun run test`.
Then run the Review stage (CLAUDE.md §5): `requesting-code-review` **plus** `ecc:database-reviewer` + `ecc:security-reviewer` (high-risk financial aggregation). Address findings, then use `create-pr` into `dev_wth`.

---

## Self-Review

**1. Spec coverage:**
- §2 pivot + channel filter → Tasks 5 (params) + 6 (controls). ✓
- §3 reconciliation invariant → primary assertions in Tasks 2–5. ✓
- §4 per-(channel×dimension) grouping incl. serialized `COALESCE(SaleLine.product_id, Unit.product_id)` → Tasks 2–4. ✓
- §5 API params + `MarginBreakdownReport` model + `margin_report` CRUD → Tasks 1, 5. ✓
- §5 sorting (revenue desc, margin desc, label) → `_sorted_rows` (Task 2); channel fixed order → `_channel_rows` (Task 1). ✓
- §6 frontend controls, conditional mix bar, exports → Task 6. ✓
- §7 export title/headers/filename per view → Task 5. ✓
- §9 tests: reconciliation, line-vs-snapshot (product test asserts SALE two-product split; add an explicit `Σ SaleLine == Sale.total_*` assertion in Task 2 Step 1 if desired), serialized attribution, channel scoping, `(not project work)` bucket, empty month (Task 1 uses 2099-02), export shape, frontend helper, E2E → Tasks 1–7. ✓
- §10 no migration → Global Constraints. ✓

**2. Placeholder scan:** The only intentional `...` is the "paste the existing three aggregation blocks verbatim" in Task 1 Step 4 — an explicit copy of known code (crud.py:2946–3008), not an undefined placeholder. No TBD/TODO elsewhere.

**3. Type consistency:** `margin_report`, `_channel_rows`, `_product_rows`, `_customer_rows`, `_project_rows`, `_merge`, `_sorted_rows`, `_month_window`, `_product_labels`/`_customer_labels`/`_project_labels` used consistently across tasks. `MarginBreakdownRow` fields (`key`, `label`, `revenue_thb`, `cogs_thb`, `margin_thb`) and `MarginBreakdownReport` fields match models and route/frontend consumers. `channelMarginExport(month, fmt, groupBy, channel?)` signature matches its test and caller.
