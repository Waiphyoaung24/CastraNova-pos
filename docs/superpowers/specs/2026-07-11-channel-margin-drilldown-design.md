# FR-013 Channel-Margin Drill-down — Design

**Date:** 2026-07-11
**Status:** Approved (interaction model); pending spec review
**Requirement:** FR-013 (Monthly Channel Margin Report) — the *"Drill-down by product, customer, or project"* clause, currently unimplemented. See gap note in `notes.md` and spec §8 (`docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md:289`: "Drill-down filters add product/customer/project joins").

## 1. Goal

Today `/reports/channel-margin` returns a fixed 3-row summary (revenue / COGS / margin for SALE, MAINTENANCE, PROJECT). This design adds the ability to **re-slice the same month's money by a chosen dimension** (product, customer, or project) and to **scope the slice to one channel** — answering questions like *"which product earned the most margin this month?"* and *"which products did the SALE channel move?"* — without regressing the existing default view.

## 2. Interaction model — "pivot + channel filter"

The report screen keeps its current layout and gains **two controls**:

- **Group by:** `Channel` (default) · `Product` · `Customer` · `Project`
- **Channel:** `All` (default) · `SALE` · `MAINTENANCE` · `PROJECT`

The table is **always flat** — one row per group, sorted, with a reconciling total footer. No nested/expandable rows, no lazy fetch. Changing either control re-queries and re-renders the flat table.

- `Group by = Channel`, `Channel = All` → **byte-for-byte the current report** (3 channel rows + total). Nothing regresses.
- `Group by = Product`, `Channel = All` → one row per product across all channels, ranked.
- `Group by = Product`, `Channel = SALE` → one row per product, counting only its SALE contribution; footer reconciles to the SALE channel total.
- `Group by = Project`, `Channel = PROJECT` → clean per-project breakdown (the natural home of the project dimension).

**Why flat (vs. nested expand):** every view stays a plain table, so it drops straight into the existing PDF/XLSX export pipeline unchanged in shape, and each exported file is self-describing. The two orthogonal knobs answer every "X within Y" question by combination rather than one giant nested view.

## 3. The reconciliation invariant (the core correctness property)

**For any fixed `(month, channel-filter)`, the sum of all row values is identical regardless of `group_by`, and equals the corresponding slice of the existing report.**

Concretely, for `channel = All`:
```
Σ rows(by Channel)  ==  Σ rows(by Product)  ==  Σ rows(by Customer)  ==  Σ rows(by Project)  ==  month total
```
and each equals the totals the *current* `channel_margin_report` produces for that month. This is the invariant that makes the drill-down trustworthy, and it is the primary thing the tests assert (§9).

Consequence: when `group_by = Project` and `channel = All`, SALE and MAINTENANCE money (which has no project) is carried in a single **`(not project work)`** bucket so the total still reconciles. Scoping to `channel = PROJECT` removes that bucket and shows only real projects. (This is the single flat row the user accepted — not repeated per channel.)

## 4. Dimension → grouping key, per channel

Revenue/COGS are computed at **line/movement grain** (not the sale-level snapshots the current report uses) so they can be grouped. The grain sources:

| Channel | Revenue source | COGS source | Time window |
|---|---|---|---|
| SALE | `SaleLine.quantity * SaleLine.unit_price_thb` | `SaleLine.quantity * SaleLine.unit_cost_thb` (line snapshot) | `Sale.sold_at ∈ [start,end)` |
| MAINTENANCE | `ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb` | `Σ CostLine.total_cost_thb` via `PartMovement(MAINTENANCE_OUT) → ServiceTicket` | `ServiceTicket.closed_at ∈ [start,end)` |
| PROJECT | `0` (always — project pulls carry no revenue) | `Σ CostLine.total_cost_thb` via `PartMovement(PROJECT_OUT) → ProjectPull` **+** `Σ Unit.purchase_cost_thb` via `UnitMovement(PROJECT_OUT) → ProjectPull` | `ProjectPull.fulfilled_at ∈ [start,end)` |

Grouping key by dimension:

| Dimension | SALE | MAINTENANCE | PROJECT |
|---|---|---|---|
| **Product** | `COALESCE(SaleLine.product_id, Unit.product_id)` (serialized lines carry `unit_id`, not `product_id` — join `Unit` to recover the product) | `ServiceTicketPart.product_id` (revenue) / `PartMovement.product_id` (COGS) | `PartMovement.product_id` (parts) / `Unit.product_id` (units) |
| **Customer** | `Sale.customer_id` (NOT NULL — every sale has a customer) | `ServiceTicket.customer_id` | `ProjectPull.customer_id` (present directly on the pull) |
| **Project** | — → `(not project work)` bucket | — → `(not project work)` bucket | `ProjectPull.project_id` |

Notes:
- SALE COGS uses the **`SaleLine.unit_cost_thb` snapshot**, not a `CostLine` join. This is the recorded cost-of-sale at the grain we need and must reconcile to `Sale.total_cogs_thb` (asserted by a reconciliation test).
- MAINTENANCE revenue (from `ServiceTicketPart`) and COGS (from `CostLine`/`PartMovement`) are two separate aggregations **merged per group key** (both expose `product_id`; both reach `customer_id` via the ticket).
- PROJECT part-COGS and unit-COGS are two aggregations merged per group key.
- Because `Sale.customer_id` is non-nullable, the customer dimension needs **no walk-in/None bucket** — walk-in is a real customer row.

## 5. API surface

Extend the existing endpoints (no new paths):

```
GET /reports/channel-margin[.pdf|.xlsx]
    ?month=YYYY-MM
    &group_by=channel|product|customer|project   (default: channel)
    &channel=SALE|MAINTENANCE|PROJECT             (optional; omitted = all)
```

Admin-only (unchanged — the router already depends on `get_admin`; revenue/COGS stay redacted from staff).

### Response model (generalized)

The response generalizes from the fixed `ChannelMarginReport` to a breakdown that carries the same shape for every dimension:

```python
class MarginDimension(str, enum.Enum):
    CHANNEL = "channel"
    PRODUCT = "product"
    CUSTOMER = "customer"
    PROJECT = "project"

class MarginBreakdownRow(SQLModel):
    key: str          # group identity: channel name, or entity UUID as str, or "" for the (none) bucket
    label: str        # display: channel name / "SKU — model_name" / customer name / "code — name" / "(not project work)"
    revenue_thb: MoneyTHB
    cogs_thb: MoneyTHB
    margin_thb: MoneyTHB

class MarginBreakdownReport(SQLModel):
    month: str                       # "YYYY-MM"
    group_by: MarginDimension
    channel: Channel | None          # filter applied; null = all channels
    rows: list[MarginBreakdownRow]
    total_revenue_thb: MoneyTHB
    total_cogs_thb: MoneyTHB
    total_margin_thb: MoneyTHB
```

The current `ChannelMarginReport` / `ChannelMarginRow` are **replaced** by the above (the only consumer is this one screen + its exports). When `group_by = channel` the rows are the three channels in fixed order (`SALE, MAINTENANCE, PROJECT`), so the default view is unchanged in content.

**Ripple:** this changes the generated SDK (`bun run generate-client`) and requires updating `channel-margin.tsx`, `lib/reports.ts`, and the export table builders. All in scope.

### CRUD

Replace `crud.channel_margin_report(session, year, month)` with a generalized:

```python
def margin_report(*, session, year, month,
                  group_by: MarginDimension = MarginDimension.CHANNEL,
                  channel: Channel | None = None) -> MarginBreakdownReport
```

- Builds the per-channel `(group_key, revenue, cogs)` aggregations from §4, filtered to `channel` when set.
- Aggregates across channels by `group_key` (for non-channel dimensions), attaches labels via a single batched lookup (products/customers/projects by id), computes margins and totals.
- `group_by = channel` path returns the existing three-row result (keeps parity, and lets us assert new-vs-old equality in tests during the transition).
- Reuses `_q()` cent-quantization and the existing window math (`start`/`end`).

### Sorting

- `group_by = channel`: fixed order SALE, MAINTENANCE, PROJECT (unchanged).
- Other dimensions: `revenue_thb DESC, margin_thb DESC, label ASC`. (PROJECT-only views have zero revenue, so this naturally falls back to margin — most-negative/cost-heavy last; acceptable. A dedicated cost-desc sort is out of scope.)

## 6. Frontend

`frontend/src/routes/_layout/channel-margin.tsx`:
- Add the two controls (segmented **Group by** + **Channel** select) beside the existing month picker.
- Query key becomes `["channel-margin", month, groupBy, channel]`; call passes the new params.
- Table first-column header switches with the dimension (`Channel` / `Product` / `Customer` / `Project`); body renders `row.label`; footer unchanged (totals).
- **Revenue-mix bar** (`MetricBar` "Revenue mix by channel") renders **only when `group_by = channel`** (it's a channel-share visual). The four **StatCards** (Revenue / COGS / Margin / Margin %) and the month-over-month deltas stay for all views — totals are always defined; the prior-month comparison uses the same `(groupBy, channel)` params.
- Mobile card layout mirrors the table (label + revenue/COGS/margin/margin%).
- Export buttons pass the current `groupBy` + `channel` to the download path.

`frontend/src/lib/reports.ts`:
- `channelMarginExport(month, fmt, groupBy, channel)` appends `&group_by=…` (and `&channel=…` when set) and encodes them into the filename (e.g. `channel-margin-2026-03-by-product-SALE.xlsx`).

## 7. Exports

`reports.py` `_channel_margin_table` generalizes to take the `MarginBreakdownReport`:
- First header cell = dimension label; remaining columns unchanged (Revenue / COGS / Margin THB) + TOTAL row.
- Title reflects the view: `Channel Margin — 2026-03 — by Product — SALE`.
- Filenames carry `group_by`/`channel` (as above) so downloaded files are self-identifying.

## 8. Out of scope (YAGNI)

- No nested/expandable rows, no lazy per-row fetch.
- No cost-descending sort mode; no CSV.
- No sub-grouping (e.g. product-within-customer). A second knob combination covers the real questions.
- No change to how channels/COGS are *defined* — only how existing money is grouped.

## 9. Testing (high-risk — money/COGS aggregation)

Per CLAUDE.md this touches financial aggregation, so stages 3–5 are mandatory and the review must add `ecc:database-reviewer` + `ecc:security-reviewer`.

**Backend (pytest), TDD:**
1. **Reconciliation invariant (primary):** with a seeded month spanning all 3 channels, assert `Σ rows` is equal across `group_by ∈ {channel, product, customer, project}` for `channel = All`, and equals the pre-change `channel_margin_report` totals. Repeat per single-channel filter.
2. **SALE line-level == sale-level snapshot:** `Σ SaleLine` revenue/COGS for the month equals `Σ Sale.total_thb / total_cogs_thb` (guards the grain switch).
3. **Serialized vs. quantity product attribution:** a serialized SALE line (product via `Unit`) and a quantity line land under the correct product rows.
4. **Per-dimension correctness:** hand-computed expected rows for product / customer / project on a small fixture.
5. **Channel filter scoping:** `channel = SALE` excludes maintenance/project contributions; footer matches the SALE channel total.
6. **`(not project work)` bucket:** appears for `group_by = project, channel = All`; disappears for `channel = PROJECT`; totals reconcile both ways.
7. **Empty month:** zero rows, zero totals, margin% "—".
8. **Export shape:** PDF/XLSX table headers/rows per dimension.

**Frontend:** unit-test the export-path/filename helper for each `(groupBy, channel)`.

**E2E (Playwright, `ecc:e2e-runner`):** admin loads the report, flips Group by → Product, applies Channel = SALE, sees a ranked flat table with a reconciling total; exports respect the current view. Staff cannot reach the route (existing guard).

## 10. Files touched

- `backend/app/models.py` — add `MarginDimension`, `MarginBreakdownRow`, `MarginBreakdownReport`; remove `ChannelMarginRow`/`ChannelMarginReport`.
- `backend/app/crud.py` — replace `channel_margin_report` with `margin_report(...)`.
- `backend/app/api/routes/reports.py` — new query params on the 3 channel-margin routes; generalize `_channel_margin_table`.
- `backend/tests/api/routes/test_dashboards.py` (or a reports test module) — the suite in §9.
- `frontend/src/routes/_layout/channel-margin.tsx` — controls, query, table header, conditional mix bar, exports.
- `frontend/src/lib/reports.ts` + its spec — export helper signature.
- `frontend/src/client/*` — regenerated SDK (`bun run generate-client`; never hand-edited).

No DB migration (no schema change — read-only aggregation over existing tables).
