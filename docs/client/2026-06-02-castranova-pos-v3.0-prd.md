<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
  --primary: #0f3a52; --accent: #0d9488; --accent-light: #ccfbf1; --gold: #BF9A4A;
  --text: #1f2937; --muted: #6b7280; --border: #e5e7eb; --stripe: #f8fafc; --code-bg: #f1f5f9;
}
@page { size: A4; margin: 20mm 18mm 20mm 18mm; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; color: var(--text); line-height: 1.65; font-size: 10.5pt; margin: 0; padding: 0; }
h1 { color: var(--primary); font-size: 28pt; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 0.4em 0; padding-bottom: 0.3em; border-bottom: 3px solid var(--gold); line-height: 1.15; page-break-after: avoid; }
h2 { color: var(--primary); font-size: 18pt; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 0.5em 0; padding-left: 0.4em; border-left: 4px solid var(--accent); line-height: 1.25; page-break-before: always !important; break-before: page !important; page-break-after: avoid; break-after: avoid; }
h1 + h2 { page-break-before: avoid !important; break-before: avoid !important; }
h3 { color: var(--accent); font-size: 13pt; font-weight: 600; margin: 1.6em 0 0.4em 0; page-break-after: avoid; }
h4 { color: var(--primary); font-size: 11pt; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin: 1.2em 0 0.3em 0; page-break-after: avoid; }
p { margin: 0 0 0.7em 0; }
strong { color: var(--primary); font-weight: 600; }
ul, ol { margin: 0.4em 0 1em 0; padding-left: 1.4em; }
li { margin-bottom: 0.35em; line-height: 1.55; }
li::marker { color: var(--accent); font-weight: 600; }
blockquote { border-left: 4px solid var(--accent); background: var(--accent-light); margin: 1.2em 0; padding: 0.8em 1.2em; color: var(--text); border-radius: 0 4px 4px 0; page-break-inside: avoid; }
blockquote p { margin: 0.3em 0; }
blockquote p:first-of-type { margin-top: 0; } blockquote p:last-of-type { margin-bottom: 0; }
code { font-family: 'JetBrains Mono', monospace; background: var(--code-bg); color: var(--primary); padding: 0.1em 0.4em; border-radius: 3px; font-size: 0.88em; font-weight: 500; }
pre { background: var(--primary); color: #f8fafc; padding: 1em 1.2em; border-radius: 6px; font-size: 0.85em; line-height: 1.55; page-break-inside: avoid; }
pre code { background: transparent; color: inherit; padding: 0; font-weight: 400; }
table { border-collapse: collapse; width: 100%; margin: 1.2em 0; font-size: 9.5pt; page-break-inside: auto; box-shadow: 0 1px 2px rgba(15,58,82,0.04); }
thead { display: table-header-group; } tr { page-break-inside: avoid; }
th { background: var(--primary); color: white; text-align: left; padding: 0.65em 0.9em; font-weight: 600; font-size: 9pt; letter-spacing: 0.03em; text-transform: uppercase; border-bottom: 2px solid var(--gold); }
td { padding: 0.6em 0.9em; border-bottom: 1px solid var(--border); vertical-align: top; line-height: 1.5; }
tr:nth-child(even) td { background: var(--stripe); }
hr { display: none; } hr.visible { display: block; border: none; border-top: 1px solid var(--border); margin: 2.5em 0; }
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent-light); }
@media print { h1, h2, h3, h4 { page-break-after: avoid; } pre, blockquote { page-break-inside: avoid; } img { max-width: 100% !important; } }
.page-break { display: block !important; page-break-before: always !important; break-before: page !important; height: 0; margin: 0; padding: 0; border: 0; visibility: hidden; }
.cover-watermark { text-align: center; margin: 0 0 1.8em 0; }
.cover-watermark img { width: 90px; height: 90px; border-radius: 50%; object-fit: cover; opacity: 0.95; }
</style>

<div class="cover-watermark">
  <img src="pdf/kwg-logo.png" alt="K W G" />
</div>

# CastraNova POS

## Inventory & Channel-Margin System — Project Proposal

**Document:** Product Requirements Proposal · Version 3.0 (Client-Facing)
**Date:** 2 June 2026
**Prepared by:** K W G
**Prepared for:** CastraNova (Bangkok HQ + Yangon Warehouse)
**Companion document:** Project Quotation v2.0 — same folder, dated 2 June 2026
**Validity:** This proposal is valid for 30 days from the date above.

---

> **A note on this document.** This is the **client-facing** version of the requirements. It is written in plain English and intentionally leaves out the implementation-level detail (database design, code patterns, test specifications) that lives in our internal engineering brief. If you'd like to see that depth, we're happy to share it on request — but it isn't needed to approve and sign off on this proposal.

---

## Table of Contents

1. Executive Summary
2. The Challenge
3. The Solution at a Glance
4. Goals We'll Hit
5. Who Will Use It
6. What You Get — Features by Area
7. How It Works — Key Workflows
8. Quality, Security & Reliability
9. What's Not Included (and Why)
10. Tricky Scenarios — How We Handle Them
11. Investment Summary
12. Sign-Off & Next Steps

---

## 1. Executive Summary

CastraNova POS is a purpose-built inventory and margin-reporting system for your B2B refrigeration trading business. It replaces today's spreadsheet-and-memory approach with one barcode-tracked source of truth that spans the **Bangkok HQ administration** and the **Yangon warehouse + on-site service** operation.

Every machine and every high-value spare part is tracked **individually** — one barcode per piece, full lifecycle history. Every commodity spare part is tracked **by SKU** with proper **FIFO cost layering** — each shipment becomes its own purchase batch with its own cost, and consumption draws from the oldest batch first. Every consumption movement — Sale, Maintenance, or Project — is tagged with the customer and the channel, feeding a clean **monthly per-channel margin report**.

The system **works offline** at the Yangon warehouse and syncs automatically when internet returns. Bangkok HQ runs the catalog, prices, customer master data, and creates **Project Pulls** that Yangon staff fulfill at the warehouse barcode terminal. Yangon executes physical receiving, sales, and maintenance.

**Timeline:** two–four weeks from contract signing to go-live, including a parallel run with your existing spreadsheets and 1 day of on-site training per office.
**Investment:** $1,000 USD (≈ ฿35,000 THB), all-in fixed-price. The fee also includes a **small AI integration** that complements the core workflow (specific feature finalized at contract signing). Payment in two milestones — 50% upfront ($500) + 50% on delivery ($500). Optional monthly SLA at ฿5,000 / month available after the 30-day post-launch window. See Project Quotation v2.0 for the full breakdown.

---

## 2. The Challenge

Today, CastraNova runs a healthy refrigeration trading business across two countries with **no single, reliable picture of stock or recent activity**. The cost is real and growing:

### What's happening now

- Bangkok HQ has no live view of what's in the Yangon warehouse, what was sold this week, or which projects have consumed what.
- Yangon staff record receipts and sales on paper or in spreadsheets; month-end reconciliation takes days.
- Maintenance jobs run on memory and LINE messages — there is no audit trail.
- When the warehouse internet drops (which it does), the tooling available to staff stops working.
- Sales, on-site repairs, and project deployments all blend into one undifferentiated stream — true per-channel margins are invisible.
- Nobody can tell at a glance which stock has been sitting on the shelf for 90+ days.

### What it costs

- Slow, error-prone month-end reporting.
- Slow-moving stock that ties up capital without anyone noticing.
- Margin decisions made on incomplete data.
- Lost confidence in inventory counts — staff distrust the spreadsheet, BKK distrusts Yangon, both spend extra time double-checking.

## 3. The Solution at a Glance

> **One barcode-tracked source of truth, working online and offline, with channel-aware margin reporting and a defensible audit trail.**

Concretely:

- **Every machine and high-value spare part** gets a CastraNova barcode on receipt and is tracked piece-by-piece through its full lifecycle.
- **Every commodity part** is tracked by SKU with FIFO purchase batches. The oldest shipment is consumed first; the system handles batch transitions automatically.
- **Every consumption** (Sale, Maintenance, or Project) carries a customer, channel, price, and accurate cost — feeding the monthly margin report.
- **Bangkok HQ owns all admin actions** — catalog, pricing, customers, projects, user accounts, project consumption (via Project Pulls), pricing-override approvals, and any inventory adjustments.
- **Yangon staff handle physical operations** — receiving, sales, on-site service tickets (recorded at the warehouse terminal), and project-pull fulfillment.
- **Offline operation at the warehouse is first-class** — staff keep working when the wifi drops; the system catches up automatically when it returns.
- **Notifications via LINE and Viber** for the events that matter — low stock, large discount waiting for approval, project pull marked short.
- **A complete audit trail** — every movement records who, when, and (where relevant) why.

## 4. Goals We'll Hit

These are the seven outcomes the system is committed to delivering. Each has a clear way to measure success.

| Goal | What we measure | Target | How we check it |
|---|---|---|---|
| See live stock at Yangon | How long it takes to open the warehouse stock screen and see what's in stock | Under 10 seconds, almost every time | Time it with a stopwatch during the pilot |
| Get monthly margin reports on time | The monthly Sale / Maintenance / Project margin report is ready by the end of the first business day of the following month | By end of Day 1 of the next month | Date stamp on the report |
| Every inventory movement is traceable | Percentage of inventory movements (receipts, sales, repairs, project pulls, adjustments) that record who did it, when, and why | 100% | Pick 50 movements at random each month and check each one has a name, time, and reason |
| Keep working when the warehouse internet is down | Sales, scans, and movements captured during an 8-hour internet outage at the warehouse | All of them — no lost work | Unplug the warehouse router for 8 hours during the pilot and confirm everything synced afterwards |
| Spot slow-moving stock easily | How many clicks it takes to see the top slow-movers | One click from the main dashboard | Show the top-20 slow-movers list during the demo |
| Reduce stock-out incidents at Yangon | Number of times a part runs out of stock per month at Yangon | Month 1 = baseline (no target). Month 2 onward = reduction target set together with CastraNova based on the baseline. | Counted automatically from the system |
| Smooth sync after offline work | Percentage of offline sync events that finish on their own without needing the admin to step in | 95 out of every 100, or better | Counted from the admin's review queue at the end of each month |

---

## 5. Who Will Use It

Two clearly separated user roles, designed around how CastraNova actually operates today.

### Bangkok Admin (HQ)

- **Team size:** ~5 people
- **Primary device:** Laptop at the Bangkok office, with reliable internet. Mobile phone as a backup device on the go.
- **What they do in the system:** Maintain the product catalog and prices, manage suppliers, customers, and projects, create Project Pulls when inventory is deployed for a customer project, approve large pricing overrides, perform admin-only Stock Adjustments, review monthly reports and customer/project dashboards
- **Tech comfort:** Medium — comfortable with web apps and spreadsheets

### Yangon Staff (Receiving, Sales, Maintenance, Pull Fulfillment)

- **Team size:** ~5 people (unified team — same people handle receiving, sales, service, and project-pull fulfillment)
- **Primary device:** Laptop at the Yangon warehouse barcode terminal. Mobile phone as a backup when staff are away from the terminal or when a laptop is being repaired. Warehouse wifi is patchy — the system works offline either way.
- **What they do in the system:** Receive incoming shipments, label new stock, process customer sales at the warehouse, record parts used on maintenance jobs (at the warehouse, after the mechanic returns), fulfill Project Pulls created by Bangkok admin
- **Tech comfort:** Low to medium — the interface is designed for fast, scan-driven work and runs on a standard laptop browser
- **What they don't do:** Edit prices, edit the catalog, create projects, initiate project consumption, perform stock adjustments

> **Note on on-site work.** Mechanics visiting customer sites do **not** interact with the system. They list parts needed on paper or LINE; warehouse staff record those parts at the warehouse terminal. This keeps the on-site workflow simple and avoids depending on connectivity at the customer site.

---

## 6. What You Get — Features by Area

Twenty distinct features (FR-001 through FR-020), grouped by area. Each is marked **Must-have** (in v1 launch), **Important** (in v1, can flex on order), or **Nice** (v1 if budget allows, else v1.1).

### 6.1 Catalog & Master Data

#### FR-001 · Product Catalog
**Must-have.**

Bangkok admin maintains the master list of every product — refrigeration machines, high-value parts (compressors, motors), and commodity parts (filters, fittings, refrigerants). Each product has a unique SKU, model name, brand, category, and a **tracking mode**: either *Serialized* (one barcode per piece) or *Quantity* (SKU stock counter). KWG handles a one-time seed import of your existing product list from CSV or Excel at deployment.

#### FR-002 · Per-Product Pricing with FIFO Cost Tracking
**Must-have.**

Every product carries a **retail price** (for Sale) and a **repair price** (for Maintenance). For commodity parts tracked by quantity, the **cost** comes from FIFO purchase batches — the oldest shipment is consumed first. When a single sale spans two batches (e.g., 5 units = 3 from the old batch + 2 from the new), the system splits the cost accurately so your margin report stays correct. Every price change is recorded permanently; auditors can answer *"what was the price of part X on a given date?"*

#### FR-003 · Suppliers, Customers & Projects
**Must-have.**

Bangkok admin maintains the authoritative lists of suppliers, customers (Dealer or End Customer), and projects (with code, name, customer link, dates, optional budget). Yangon staff can read these lists and link transactions to them. Staff can quickly **create a new customer record inline** during a sale if needed.

#### FR-004 · User & Role Management
**Must-have.**

Two clearly separated roles: **Bangkok admin** (full surface — catalog, pricing, projects, approvals, adjustments, full dashboards) and **Yangon staff** (warehouse operations + customer transactions, no financial figures on dashboards). Bangkok admin can add, edit, and deactivate user accounts. New users go through a quick one-time LINE/Viber bot enrollment so they can receive alerts — KWG handles the first 10 users at deployment.

### 6.2 Receiving at Yangon

#### FR-005 · Serialized Receiving (Machines & High-Value Parts)
**Must-have.**

When a machine or designated high-value part arrives, Yangon staff scans the supplier's serial number, the system generates a **CastraNova barcode** for that piece, and prints a label for the warehouse label printer. Each piece's purchase cost and received date are stored individually. If the supplier serial sticker is messy, staff simply types it.

#### FR-006 · Commodity Parts Receiving (FIFO Batches)
**Must-have.**

When commodity parts arrive, staff scans the product SKU barcode, enters the quantity and cost from the supplier invoice, and the system creates a **new FIFO purchase batch** automatically. Each batch gets a clean, dated ID (e.g. `20260527-FLT-001`). Missing or extra items vs the supplier manifest are flagged for confirmation.

### 6.3 Consumption — Three Channels

> **Note:** The system separates consumption into three channels — **Sale**, **Maintenance**, **Project** — for accurate margin reporting. Yangon staff only sees two tags on screen (*Sale* and *Maintenance*); the third (*Project*) is admin-initiated and shows up in a separate "Pending Project Pulls" queue.

#### FR-007 · Sale
**Must-have.**

Yangon staff records the sale of one or more machines and/or parts to a customer at the warehouse. **A customer is always required** (no walk-in or anonymous sales). Machines are scanned individually; parts are scanned by SKU with a quantity. The system refuses to oversell, applies FIFO cost-layering automatically, and prints a customer receipt. **The whole flow works offline** at the warehouse and syncs when reconnected.

#### FR-008 · On-Site Maintenance (Recorded at the Warehouse)
**Must-have.**

When a customer reports a problem, a Yangon team member visits the site, assesses, and lists the parts needed. All parts are then scanned **at the warehouse barcode terminal** and physically delivered to the on-site mechanic. The ticket is opened and closed at the warehouse. Parts are priced at the product's repair price (overridable per FR-010). If a whole machine is swapped at the customer site, the new unit is recorded as a normal Maintenance exit; the swap context is captured in free-text notes on the ticket.

#### FR-009 · Project Consumption — Admin Project Pulls
**Must-have.**

Project consumption is **admin-initiated only**. Bangkok admin creates a **Project Pull** listing the project, customer, and line items. The pull appears in Yangon staff's "Pending Project Pulls" queue. Staff fulfills by scanning each item at the warehouse barcode terminal. On full fulfillment the pull is *Fulfilled*; on partial fulfillment it's *Short* and Bangkok admin is notified via LINE + Viber to decide whether to wait for the next shipment or cancel the remainder. Every Project consumption is **cost-only** (revenue = 0) and is audit-tagged with both the admin who created the pull and the staff member who fulfilled it.

#### FR-010 · Pricing Overrides with Audit Trail
**Important.**

Yangon staff can override the default price on a Sale or Maintenance line — but every override needs a reason. Overrides **above the threshold** (default 5%, admin-configurable) route to Bangkok admin for approval; the sale waits in "awaiting approval" status. The monthly override exception report lists every override sorted by deviation size.

### 6.4 Inventory Management

#### FR-011 · Stock Adjustment (Admin Only)
**Important.**

Bangkok admin can adjust stock directly — to reconcile damaged stock, recount discrepancies, supplier returns, or any other gap between system and physical reality. **Yangon staff cannot see or invoke this action.** Every adjustment is audit-logged with the actor, time, and a mandatory reason. Negative adjustments consume oldest FIFO batches first; positive adjustments create a new batch labelled with `-ADJ-` in its ID.

### 6.5 Reports & Dashboards

#### FR-012 · Stock-on-Hand Dashboard
**Must-have.**

Live view of current Yangon inventory — serialized items by piece, commodity parts by SKU. Each commodity row expands to show its FIFO batches: how many units in each batch, when they were received, and at what cost. Searchable and filterable by category, supplier, customer.

#### FR-013 · Monthly Channel Margin Report
**Must-have.**

End-of-month report showing **revenue, cost, and margin per channel** (Sale, Maintenance, Project). Drill-down by product, customer, or project. Available on screen, as PDF, and as Excel.

#### FR-014 · Inventory Holding Period Report
**Important.**

Shows how long each serialized piece and each FIFO batch has been sitting in stock. Identifies slow-movers. Slow-mover threshold is configurable (e.g., highlight anything over 90 days).

#### FR-015 · Search & Lookup
**Important.**

Search by serial / barcode (for serialized pieces) or by SKU (for commodity parts). Serial search returns the **full lifecycle** of that piece. SKU search returns batch history, consumption history with batch-by-batch attribution, and current quantity-on-hand.

#### FR-016 · Low-Stock Alerts (Per SKU)
**Important.**

Bangkok admin sets a minimum stock level per SKU (single-row edit or **bulk-edit screen** for setting many at once). When Yangon stock drops below the threshold, an alert fires via LINE and Viber. The dashboard always shows the current low-stock list.

#### FR-017 · Export to PDF and Excel
**Important.**

One-click PDF and Excel export from every list view and report — stock-on-hand, channel margin, holding period, override exceptions, search results, customer detail, project detail, audit log, low-stock list, and adjustments history.

### 6.6 Notifications

#### FR-018 · LINE and Viber Notifications
**Important.**

Operational alerts pushed to LINE and Viber. Each user picks which channels (LINE, Viber, both, neither) and which events to receive. Events covered: low-stock alert, large pricing-override pending, Project Pull fulfilled, Project Pull marked short. Failed deliveries retry automatically; permanent failures are logged for admin review.

### 6.7 Audit & Compliance

#### FR-019 · Append-Only Audit Trail
**Must-have.**

Every inventory movement, price change, and adjustment is recorded **permanently**. Nothing is deleted or quietly edited — corrections happen via compensating records. Project Pull consumptions record both the **admin who created the pull** and the **staff member who fulfilled it**. Admin can filter the audit log by user, date, event type, SKU, or batch.

### 6.8 Customer & Project Analytics

#### FR-020 · Customer & Project Detail Dashboard
**Important.**

Drill-down view of a single customer with nested projects. The **customer page** shows lifetime totals (revenue / cost / margin, admin-only), the full transaction list, active and closed projects. The **project page** shows budget-vs-actual (admin-only), the consumed-items list with batch attribution, and pull history. **Yangon staff see transactions and item history only** — financial columns are completely hidden from staff (not just visually masked).

---

## 7. How It Works — Key Workflows

### 7.1 Bangkok admin (laptop-first, phone backup)
- **Dashboard** — stock on hand, alerts, pending approvals, pending/short Project Pulls
- **Catalog management** — products, suppliers, customers, projects, users
- **Project Pulls** — create a new pull (select project → customer auto-fills → add items → submit), view history, cancel pending pulls
- **Approval queue** — large pricing overrides waiting for sign-off
- **Stock Adjustment** — write off damaged stock, correct recount gaps, with reason
- **Customer detail dashboard** with nested projects — full financial view
- **Reports section** — monthly margin, holding period, audit log, override exceptions, adjustments history, exports
- **System settings** — override threshold, low-stock default, label printer config

### 7.2 Yangon staff (laptop-first, phone backup, warehouse-only)
- **Home screen** — receive, sell, on-site service, pending project pulls, search
- **Receive (serialized)** — scan supplier serial → confirm details → print label per piece
- **Receive (commodity)** — scan SKU → enter quantity + cost → batch created automatically
- **Sale** — select customer (required) → two-tag control (Sale / Maintenance, Sale default) → scan / select items → confirm
- **Service ticket (Maintenance)** — open ticket at warehouse → scan / enter parts → notes → close
- **Pending Project Pulls** — list of admin-created pulls; click → view lines → scan each item → mark fulfilled or short
- **Customer dashboard** — transaction-only view; no financial columns
- **Offline indicator** — clearly visible at all times; a counter shows pending sync count

### 7.3 Things both roles get
- Loading and empty states designed explicitly — no blank screens
- Errors in plain language (*"This unit is already sold"*) — no error codes
- Phone-camera barcode scanning as a fallback when no Bluetooth scanner is paired

---

## 8. Quality, Security & Reliability

### 8.1 Speed
- The stock-on-hand dashboard opens in under 10 seconds at the warehouse, even with hundreds of SKUs and thousands of batches in the system.
- Other pages load in under 2 seconds at the warehouse (4G) and under 1 second at the Bangkok office (fibre).
- The monthly margin report renders in under 5 seconds for a one-month window.
- The system comfortably handles all 10 of your concurrent users with headroom for occasional 20-user peaks.

### 8.2 Security
- Industry-standard login with secure tokens.
- Two clearly separated roles with strict server-side enforcement — Yangon staff cannot accidentally (or deliberately) reach admin-only screens.
- Login attempts are rate-limited to prevent brute-force attacks.
- All traffic is encrypted in transit (HTTPS).
- Daily database backups with 30-day retention. We run a restore drill every month on a staging copy to confirm backups are usable.
- Sensitive secrets are rotated annually.

### 8.3 Offline operation (Yangon warehouse)
- The system works at the warehouse when wifi is patchy or unavailable. All inventory-out recording happens at the warehouse.
- Sales, scans, maintenance entries, and project-pull fulfillments are saved on the device first; they sync automatically once internet returns.
- If two people accidentally act on the same item while offline (e.g., one sells a machine while another fulfills it for a project pull), the system spots the conflict on sync and surfaces it for review.
- The app auto-logs-out after 12 hours of inactivity for security.
- The offline queue is capped at 7 days; anything older is held back for admin review on sync, so a forgotten device in a drawer can't quietly corrupt your records weeks later.

### 8.4 Hosting and uptime
- Hosted on a **Hostinger KVM 8 VPS** in the Singapore region (8 vCPU / 16 GB RAM / 100 GB SSD — comfortable headroom for your volume with room to grow).
- Daily database backups, 30-day retention, monthly restore tests on staging.
- Uptime target: 99% (excluding planned maintenance windows announced at least 48 hours ahead).
- Optional Hostinger Daily Auto-Backup add-on (~฿840 / month) pairs with the daily backup for redundancy; recommended but not required.

### 8.5 Hardware

CastraNova procures the hardware directly from Thailand-distributed vendors. KWG QAs against the reference models below during deployment.

**Reference barcode scanners** — two well-tested Bluetooth HID-mode scanners available through Thai distributors:

- **TYSSO BCP-2DC** — 1D + 2D Bluetooth scanner (HID keyboard-wedge mode). Primary scanner. Available through POSPAK Thailand and other Bangkok POS distributors.
- **Posiflex CD-3870** — 1D Bluetooth scanner (HID keyboard-wedge mode). Backup unit. Available through Posiflex's Thailand distributor network.

Other Bluetooth HID-mode scanners may work but are supported on best-effort only.

**Label printer** — **TSC TDP-225** (2-inch desktop direct thermal label printer, USB). The most common label printer in Thailand's POS market; available through BARIGAN, PM Labels, and other Bangkok distributors. Direct thermal — no ribbon needed; uses 4×6 inch label rolls.

**Phone as backup device** — When a laptop is unavailable (battery, repair, or staff are away from the warehouse terminal), Yangon staff can fall back to a mobile phone. The phone runs the same browser interface and can use its built-in camera as a barcode scanner. Slower than a laptop with a Bluetooth scanner, but covers the gap.

### 8.6 Language and currency
- English only in v1.
- Thai Baht (THB) only in v1.

### 8.7 Audit
- Every transaction is audit-tagged with the user, the time, and (where relevant) the reason.
- Monthly override-exception and stock-adjustment history reports are always available to Bangkok admin.
- Project Pull audit shows both the admin creator and the staff fulfiller on every consumption.

### 8.8 Observability
- We use Sentry to capture front-end and back-end errors automatically, so we see and fix things even before you report them.
- Notification delivery failures are logged in a place admin can review weekly.

## 9. What's Not Included (and Why)

Being explicit about what's **not** in v1 helps everyone stay aligned. Most of these are either future-version candidates or out of scope by design.

### Out of scope for v1

| Excluded | Why |
|---|---|
| Customer-facing legal tax documents | Your existing accounting tool handles tax invoicing |
| Warranty start / end tracking per unit | Not in scope per v2.5 client direction |
| Multi-currency | THB only in v1 |
| Native mobile app | The web app runs on phones as a backup; no separate native app needed |
| Direct integration with accounting / tax systems | Reports export to PDF and Excel for hand-off to your accountant |

### Deferred to v1.1 (a future, separately-scoped engagement)

| Deferred | Why it's a v1.1 candidate |
|---|---|
| Admin customer-merge tool | Handles the rare case of duplicate customer records created during offline sales. v1 tolerates duplicates; the merge tool is a quality-of-life upgrade |
| Stronger app-level encryption of offline cached data | v1 relies on device-level encryption + 12-hour auto-logout + 7-day queue cap. If your security policy later requires app-level encryption, we can add it |
| Stock-out incident dashboard as a first-class report | The data is already captured by FR-016 alerts; a dedicated dashboard view is a polish item |
| Bulk catalog re-import beyond the v1 seed | v1 imports your catalog once at deployment; ongoing additions are single-row |
| 24×7 SLA / support tier | Post-launch support is a 30-day bug-fix window; longer-term support is available as a retainer (see quotation §9) |

## 10. Tricky Scenarios — How We Handle Them

Real warehouse operations throw curveballs. These are the ones we've designed for explicitly.

| What could go wrong | What the system does |
|---|---|
| Two staff sell the same machine — one of them is offline | When the offline one comes back online, the system spots the clash and shows *"already sold by [name] at [time]"* so they can fix it. |
| Staff tries to sell more parts than are in stock | The sale is blocked. The screen shows exactly how many are actually available. |
| Supplier's serial number sticker is messy or unreadable | Staff types it in by hand. The system accepts it like any scanned serial. |
| A big discount needs Bangkok approval but the admin isn't around | The sale waits in "awaiting approval" status. Once admin approves on LINE / Viber, the sale goes through. |
| Yangon finds damaged stock | Staff messages Bangkok on LINE or phone; Bangkok admin writes it off using the Stock Adjustment screen with a reason. |
| A sale empties the oldest batch and dips into the next one | The customer just sees one line on their receipt (e.g. *"5 filters @ ฿120 each"*). Behind the scenes the system uses both batches' costs so the margin report stays accurate. |
| A new batch arrives while the old batch still has stock | The new batch waits in line. Sales keep using the old batch's price until it's fully sold out, then automatically switch to the new one. |
| Bangkok creates a Project Pull for a machine that Yangon happens to be selling at the same moment | Whoever saves first wins. The other person sees *"already sold"* or *"already pulled for project X"* and can pick a different item. |
| Yangon staff's laptop (or backup phone) runs out of battery while offline work is still pending | When the device is back on, the pending work is still there. It syncs the moment internet returns. |
| The Bluetooth scanner sends odd extra keystrokes | The system reads only the actual barcode and ignores anything extra. |

## 11. Investment Summary

| Item | Amount |
|---|---|
| **Total project fee** | **$1,000 USD** (≈ ฿35,000 THB) |
| Payment terms | 2 milestones — $500 upfront + $500 on delivery |
| Currency | US Dollars (USD), with THB equivalent at ~35 THB per USD |
| Quotation reference | KWG-CN-2026-0602-Q2 |
| Quotation document | See **Project Quotation v2.0** (same folder, dated 2 June 2026) |

**What's covered by the project fee:** all 20 features, the small AI integration, deployment, parallel run, on-site training (1 day per office), and 30 days of post-launch bug-fix support.

**What's separately client-owned** (not in the project fee):
- **Hardware (Thailand-procured):** TYSSO BCP-2DC + Posiflex CD-3870 scanners (~฿8,300), TSC TDP-225 label printer (~฿8,500), label rolls (~฿1,200/year) — approximately **฿16,800 one-time + ฿1,200 / year**
- **Hosting (Hostinger KVM 8 Singapore):** ~฿12,800 first year (promo $28.49/mo + tax + free domain), ~฿24,700 / year from year 2 onward (renewal at $53.99/mo). Optional Daily Auto-Backup ~฿840 / month
- **Notifications:** LINE Messaging API + Viber Bot — free tier sufficient at your volume

**Post-launch (after the 30-day included window):** Optional monthly **Service Level Agreement at ฿5,000 / month** covering bug-fix support, monthly system health check, user onboarding for new staff, and runbook updates. Three-month minimum if opted in; 30 days notice to terminate. See Project Quotation v2.0 §6 for full terms.

See Project Quotation v2.0 for the complete commercial terms — payment schedule, change-order process, warranty, IP transfer, confidentiality, termination clauses, and signature block.

## 12. Sign-Off & Next Steps

To move forward:

1. **Review** this proposal and the companion Project Quotation v2.0.
2. **Share** any questions or change requests by the validity date (2 July 2026). We'll respond within 3 business days with any impact assessment.
3. **Sign** the quotation acceptance block — physically or via electronic signature.
4. **KWG starts** on the first business day after signed acceptance + the upfront payment land.

We'd love to be working alongside you. We're confident this system will give CastraNova exactly the visibility, control, and audit trail that today's spreadsheet-and-memory operation can't.

---

*Prepared by K W G · 2 June 2026 · valid for 30 days · For questions, reply to this proposal or contact the K W G project lead.*
