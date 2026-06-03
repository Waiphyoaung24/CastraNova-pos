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
table { border-collapse: collapse; width: 100%; margin: 1.2em 0; font-size: 10pt; page-break-inside: auto; box-shadow: 0 1px 2px rgba(15,58,82,0.04); }
thead { display: table-header-group; } tr { page-break-inside: avoid; }
th { background: var(--primary); color: white; text-align: left; padding: 0.65em 0.9em; font-weight: 600; font-size: 9pt; letter-spacing: 0.03em; text-transform: uppercase; border-bottom: 2px solid var(--gold); }
td { padding: 0.7em 0.9em; border-bottom: 1px solid var(--border); vertical-align: top; line-height: 1.5; }
tr:nth-child(even) td { background: var(--stripe); }
hr { display: none; } hr.visible { display: block; border: none; border-top: 1px solid var(--border); margin: 2.5em 0; }
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent-light); }
@media print { h1, h2, h3, h4 { page-break-after: avoid; } pre, blockquote { page-break-inside: avoid; } img { max-width: 100% !important; } }
.cover-watermark { text-align: center; margin: 0 0 1.8em 0; }
.cover-watermark img { width: 90px; height: 90px; border-radius: 50%; object-fit: cover; opacity: 0.95; }
.parties { display: flex; gap: 2em; margin: 1.5em 0 2em 0; }
.party { flex: 1; }
.party-label { font-size: 9pt; font-weight: 600; color: var(--gold); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.3em; }
.party-name { font-size: 13pt; font-weight: 700; color: var(--primary); margin-bottom: 0.2em; }
.party-detail { font-size: 10pt; color: var(--muted); line-height: 1.5; }
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1em 2em; margin: 1.5em 0; padding: 1em 1.2em; background: var(--stripe); border-left: 4px solid var(--gold); border-radius: 0 4px 4px 0; }
.meta-label { font-size: 9pt; font-weight: 600; color: var(--gold); text-transform: uppercase; letter-spacing: 0.06em; }
.meta-value { font-size: 12pt; font-weight: 600; color: var(--primary); }
.total-row td { background: var(--primary) !important; color: white !important; font-weight: 700; font-size: 12pt; border-top: 2px solid var(--gold); }
.amount-cell { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>

<div class="cover-watermark">
  <img src="pdf/kwg-logo.png" alt="K W G" />
</div>

# Invoice — Software Development

<div class="meta-grid">
  <div><div class="meta-label">Invoice Number</div><div class="meta-value">KWG-CN-2026-0602-INV-001</div></div>
  <div><div class="meta-label">Issue Date</div><div class="meta-value">2 June 2026</div></div>
  <div><div class="meta-label">Reference Quotation</div><div class="meta-value">KWG-CN-2026-0602-Q2</div></div>
  <div><div class="meta-label">Payment Terms</div><div class="meta-value">Net 14 days per milestone</div></div>
</div>

<div class="parties">
  <div class="party">
    <div class="party-label">From</div>
    <div class="party-name">K W G</div>
    <div class="party-detail">Software development services<br/>Email: <a href="mailto:waiphyoag.cs34@gmail.com">waiphyoag.cs34@gmail.com</a><br/>Bank details: see attached scan</div>
  </div>
  <div class="party">
    <div class="party-label">Bill To</div>
    <div class="party-name">CastraNova</div>
    <div class="party-detail">Bangkok HQ + Yangon Warehouse<br/>Attention: Bangkok admin team<br/>VAT / Tax ID: ______________________</div>
  </div>
</div>

## Line Items

| # | Description | Amount |
|---|---|---|
| 1 | **CastraNova POS v1 — End-to-end system development** *(Mobilization milestone — 50%)*<br/>Per PRD v3.0 scope (FR-001 through FR-020), including the small AI integration. Trigger: quotation acceptance signed + PRD v3.0 sign-off. | <span class="amount-cell">**$500.00 USD**</span> |
| 2 | **CastraNova POS v1 — End-to-end system development** *(Delivery milestone — 50%)*<br/>Trigger: production cutover + start of the parallel run with existing spreadsheets. | <span class="amount-cell">**$500.00 USD**</span> |

<table>
  <tr>
    <td colspan="2" style="text-align: right; padding: 0.7em 0.9em; color: var(--muted);">Subtotal</td>
    <td class="amount-cell" style="padding: 0.7em 0.9em;">$1,000.00 USD</td>
  </tr>
  <tr>
    <td colspan="2" style="text-align: right; padding: 0.7em 0.9em; color: var(--muted);">VAT</td>
    <td class="amount-cell" style="padding: 0.7em 0.9em; color: var(--muted);">Not applicable (international services)</td>
  </tr>
  <tr class="total-row">
    <td colspan="2" style="text-align: right; padding: 0.9em;">Total Due</td>
    <td class="amount-cell" style="padding: 0.9em;">$1,000.00 USD (≈ ฿35,000 THB)</td>
  </tr>
</table>

## What's Included

This invoice covers the full PRD v3.0 scope:

- Catalog, pricing, suppliers, customers, projects, and user management
- Serialized + commodity (FIFO batch) receiving at Yangon
- Sale · On-site maintenance (recorded at warehouse) · Project Pull workflow
- Pricing overrides with admin approval queue
- Admin-only Stock Adjustment (FIFO-aware)
- Stock-on-Hand dashboard · Monthly channel margin report · Holding-period report · Search & lookup
- Low-stock alerts · PDF + Excel exports across all views
- LINE + Viber notifications with per-user opt-in
- Append-only audit trail with dual-actor tagging on Project Pulls
- Customer & Project detail dashboards with role-tiered access
- **Small AI integration** complementing the core workflow
- Deployment to Hostinger VPS, catalog seed import, LINE/Viber bot enrollment for first 10 users
- Two-week parallel run with existing spreadsheets
- One-day on-site training per office (Bangkok + Yangon)
- 30 calendar days of post-launch bug-fix support

## What's NOT in This Invoice

- Hardware (Bluetooth scanners, label printer, label rolls) — invoiced separately or procured directly by CastraNova
- Hosting subscription (Hostinger VPS, domain) — invoiced separately or subscribed directly by CastraNova
- LINE Messaging API charges beyond the free tier
- Any change order beyond PRD v3.0 scope (priced by mutual agreement per Quotation v2.0 §9)

## Recurring Charge — Monthly SLA Agreement

Starting **from month 2** (immediately after the 30-day post-launch bug-fix window included in the project fee), CastraNova continues onto a **monthly Service Level Agreement** for ongoing support and maintenance.

| Item | Amount |
|---|---|
| **Monthly SLA fee** | **฿5,000 / month** |
| **Start date** | Day 31 after production cutover (immediately after the included 30-day window) |
| **Billing cycle** | Monthly · invoiced on the 1st of each month · payable within 14 calendar days |
| **First monthly invoice number** | KWG-CN-2026-XXXX-SLA-001 *(numbered sequentially each month)* |

### What the monthly SLA covers

- Bug-fix support for any defect traceable to the v3.0 scope
- Monthly system health check (logs, backups, hosting status, notification delivery)
- LINE / Viber bot enrollment for new user accounts as CastraNova adds staff
- Admin runbook updates as the system evolves
- Same response SLAs as the included 30-day window: critical fixes within 1 business day, non-critical within 5 business days

### What the monthly SLA does NOT cover

- New features or scope changes beyond PRD v3.0 — those are change orders, priced by mutual agreement per Quotation v2.0 §9
- Hardware repair or replacement (vendor responsibility)
- Third-party API outages (LINE, Viber, Hostinger) or behaviour changes

### Terms

- **Minimum commitment:** three months once activated.
- **Termination:** 30 calendar days written notice from either party after the minimum commitment.
- **Pause or skip:** if CastraNova wishes to pause the SLA in a given month, written notice 14 days before that month's billing. Resumption requires written re-activation.
- **Opt-out:** CastraNova may decline the SLA entirely. In that case, post-month-1 support is handled ad-hoc — KWG and CastraNova agree on a price per request before any work starts.

By approving Invoice KWG-CN-2026-0602-INV-001, CastraNova acknowledges and accepts the monthly SLA terms above unless explicitly opting out in writing before the end of the included 30-day support window.

## Payment Instructions

1. The **mobilization line item ($500 USD)** is due upon signed quotation acceptance.
2. The **delivery line item ($500 USD)** is due upon production cutover + start of the parallel run.
3. Each milestone is payable within 14 calendar days of milestone trigger.
4. Bank details (account name, account number, SWIFT, currency) — see the bank-details scan attached to this invoice.

## Acknowledgement

By paying this invoice, CastraNova acknowledges that the deliverables described above will be provided per PRD v3.0 ([2026-06-02-castranova-pos-v3.0-prd.md](2026-06-02-castranova-pos-v3.0-prd.md)) and Quotation v2.0 ([2026-06-02-castranova-pos-quotation-v2.0.md](2026-06-02-castranova-pos-quotation-v2.0.md)).

For questions about this invoice, reply to the K W G project lead or contact K W G directly.

---

*Prepared by K W G · Invoice KWG-CN-2026-0602-INV-001 · Issued 2 June 2026*
