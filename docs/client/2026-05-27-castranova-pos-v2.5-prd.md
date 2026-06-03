# CastraNova POS — Product Requirements Document

**Version:** 2.5
**Date:** 2026-05-27
**Author:** K W G
**Status:** Locked — incorporates client feedback on v2.4 (FIFO costing, batch numbering, FR-008 warehouse-recording, FR-009 admin-only Project workflow, customer/project dashboard). Decision Log: D1 → D31.

> **Supersedes:** v2.4 (PDF dated 2026-05-25). v2.4 remains the previous client-locked artifact for audit reference.

---

## 1. Executive Summary

CastraNova POS is an inventory tracking and channel-margin reporting system for a B2B refrigeration trading business operating between **Bangkok HQ** (administration) and **Yangon** (warehouse + on-site service). Every machine and high-value spare part is tracked individually (one barcode per piece); commodity parts are tracked by SKU quantity with **FIFO cost layering** — each receipt creates a new purchase batch with its own cost, and consumption draws from the oldest batch first. Every consumption movement records its customer, channel (Sale / Maintenance / Project), and price — feeding a monthly per-channel revenue + margin report. The system works offline at the Yangon warehouse with idempotent sync on reconnect; **all inventory-out recording happens at the warehouse** (on-site mechanic visits do not require system access). Bangkok HQ maintains the catalog, prices, customers, projects, user accounts, and **initiates all Project-channel consumption via Project Pulls** that Yangon staff fulfill; Yangon executes physical receiving, sales, and maintenance.

---

## 2. Problem Statement

### Current state
- Bangkok HQ has no reliable view of Yangon stock or recent consumption.
- Inventory movements live in spreadsheets and memory; month-end reconciliation is slow and error-prone.
- The Yangon team loses time on paper-based receiving and handwritten service notes.
- Yangon's internet is unreliable; current digital tools fail when the connection drops.
- Channel mix (Sale / Maintenance / Project) and inventory holding period are invisible.

### Pain points
1. **No live stock visibility** at Yangon.
2. **No channel separation** in consumption tracking — sales, on-site maintenance, and projects blend together, hiding true margins.
3. **No defensible audit trail** for inventory movements or price changes.
4. **Yangon internet is unreliable** — current digital tools fail when the connection drops.
5. **Holding period for stock is unknown** — slow-movers are not identifiable.

### Business impact
- Month-end reporting takes days and is error-prone.
- Slow-moving stock ties up capital invisibly.
- Margin decisions are made on incomplete data.

---

## 3. Goals & Success Metrics

| Goal | Metric | Target | Measurement |
|---|---|---|---|
| Live stock visibility | Time to look up *"what's in YGN warehouse"* | < 10 seconds | Dashboard load |
| Channel-separated margin reporting | Monthly report ready by close of business Day 1 of next month | Day 1 | Report timestamp |
| Audit-grade inventory trail | % of movements with full audit fields (who/when/why) | 100% | DB check |
| Offline reliability (YGN warehouse) | Captured writes during an 8-hour internet outage at the warehouse | 100% | Manual outage test |
| Inventory holding period visibility | Slow-mover list in one click | Top-20 list available | Dashboard report |
| Reduction in stock-out incidents | Monthly stock-out incidents at YGN | Baseline captured from system data in month 1; reduction target set from month 2 onward | Monthly count from system data |

---

## 4. User Personas

### Bangkok Admin (HQ)
- **Role:** Bangkok HQ staff (~5 people).
- **Goals:** Maintain the product catalog and prices, manage suppliers, customers, and projects, **create Project Pulls** when inventory is deployed for a customer project, approve large pricing overrides, perform admin-only Stock Adjustments, review monthly reports and customer/project history dashboards.
- **Pain points:** No timely visibility into Yangon stock; manual month-end reconciliation; no clean way to record project consumption separately from sales.
- **Technical proficiency:** Medium — comfortable with web apps and spreadsheets.
- **Usage context:** Daily, on desktop/laptop at the Bangkok office, reliable internet.

### Yangon Staff (Receiving, Sales, Maintenance, Pull Fulfillment)
- **Role:** Unified Yangon team (~5 people). The same people handle warehouse receiving, customer sales, on-site service jobs (off-system), and fulfillment of admin-created Project Pulls.
- **Goals:** Receive incoming shipments, label new stock, process customer sales at the warehouse, record parts consumed for maintenance jobs at the warehouse terminal, fulfill Project Pulls created by Bangkok admin.
- **Pain points:** Slow paper-based receiving; no easy way to check stock; warehouse wifi is patchy.
- **Technical proficiency:** Low–Medium — phone-first users at the warehouse.
- **Usage context:** Multiple times per day at the YGN warehouse barcode terminal. On-site customer visits are off-system — mechanics list needed parts on paper/LINE and warehouse staff process them on return.

---

## 5. Functional Requirements

Features are grouped by area and prioritized as **P0** (must have for launch), **P1** (important for first version), **P2** (nice to have, can wait).

---

### Catalog & Master Data

#### FR-001: Product Catalog
**Description:** Bangkok admin maintains the master list of all products — refrigeration machines, high-value spare parts (compressors, motors), and commodity spare parts (filters, fittings, refrigerants).

**User story:** As a Bangkok admin, I want one place to add, edit, and categorize every product so that Yangon staff can scan and sell consistent items.

**Acceptance criteria:**
- [ ] Each product has a unique SKU, model name, brand, category, and **tracking mode** — `SERIALIZED` (every piece tracked individually) or `QUANTITY` (SKU stock counter with FIFO batches).
- [ ] Each product category carries a **default tracking mode**; Bangkok admin can override per product when creating or editing.
- [ ] Initial catalog is imported from the existing product list the client will provide.
- [ ] Products can be deactivated by Bangkok admin (no hard delete — preserves history).

**Priority:** P0

---

#### FR-002: Per-Product Pricing (FIFO cost basis)
**Description:** Each product carries a **purchase cost basis**, a **retail price** (Sale channel), and a **repair price** (Maintenance channel). Project consumption uses cost only — revenue is 0. For QUANTITY-tracked products, the effective purchase cost at any moment is the cost of the **oldest non-depleted batch** (FIFO). When a single consumption spans a batch boundary — for example, a sale of 5 units while the oldest batch has only 3 remaining — the cost **splits proportionally across batches**: 3 units at the old batch's cost + 2 units at the new batch's cost. This is accountancy-standard FIFO (option (a)), explicitly chosen over (b) charging the whole sale at the old batch's price or (c) blocking sales that span batches. For SERIALIZED products, purchase cost is captured per piece at receipt.

**User story:** As a Bangkok admin, I want distinct retail and repair prices for every product, and I want the cost basis of commodity parts to honour the order they entered stock, so that monthly margin reports reflect the real economics.

**Acceptance criteria:**
- [ ] Retail price and repair price both editable by Bangkok admin.
- [ ] Every price change is recorded permanently — auditors can answer *"what was the price of part X on a given date?"*
- [ ] For QUANTITY-tracked products, **no single "purchase cost" column on the product** — cost is derived from the oldest non-depleted `part_batch` row. The dashboard displays "current FIFO cost = oldest batch's cost."
- [ ] **Batch succession is automatic.** When the oldest batch reaches `remaining_qty = 0`, it is marked depleted, and the next batch in receipt order automatically becomes the effective purchase cost. This succession is a derived value — **no `price_change` record is created for it**, because the per-batch costs themselves are immutable; only the *active* batch changes.
- [ ] **Mid-consumption splits produce multiple cost lines.** A single consumption row that spans two or more batches generates one `cost_line` row per batch consumed (referencing each batch's `id` and the quantity drawn). The customer-facing receipt shows the line at its sale price; the internal margin record carries the split for accurate COGS.
- [ ] For SERIALIZED products, purchase cost is captured per piece at receipt.
- [ ] Yangon staff cannot edit prices; they can only override per-transaction via FR-010.

**Priority:** P0

---

#### FR-003: Suppliers, Customers, Projects
**Description:** Bangkok admin maintains the authoritative lists of suppliers, customers (Dealer or End Customer), and projects (each with code, name, customer, dates, optional budget).

**User story:** As a Bangkok admin, I want to maintain authoritative lists so that every transaction can be tagged correctly.

**Acceptance criteria:**
- [ ] Customer record stores name, country, contact, type (Dealer / End Customer).
- [ ] Project record stores code, name, customer link, start/end dates, status, optional budget.
- [ ] Yangon staff can read these lists and link transactions to them, but cannot create or edit them.

**Priority:** P0

---

#### FR-004: User & Role Management
**Description:** The system supports two roles: **Bangkok admin** and **Yangon staff**.

**User story:** As a Bangkok admin, I want to add new staff and assign them the correct role.

**Acceptance criteria:**
- [ ] Bangkok admin can create, edit, and deactivate user accounts.
- [ ] **Bangkok admin role:** catalog, pricing, suppliers, customers, projects, **Project Pull creation**, override approvals, Stock Adjustment, user management, full customer/project dashboards.
- [ ] **Yangon staff role:** receiving, sales, on-site service tickets (recorded at warehouse), **Project Pull fulfillment**, search, customer/project dashboards (transactions only — no financials).

**Priority:** P0

---

### Receiving at Yangon

#### FR-005: Serialized Inventory Receipt (machines + high-value parts)
**Description:** When SERIALIZED inventory arrives at Yangon — machines and designated high-value parts such as compressors and motors — staff scans the supplier's serial number on each piece, the system generates a CastraNova barcode per piece, and a printable label is produced.

**User story:** As a Yangon staff member, I want to record each incoming serialized item quickly so that every individual piece is trackable from the moment it arrives.

**Acceptance criteria:**
- [ ] Receipt captures the supplier's serial number and the CastraNova-generated barcode on each piece.
- [ ] System produces a printable label (PDF) per piece — for the in-warehouse label printer.
- [ ] Each piece's purchase cost and received date are stored individually.
- [ ] If the supplier didn't print a clean serial, staff types it manually.

**Priority:** P0

---

#### FR-006: Quantity-Tracked Parts Receipt (FIFO batches)
**Description:** When commodity spare parts (QUANTITY-tracked products) arrive at Yangon, staff scans the product's SKU barcode and enters quantity and purchase cost. **A new purchase batch is created** with its own cost; the batch queues behind any existing non-depleted batches of the same SKU for FIFO consumption.

**User story:** As a Yangon staff member, I want to add incoming commodity parts to stock without labelling every individual piece, with each receipt forming its own batch so the FIFO order is preserved automatically.

**Acceptance criteria:**
- [ ] Staff scans the product's SKU barcode (one barcode per product, used at the shelf bin and on the receiving form).
- [ ] Staff enters the quantity received and the purchase cost from the supplier invoice.
- [ ] System creates a new `part_batch` row with:
  - `batch_no` auto-generated as **`YYYYMMDD-{SKU}-###`** (daily sequence per SKU; e.g. `20260527-FLT-001`).
  - `received_at` timestamp.
  - `received_qty` (set on creation; immutable thereafter).
  - `remaining_qty` (= `received_qty` at creation; decremented as consumed).
  - `purchase_cost` (per unit, immutable thereafter).
  - Optional **`supplier_batch_ref`** free-text field for the supplier's lot number (nullable).
- [ ] SKU's total quantity-on-hand at YGN = sum of `remaining_qty` across all non-depleted batches.
- [ ] Last-received date is captured per SKU (rough holding-period signal).
- [ ] Missing or extra items vs the supplier manifest are flagged for confirmation.

**Priority:** P0

---

### Consumption — Channels

> **Design note (v2.5):** The data model tracks three channels (`SALE`, `MAINTENANCE`, `PROJECT`), each with its own margin rules. The **Yangon staff consumption screen shows a two-tag segmented control — Sale / Maintenance**. PROJECT consumption is **never initiated by Yangon staff**; it is created as a Project Pull by Bangkok admin and fulfilled by Yangon staff via a separate "Pending Project Pulls" queue (see FR-009). This is a deliberate revert from v2.0–v2.4's three-tag staff UI, per client direction.

#### FR-007: Sale (Sales channel)
**Description:** Yangon staff records the sale of one or more machines and/or parts to a customer.

**User story:** As a Yangon staff member, I want to record a sale by scanning machines and/or selecting parts with quantities, so that stock is deducted and revenue is captured.

**Acceptance criteria:**
- [ ] **Sale requires a customer to be selected (Dealer or End Customer); no walk-in or anonymous sales.** Staff can quickly create a new customer record inline if needed.
- [ ] Machines and serialized parts: scan each piece's barcode → system verifies in-stock → mark as sold at that piece's selling price.
- [ ] Parts (QUANTITY-tracked): scan SKU barcode and enter quantity → system deducts from YGN stock following **FIFO across batches**. A single sale line may produce multiple internal cost lines when the quantity spans two or more batches (e.g., 5 units = 3 from batch A @ ฿100 + 2 from batch B @ ฿120). Each cost line references the source batch.
- [ ] System refuses to oversell (no negative stock).
- [ ] Receipt PDF printable for the customer (operational receipt — not a legal tax document).
- [ ] Works offline at the YGN warehouse; syncs when reconnected.

**Priority:** P0

---

#### FR-008: On-Site Maintenance (Maintenance channel — recorded at warehouse)
**Description:** When a customer reports a problem, a Yangon staff member visits the customer site to assess and lists the parts needed. The mechanic returns to the warehouse (or relays the list to warehouse staff). **All parts are scanned out at the YGN warehouse barcode terminal** and physically delivered to the on-site mechanic; nothing is recorded from the customer site. On the consumption UI, the channel tag is **Maintenance**.

**User story:** As a Yangon staff member, I want to record what parts a customer's repair consumed at the warehouse terminal, even when warehouse wifi is patchy, so that stock is deducted correctly and the maintenance history is preserved.

**Acceptance criteria:**
- [ ] Service ticket links to a customer (mandatory).
- [ ] Service tickets are **opened and closed at the warehouse** — there is no on-site app workflow.
- [ ] Staff can scan/enter parts used during the repair, with quantities, at the warehouse barcode terminal.
- [ ] Parts consumed are priced at the product's **repair price**, not retail (overridable per FR-010).
- [ ] QUANTITY-tracked parts follow FIFO at consumption time (per FR-007 cost-split rule).
- [ ] If a whole machine is swapped at the customer site, the new unit is recorded at the warehouse terminal as a normal Maintenance-channel exit. **The original sale is not linked in v1**; staff capture any unit-swap context in free-text notes on the service ticket.
- [ ] Ticket can be closed; closing deducts all parts from stock in one transaction.
- [ ] **Works offline at the YGN warehouse**; syncs when reconnected. *(v2.4's "works fully offline at the customer site" requirement is removed in v2.5 — there is no on-site recording.)*

**Priority:** P0

---

#### FR-009: Project Consumption (admin-initiated Project Pull workflow)
**Description:** Project consumption is **initiated exclusively by Bangkok admin**. When inventory is deployed as part of a customer project, BKK admin creates a **Project Pull** listing the project, customer, and line items (specific SERIALIZED serials or QUANTITY SKU + quantity). The pull enters `PENDING` state and appears in a Yangon staff "Pending Project Pulls" queue. Yangon staff fulfills the pull by scanning each item at the warehouse barcode terminal, which finalizes a PROJECT-channel consumption (cost only, revenue = 0).

**User story (admin):** As a Bangkok admin, I want to record project consumption myself so that the Project channel is never confused with Sale or Maintenance, and so that physical stock leaves YGN only after staff confirms what was pulled.

**User story (staff):** As a Yangon staff member, I want a clear queue of admin-created pulls so I know exactly which items to set aside for a project, with no risk of mis-tagging the channel.

**Acceptance criteria:**
- [ ] **Yangon staff consumption screen shows two tags only: Sale, Maintenance.** No Project tag is visible to staff.
- [ ] Bangkok admin creates a Project Pull with:
  - `project_id` (FK; customer is auto-derived from the project).
  - One or more line items: each is `product_id` + (specific `unit_serial` for SERIALIZED, or `quantity` for QUANTITY).
  - Optional admin notes.
- [ ] Pull state machine: `PENDING` → `FULFILLED` (all lines scanned), `SHORT` (one or more lines partially fulfilled or unavailable), `CANCELLED` (admin-cancelled before fulfillment).
- [ ] On creation, pull state = `PENDING` and appears in YGN staff "Pending Project Pulls" queue.
- [ ] Yangon staff fulfills by scanning each item at the warehouse barcode terminal. Each scan validates stock; QUANTITY parts decrement FIFO across batches (per FR-007 cost-split rule).
- [ ] On full fulfillment, pull state → `FULFILLED`. One PROJECT-channel consumption record per line is written; cost is recorded per FIFO; **revenue = 0**.
- [ ] If a line is short on physical stock, staff can mark it **partial / short** with the actual quantity fulfilled. Pull state → `SHORT`; BKK admin notified via LINE + Viber (FR-018).
- [ ] BKK admin can cancel a `PENDING` or `SHORT` pull; cancellation is audit-logged and notifies the staff who saw it in queue (if any).
- [ ] Audit record on every consumption names **both users**: admin creator + staff fulfiller (plus timestamps for each).
- [ ] Works offline at the YGN warehouse; syncs when reconnected.
- [ ] Bangkok admin reports continue to show all three channels separately.

**Priority:** P0

---

#### FR-010: Pricing Overrides with Audit Trail
**Description:** Yangon staff can override the default price on a Sale or Maintenance line when needed, but every override is recorded with a mandatory reason. Overrides above the threshold (default 5% deviation) require Bangkok admin co-sign.

**User story:** As a Yangon staff member, I want to offer occasional discounts or adjustments without breaking the audit trail.

**Acceptance criteria:**
- [ ] Override on any Sale or Maintenance line requires a non-empty reason.
- [ ] The deviation threshold that triggers Bangkok co-sign is **set by Bangkok admin** in system settings (default: **5%**, editable any time).
- [ ] Override above the current threshold routes to a Bangkok admin approval queue before the transaction completes.
- [ ] Monthly override exception report lists every override, sorted by deviation size.
- [ ] Project Pulls do not use overrides (revenue is always 0).

**Priority:** P1

---

### Inventory Management

#### FR-011: Stock Adjustment (Bangkok admin only)
**Description:** Bangkok admin can adjust inventory directly to reconcile damaged stock, physical recount discrepancies, supplier returns, or any other gap between system and physical reality. **Yangon staff cannot see or invoke this action.** Every adjustment is audit-logged with actor, timestamp, and mandatory reason.

**User story:** As a Bangkok admin, I want to write off damaged inventory or correct recount discrepancies without exposing a write-off control to Yangon staff, so the system stays in sync with physical reality and the audit trail stays clean.

**Acceptance criteria:**
- [ ] Bangkok admin selects the item to adjust — a specific serialized piece **or** a SKU + quantity delta — and provides a mandatory reason.
- [ ] Adjustment is one-tap (no two-step approval); audit-logged immediately on submit.
- [ ] Serialized pieces can be moved to a terminal `ADJUSTED_OUT` state (visible in lifecycle history; not in active stock).
- [ ] QUANTITY-tracked SKUs accept positive or negative deltas:
  - **Negative deltas consume oldest batches first (FIFO).** Affected `part_batch` rows are recorded on the adjustment for audit (one adjustment may span multiple batches).
  - **Positive deltas** create a new `part_batch` row labelled `YYYYMMDD-{SKU}-ADJ-###` with the admin-supplied cost basis.
- [ ] Negative-beyond-current-stock is blocked.
- [ ] Yangon staff role cannot see or invoke this action.
- [ ] All adjustments appear in the monthly audit log under a dedicated "Adjustments" filter.
- [ ] No notifications fire — this is a quiet, admin-side action.

**Priority:** P1

---

### Reports & Visibility

#### FR-012: Stock-on-Hand Dashboard
**Description:** Live view of current inventory at Yangon — serialized items by piece, QUANTITY-tracked parts by SKU.

**Acceptance criteria:**
- [ ] Serialized items list shows serial/barcode, model, location/status, received date, purchase cost.
- [ ] QUANTITY-tracked parts list shows SKU, name, current quantity-on-hand at YGN (sum of `remaining_qty` across batches), last-received date, **current FIFO cost (oldest non-depleted batch's cost)**.
- [ ] Each QUANTITY row expands to a per-batch breakdown: `batch_no`, `received_at`, `received_qty`, `remaining_qty`, `purchase_cost`, optional `supplier_batch_ref`.
- [ ] Searchable and filterable by category, supplier, customer.

**Priority:** P0

---

#### FR-013: Monthly Channel Margin Report
**Description:** End-of-month report showing revenue, cost of goods sold (COGS), and margin broken out by channel (Sale, Maintenance, Project).

**Acceptance criteria:**
- [ ] Report lists revenue, COGS, and margin per channel.
- [ ] COGS for QUANTITY consumption is the sum of batch-cost lines (FIFO).
- [ ] Drill-down by product, customer, project supported.
- [ ] Available on-screen + PDF + Excel export.

**Priority:** P0

---

#### FR-014: Inventory Holding Period Report
**Description:** Shows how long inventory has been in stock; identifies slow-moving inventory.

**Acceptance criteria:**
- [ ] Per serialized piece (machine or high-value part): days from received to today (or to exit date if sold/consumed/adjusted).
- [ ] Per QUANTITY-tracked batch: days from `received_at` to today (per-batch granularity, since FIFO now exposes batch ages).
- [ ] Per QUANTITY-tracked SKU rollup: days since oldest non-depleted batch was received, plus current quantity on hand.
- [ ] Slow-mover threshold configurable (e.g., > 90 days highlighted).

**Priority:** P1

---

#### FR-015: Search & Lookup
**Description:** Search by serial/barcode (for serialized pieces) or by SKU (for QUANTITY parts).

**Acceptance criteria:**
- [ ] Serialized-piece search (machine or high-value part): full lifecycle (received → sold/consumed → any maintenance → any adjustment), with originating Project Pull if applicable.
- [ ] SKU search (QUANTITY-tracked): per-batch history (each batch's `batch_no`, `received_at`, `received_qty`, `remaining_qty`, `purchase_cost`) + consumption history (all channels, with customer/project, and **which batch(es) each consumption drew from**) + current quantity-on-hand.

**Priority:** P1

---

#### FR-016: Low-Stock Alerts (per SKU)
**Description:** Each spare-part SKU has its own minimum stock level set by Bangkok admin. When the total quantity-on-hand (sum across batches) drops below the threshold, an alert fires.

**Acceptance criteria:**
- [ ] Bangkok admin can set a minimum-stock-level per SKU (bulk-edit screen for setting many at once).
- [ ] When YGN quantity-on-hand drops below the threshold, an alert fires via LINE and Viber.
- [ ] Dashboard always shows the current low-stock SKU list.

**Priority:** P1

---

#### FR-017: Export to PDF and Excel
**Description:** Every list view and report can be exported to PDF and Excel.

**Acceptance criteria:**
- [ ] One-click PDF export from any list/report view.
- [ ] One-click Excel export from any list/report view.

**Priority:** P1

---

### Notifications

#### FR-018: LINE and Viber Notifications
**Description:** Operational alerts pushed to LINE and Viber. Each user can opt in/out per channel and per event type.

**Acceptance criteria:**
- [ ] Trigger events:
  - Low-stock alert (per FR-016).
  - Large pricing override pending (per FR-010).
  - **Project Pull fulfilled** — notifies BKK admin (the pull's creator).
  - **Project Pull marked short** — notifies BKK admin (the pull's creator).
- [ ] Per-user opt-in/out for each channel (LINE, Viber) and each event type.
- [ ] Failed deliveries retry with backoff; permanent failures logged for admin review.

**Priority:** P1

---

### Audit & Data Integrity

#### FR-019: Append-Only Audit Trail
**Description:** Every inventory movement, price change, and adjustment is recorded permanently. Corrections happen via compensating records — nothing is deleted or quietly edited.

**Acceptance criteria:**
- [ ] Every movement records WHO did it, WHEN, and (where applicable) WHY.
- [ ] Project Pull consumptions record both the **admin creator** (`created_by_user_id`, `created_at`) and the **staff fulfiller** (`fulfilled_by_user_id`, `fulfilled_at`).
- [ ] Each cost line on a QUANTITY consumption references the source `part_batch` (immutable audit chain from movement → batch → original receipt).
- [ ] Movements cannot be deleted or edited after the fact.
- [ ] Corrections happen via new compensating entries.
- [ ] Admin can view a filterable audit log by user, date, event type, SKU, or batch.

**Priority:** P0

---

### Customer & Project Analytics (new in v2.5)

#### FR-020: Customer & Project Detail Dashboard
**Description:** Drill-down view of a single customer (with nested projects) for historical analysis. Replaces the prior implicit "search by customer" use case with a structured analytics surface.

**User story:** As a Bangkok admin, I want to click into a customer and see every transaction, every project, and lifetime totals. As Yangon staff, I want a quick lookup of what a customer has bought before to inform a current sale conversation, without seeing margin numbers.

**Acceptance criteria:**

**Customer detail page:**
- [ ] Header: customer name, type (Dealer / End Customer), country, contact.
- [ ] Lifetime totals (BKK admin only): Sale revenue / COGS / margin; Maintenance revenue / COGS / margin; Project COGS (revenue = 0).
- [ ] Transaction list: paginated, filterable by date range and channel (Sale, Maintenance, Project). Visible to both roles.
- [ ] Nested **Active projects** section: each row shows project code, name, budget (admin only), consumed cost-to-date (admin only), % of budget consumed (admin only).
- [ ] Nested **Closed projects** section: same columns, collapsed by default.
- [ ] Action: export to PDF + Excel (admin only; staff sees the export buttons disabled).

**Project detail page (click into a project from the customer page):**
- [ ] Header: project code, name, customer, dates, status, budget (admin only).
- [ ] Cost-to-date and budget-vs-actual chart (admin only).
- [ ] Consumed items list: each line shows item (serial or SKU + qty), batch(es) drawn from (for QUANTITY), date, admin creator, staff fulfiller. Cost column visible to admin only.
- [ ] Pull history: every Project Pull tied to this project with state (PENDING / FULFILLED / SHORT / CANCELLED).

**Role-tiered access:**
- [ ] **Bangkok admin** sees full data: revenue, COGS, margin, budget, budget-vs-actual, cost columns.
- [ ] **Yangon staff** sees transaction list and item history, but financial fields (revenue, COGS, margin, budget, cost) are hidden — the columns are absent, not blank.
- [ ] Backend enforces redaction (two `*Public` Pydantic variants); frontend cannot reveal hidden fields via DOM inspection.

**Navigation:**
- [ ] Accessible from the Customer list (both roles).
- [ ] Accessible from the Project list (admin only — staff have no top-level Project list since they don't initiate Project consumption).

**Priority:** P1

---

## 6. Non-Functional Requirements (business-level)

### Offline operation (YGN warehouse)
- The system works at the **YGN warehouse** when wifi is patchy or unavailable. **All inventory-out recording happens at the warehouse**; on-site customer/mechanic visits do not require system access.
- Scans, sales, maintenance entries, and Project Pull fulfillments are saved locally first; they sync automatically once connectivity returns (wifi or mobile data).
- If two people act on the same item while offline (e.g., one staff sells a machine while another fulfills it for a project pull), the system detects the conflict on sync and surfaces it for review.
- Locally cached data is encrypted; the app auto-logs-out after 12 hours of inactivity.
- Queue capped at 7 days; older items flagged for admin review on replay.

### Language and currency
- English only in v1.
- Thai Baht (THB) only in v1.

### Hardware
- Yangon staff use phones and/or laptops with **dedicated Bluetooth barcode scanners** (keyboard-wedge mode) for fast bulk receiving and pull fulfillment.
- Phone-camera barcode scanning is supported as a fallback.

### Hosting and uptime
- Hosted on Hostinger VPS, Singapore region.
- Daily database backups, 30-day retention, monthly restore tests.

### Audit
- All transactions audit-tagged with user, timestamp, and (where applicable) reason.
- Monthly override-exception report and Stock-Adjustment history report available to Bangkok admin.
- Project Pull audit shows both admin creator and staff fulfiller on every consumption.

---

## 7. UI/UX Requirements (high-level)

### Bangkok admin (desktop-first)
- Dashboard: stock on hand (serialized + QUANTITY with per-batch drill-down), alerts, pending approvals, **pending/short Project Pulls awaiting admin action**.
- Catalog management (products, suppliers, customers, projects, users).
- **Project Pulls section:** create new pull (select project → customer auto-fills → add items: serial scan or SKU+qty → review → submit); pull history with state filter; cancel pending pulls.
- Approval queue (large pricing overrides).
- **Stock Adjustment** (admin-only): write off damaged stock, correct recount discrepancies, adjust per supplier returns — one tap, mandatory reason, audit-logged.
- **Customer detail dashboard** with nested projects (FR-020) — full view with financial fields.
- Reports section (monthly margin, holding period, audit log, exports).

### Yangon staff (phone-first, warehouse-only)
- Home screen: receive, sell, on-site service, **pending project pulls**, search.
- Receive flow (serialized): scan supplier serial → confirm details → print label per piece.
- Receive flow (quantity): scan SKU → enter quantity + cost → system creates new `part_batch`.
- **Sale flow:** select customer (required) → **two-tag segmented control (Sale / Maintenance)** with Sale pre-selected by default → scan / select items → confirm. *Note: Project tag is no longer shown to staff (changed in v2.5).*
- **Service-ticket flow (Maintenance):** open ticket at warehouse → scan/enter parts used (Maintenance is the only available channel from this flow) → free-text notes (for machine-swap context, etc.) → close at warehouse.
- **Pending Project Pulls screen:** list of admin-created pulls in `PENDING` state; tap a pull to view line items → scan each item at the warehouse terminal → mark fulfilled, or mark a line short with the actual quantity available → confirm.
- **Customer detail dashboard** (FR-020) — transaction-only view; financial columns hidden.
- Offline indicator clearly visible at all times.

### Common behaviors
- Loading and empty states explicitly designed.
- Errors surfaced in plain language (e.g., *"This unit is already sold"* — never an error code).

---

## 8. Edge Cases & Error Handling (business-level)

| Scenario | Expected behavior |
|---|---|
| Two staff sell the same machine while one is offline | Server detects on sync; second staff sees *"already sold by [name] at [time]"* and can correct. |
| Parts quantity entered exceeds stock | System blocks the transaction with a clear message showing current available quantity (summed across batches). |
| Offline queue grows past 7 days | Items beyond 7 days are flagged for Bangkok admin review on sync. |
| Supplier didn't print a clean serial | Staff types it manually; system accepts. |
| Pricing override pending Bangkok approval but admin is unavailable | Transaction held in pending state; Yangon can see "awaiting approval" status. |
| Lost barcode label | Bangkok admin reprints by serial number; barcode stays the same. |
| Damaged item discovered at YGN | Yangon staff flags it to Bangkok admin off-system (LINE / phone); Bangkok admin executes a Stock Adjustment with a reason. |
| **Project Pull line is short on physical stock** | Staff marks the line short with the actual quantity available; pull moves to `SHORT` state; BKK admin is notified via LINE + Viber; admin can cancel the remainder or wait for the next receipt and create a follow-up pull. |
| **FIFO batch depletes mid-sale** | Sale splits across two batches automatically (e.g., 5 units = 3 @ ฿100 + 2 @ ฿120); the customer receipt shows the combined quantity at the line's sale price, but the internal cost record carries two cost lines for accurate margin reporting. |
| **New batch arrives while older batch still has stock** | New batch queues behind the existing oldest batch; no impact on current consumption pricing until the older batch is fully depleted. |
| **Admin Project Pull conflicts with a Sale on the same SERIALIZED unit** | First-write-wins; whichever transaction commits first on the server holds the unit. The losing transaction surfaces a clear error ("already pulled for project X" or "already sold"). |
| **Mechanic brings back unused parts from on-site** | Handled off-system. If meaningful, BKK admin uses a positive Stock Adjustment (FR-011) to restock. No staff-facing "return to stock" flow in v1. |

---

## 9. Out of Scope for v1

The following are explicitly **not** in v1 — they can be added in later versions if needed.

- Customer-facing invoicing or legal tax documents (handled by existing accounting tool).
- Warranty start/end tracking per unit.
- Labor charges on repairs.
- Tracking inventory while still in Bangkok or in transit (only tracked from YGN receipt onward).
- Machine returns to the warehouse for service (all service is on-site; warehouse only records parts pulled).
- Multi-currency or foreign-exchange tracking.
- Customer self-service portal.
- Native mobile app (the web app works on phones as a PWA).
- Real-time multi-user live updates (sync-on-reconnect is sufficient).
- Direct integration with accounting or tax systems.
- Multi-language UI.
- **Staff-facing scrap workflow.** Inventory write-offs are handled directly by Bangkok admin via the admin-only Stock Adjustment (FR-011). No staff-facing scrap request, no two-step approval, no scrap notifications.
- **Machine-swap → original-sale linkage in the data model.** When a whole machine is swapped at a customer site, the new unit is recorded normally; the linkage to the customer's prior unit is captured in free-text notes only.
- **Staff-initiated Project consumption.** Project consumption is admin-only via Project Pulls; staff never see a "Project" tag in any consumption flow (new in v2.5).
- **On-site consumption recording.** All recording happens at the YGN warehouse terminal; mechanic visits do not interact with the system (new in v2.5).
- **Returns-to-stock flow.** Unused parts brought back by a mechanic are restocked via admin Stock Adjustment, not via a dedicated workflow (new in v2.5).
- **Weighted-average cost option.** v2.5 uses FIFO exclusively; weighted-average is no longer an option (changed in v2.5).
- **Per-batch labelling of commodity parts.** Batches are an accounting/audit construct; physical commodity parts share the SKU barcode and shelf bin regardless of batch.

---

## 10. Build Phasing

Four phases (was three in v2.4). Each phase delivers usable software at its end.

| Phase | What ships | Rough timeline |
|---|---|---|
| **Phase 1** | Catalog & machine flow — Bangkok pricing + YGN serialized receive + Sale (with mandatory customer) + dashboard for serialized inventory | ~2 weeks |
| **Phase 2** | **FIFO-batched** spare parts (per-piece for SERIALIZED, FIFO batches for QUANTITY) + **admin Project Pull workflow** + on-site Maintenance (recorded at warehouse) + low-stock alerts + monthly margin report | ~4 weeks *(was 3 in v2.4; +1 wk for Project Pull workflow and FIFO complexity)* |
| **Phase 3** | Pricing-override approvals + admin-only Stock Adjustment (FIFO-aware) + audit exports + override exception report | ~1.5 weeks |
| **Phase 4 (new)** | **Customer & Project detail dashboards** (FR-020) with role-tiered access + per-batch drill-down in Search (FR-015) + project pull history view | ~1.5 weeks |

**Total: ~9 weeks** of build (was ~6.5 in v2.4).

---

## 11. Open Items

### Resolved (D1–D22 from v2.4 + D23–D31 new in v2.5)

**v2.4 carry-over (unchanged):**
1. ~~Labels at Yangon — confirm?~~ Confirmed **YES** (D17).
2. ~~Machine-swap repair → original sale linkage strength.~~ Confirmed: **not tracked in v1** (D17).
3. ~~Pricing override threshold.~~ Confirmed: **admin-configurable**, default 5% (D18).
4. ~~Bangkok admin availability hours.~~ Confirmed: **24/7 always-available** for approvals (D19).
5. ~~Baseline for stock-out incidents.~~ Confirmed: **measure from system data in month 1** (D20).
6. ~~Hybrid SERIALIZED / QUANTITY tracking.~~ **Confirmed** by client (D21).
7. ~~Removal of the staff-facing scrap workflow.~~ **Confirmed** by client; admin-only Stock Adjustment stands (D22).
8. ~~Three-tag staff UI for channels.~~ **Reverted in v2.5** — staff now sees two tags (Sale, Maintenance); Project moved entirely to admin Project Pull workflow (supersedes D15-revised; see D27).

**v2.5 new (per client feedback on v2.4):**

9. ~~**Weighted-average vs FIFO costing.**~~ **FIFO confirmed (D23).** Consumption draws from the oldest non-depleted batch first; a single consumption that spans batch boundaries produces multiple cost lines internally. Replaces weighted-average across FR-002, FR-006, FR-007, FR-008, FR-009, FR-011, FR-012, FR-013, FR-015. *Alternatives considered: whole-sale-from-oldest (less accurate); block-sale-if-batch-short (wrong UX).*

10. ~~**Batch number format.**~~ **Auto-generated `YYYYMMDD-{SKU}-###` (D24)** with optional `supplier_batch_ref` free-text. Updates FR-006. *Alternatives considered: sequential-per-SKU (loses date in ID); staff-entered (error-prone).*

11. ~~**FR-007 "sale links to a customer" — clarification.**~~ **Confirmed mandatory (D25).** No walk-in or anonymous sales; staff can create a new customer inline if needed. Sharpens FR-007 acceptance criteria. *Alternatives considered: walk-in customer (pollutes dashboards); nullable customer (breaks reports).*

12. ~~**FR-008 on-site vs warehouse recording.**~~ **All Maintenance recording at YGN warehouse terminal (D26).** Removes "fully offline at customer site" requirement; replaces with "works offline at the warehouse." Mechanic↔warehouse handoff is physical/off-system — no new app feature. Updates FR-008 and §6. *Alternatives considered: drop offline requirement entirely (risky if warehouse wifi drops); keep on-site offline (contradicts client direction).*

13. ~~**FR-009 Project channel — staff initiation.**~~ **Admin-only via Project Pull workflow (D27).** Staff consumption UI reverts to two tags (Sale, Maintenance). Admin creates pull → staff fulfills by scanning at warehouse → consumption finalizes as PROJECT channel. Both users on the audit record. Updates FR-004, FR-009, FR-018, §7, supersedes D15-revised. *Alternatives considered: staff records as Sale/Maintenance then admin reclassifies (loose audit); admin records directly without staff confirmation (system says "consumed" before items physically leave).*

14. ~~**Customer/project dashboard shape.**~~ **Customer detail page with nested projects (D28).** One customer page lists transactions + active/closed projects; click a project for its own drill-down. Adds FR-020. *Alternatives considered: two separate top-level dashboards; combined transaction explorer with filters.*

15. ~~**Customer/project dashboard access control.**~~ **Tiered: BKK admin sees full revenue/COGS/margin/budget; YGN staff sees transactions and item history but financial fields are hidden via separate Pydantic schemas (D29).**

16. ~~**FIFO behaviour for Stock Adjustment.**~~ **Negative adjustments consume oldest batch first (FIFO); positive adjustments create a new ADJ-suffixed batch (D30, default).** Affected batches are recorded on the adjustment for audit. *Alternatives considered: admin picks the batch (extra UI step); newest-first write-off (preserves cost averaging).*

17. ~~**Project Pull race condition.**~~ **Pull supports a `SHORT` state with partial-fulfillment (D31, default).** Staff marks the line short with the actual quantity fulfilled; admin notified; admin decides cancel-or-wait. *Alternatives considered: block the entire pull on any shortfall (too rigid); auto-cancel short pulls (loses partial value).*

### Still open

*None.* All v2.5 requirements are now locked.

---

## 12. Revision Log

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-05-25 | K W G | Initial draft based on client feedback, system design spec, and 11 locked decisions from brainstorming. |
| 0.2 | 2026-05-25 | K W G | Removed FIFO lot tracking. Replaced with hybrid tracking: `SERIALIZED` (per-piece) or `QUANTITY` (SKU counter with weighted-average cost). Per locked D5-revised, D12, D13. |
| 0.3 | 2026-05-25 | K W G | Personas + UI simplification per D14, D15. Removed Yangon Technician (merged into Yangon Staff). 2 system roles. Staff scan UI shows two tags (Sale, Maintenance); Project channel implicit when customer has an active project. |
| 0.4 | 2026-05-25 | K W G | Scrap workflow removed; replaced with admin-only Stock Adjustment per D16 (supersedes D9). |
| 2.0 | 2026-05-25 | K W G | Consolidation pass. D1 → D17 locked. (See v2.4 revision log for full details.) |
| 2.1 | 2026-05-25 | K W G | Pricing override threshold admin-configurable (D18); BKK admin 24/7-available (D19). D1 → D19. |
| 2.2 | 2026-05-25 | K W G | Stock-out baseline measured from system data (D20). All v2 open items resolved. D1 → D20. |
| 2.3 | 2026-05-25 | K W G | Final lock for v2 — D21 (hybrid tracking), D22 (scrap removal), D15-revised (three-tag UI) all confirmed by client. D1 → D22. |
| 2.4 | 2026-05-25 | K W G | Default override threshold tightened from 10% to 5% (D18 default value only). |
| **2.5** | **2026-05-27** | **K W G** | **Client feedback on v2.4 incorporated. Seven amendments + two assumed defaults locked via brainstorming.** **D23:** FIFO replaces weighted-average across the cost model — affects FR-002, FR-006, FR-007, FR-008, FR-009, FR-011, FR-012, FR-013, FR-015. Single consumption spanning batch boundaries produces multiple cost lines. **D24:** Auto-generated batch ID `YYYYMMDD-{SKU}-###` with optional `supplier_batch_ref` — adds `part_batch` entity (FR-006). **D25:** Customer mandatory on every Sale (no walk-in / anonymous) — sharpens FR-007. **D26:** FR-008 Maintenance recording moved entirely to the YGN warehouse terminal; "offline at customer site" requirement removed and replaced with "offline at warehouse." Mechanic↔warehouse handoff is physical/off-system. **D27:** Project channel is **admin-only via a Project Pull workflow** (PENDING → FULFILLED / SHORT / CANCELLED). Staff consumption UI reverts to two tags (Sale, Maintenance); supersedes v2.3's D15-revised three-tag design. Adds FR-009 rewrite, FR-018 triggers, FR-019 dual-actor audit. **D28:** Customer detail page with nested projects as the dashboard shape — adds FR-020. **D29:** Role-tiered dashboard access — BKK admin sees full financials; YGN staff sees transactions only, financial fields hidden via separate Pydantic schemas. **D30 (default):** Stock Adjustment is FIFO-aware (negative deltas consume oldest batches first; positive deltas create ADJ-suffixed batches). **D31 (default):** Project Pull supports a SHORT state for partial fulfillment with admin notification. Build phasing grows from 6.5 to ~9 weeks (added Phase 4 for dashboards). Decision Log: D1 → D31. **PRD v2.5 is fully locked.** **Addendum (2026-05-27, same day):** FR-002 sharpened per client follow-up — added an inline 3+2 example for the mid-consumption batch-split (option (a) accountancy-correct FIFO, explicitly chosen over (b) whole-sale-at-oldest-price and (c) block-spanning-sales) and an explicit batch-succession acceptance bullet (the next batch automatically becomes the effective cost when the oldest depletes; no `price_change` record is written for the succession, since per-batch costs are immutable and only the *active* batch changes). No version bump, no new decisions — D23 reaffirmed with explicit alternatives. |

---

*v2.5 supersedes v2.4. Once approved by the client, the system design spec ([docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md](../superpowers/specs/2026-05-23-castranova-pos-system-design.md)) will be revised in place against this PRD (path 1 from the alignment analysis).*
