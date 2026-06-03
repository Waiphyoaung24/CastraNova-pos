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
.subtotal-row td { background: var(--stripe); font-weight: 600; color: var(--primary); }
</style>

<div class="cover-watermark">
  <img src="pdf/kwg-logo.png" alt="K W G" />
</div>

# Estimate / Proforma — Hardware & Hosting

<div class="meta-grid">
  <div><div class="meta-label">Invoice Number</div><div class="meta-value">KWG-CN-2026-0602-INV-002</div></div>
  <div><div class="meta-label">Issue Date</div><div class="meta-value">2 June 2026</div></div>
  <div><div class="meta-label">Reference Quotation</div><div class="meta-value">KWG-CN-2026-0602-Q2 · §5</div></div>
  <div><div class="meta-label">Payment Terms</div><div class="meta-value">Net 14 days from issue date</div></div>
</div>

<div class="parties">
  <div class="party">
    <div class="party-label">From</div>
    <div class="party-name">K W G</div>
    <div class="party-detail">Pass-through procurement<br/>Email: <a href="mailto:waiphyoag.cs34@gmail.com">waiphyoag.cs34@gmail.com</a><br/>Bank details: see attached scan</div>
  </div>
  <div class="party">
    <div class="party-label">Bill To</div>
    <div class="party-name">CastraNova</div>
    <div class="party-detail">Bangkok HQ + Yangon Warehouse<br/>Attention: Bangkok admin team<br/>VAT / Tax ID: ______________________</div>
  </div>
</div>

> **This is an estimate, not a final invoice.** All hardware amounts below are **indicative prices based on current Thailand-distributor catalogs** as of 2 June 2026. Final amounts will be confirmed with CastraNova **after K W G obtains live vendor quotes** and **before any purchase order is placed**. Prices may move up or down based on stock availability, bulk discounts, and current promotions. K W G procures at pass-through vendor cost — **no margin is added**. Vendor receipts are provided on procurement completion.

## Hardware (One-Time Procurement) — Estimate

Reference models per PRD v3.0 §8.5. Items procured through Thailand-based distributors. **Prices below are indicative — to be confirmed with live vendor quotes before purchase.**

| Item | Vendor | Qty | Indicative Unit Price (THB) | Estimated Amount (THB) |
|---|---|---|---|---|
| **TYSSO BCP-2DC Bluetooth scanner** (1D + 2D, HID mode) — primary warehouse scanner | POSPAK Thailand / Shop4Thai | 1 | ~4,500 | <span class="amount-cell">~4,500</span> |
| **Posiflex CD-3870 Bluetooth scanner** (1D, HID mode) — backup unit | Posiflex Thailand distributor | 1 | ~3,800 | <span class="amount-cell">~3,800</span> |
| **TSC TDP-225 label printer** (2-inch desktop direct thermal, USB) — warehouse label printing | BARIGAN / PM Labels | 1 | ~8,500 | <span class="amount-cell">~8,500</span> |
| **Direct thermal label rolls** (4×6 in, 200 ct, TSC-compatible) — first-year supply | Local label suppliers | 4 | ~300 | <span class="amount-cell">~1,200</span> |

<table>
  <tr class="subtotal-row">
    <td colspan="4" style="text-align: right;">Estimated hardware subtotal</td>
    <td class="amount-cell">~฿18,000</td>
  </tr>
</table>

## Hosting (First-Year Subscription)

Hostinger KVM 8 VPS (Singapore region) per PRD v3.0 §8.4. Billed once for the 12-month promotional rate. Subscription in CastraNova's name; K W G provisions and configures the server during deployment.

| Item | Vendor | Period | Unit Price | Amount |
|---|---|---|---|---|
| **Hostinger KVM 8 VPS** (8 vCPU / 16 GB RAM / 100 GB SSD) — promotional rate | Hostinger | 12 months | $28.49 / mo | <span class="amount-cell">$341.88 USD</span> |
| **Domain registration** (e.g. `pos.castranova.com`) | Hostinger | 12 months | free with VPS | <span class="amount-cell">$0.00 USD</span> |
| **Taxes** | Hostinger | — | — | <span class="amount-cell">$23.93 USD</span> |

<table>
  <tr class="subtotal-row">
    <td colspan="4" style="text-align: right;">Hosting subtotal (first year)</td>
    <td class="amount-cell">$365.81 USD (≈ ฿12,800 THB)</td>
  </tr>
</table>

> **Year 2 onward (CastraNova-direct subscription):** Hostinger KVM 8 renews at ~$53.99 / month (~$647.88 / year + tax + domain at ~$13 / year = approximately **$706 / year ≈ ฿24,700 / year**). CastraNova subscribes and renews directly with Hostinger from year 2 — K W G does not invoice for renewals.

## Estimated Total

<table>
  <tr>
    <td style="padding: 0.7em 0.9em; color: var(--muted);">Estimated hardware subtotal (indicative)</td>
    <td class="amount-cell" style="padding: 0.7em 0.9em;">~฿18,000</td>
  </tr>
  <tr>
    <td style="padding: 0.7em 0.9em; color: var(--muted);">Hosting subtotal — first year (Hostinger promo, firm)</td>
    <td class="amount-cell" style="padding: 0.7em 0.9em;">฿12,800 (= $365.81 USD)</td>
  </tr>
  <tr class="total-row">
    <td style="text-align: right; padding: 0.9em;">Estimated Total</td>
    <td class="amount-cell" style="padding: 0.9em;">~฿30,800 (≈ $880 USD)</td>
  </tr>
</table>

> **Confirmation step before procurement.** Once CastraNova approves this estimate, K W G will (1) request live quotes from the listed Thai distributors, (2) share the firm vendor quotes with CastraNova for written confirmation, and (3) only then place the purchase orders. The final invoice will match the actual amounts on those vendor receipts.

## Optional Add-Ons (Not in Total Above)

CastraNova may opt into either of the items below; both will be added to this invoice or billed separately at CastraNova's choice.

| Item | Vendor | Period | Price |
|---|---|---|---|
| **Hostinger Daily Auto-Backup** — recommended for redundancy alongside KWG's daily `pg_dump` | Hostinger | per month | ~$24 / month (~฿840 / month) |
| **Additional label rolls** beyond the 4-pack | Local label suppliers | per roll | ~฿300 / roll |

## What's NOT in This Invoice

- KWG software development services — see Invoice KWG-CN-2026-0602-INV-001
- LINE Messaging API and Viber Bot accounts — free-tier sufficient at v1 volume; CastraNova owns the accounts directly
- Year 2+ hosting renewal — CastraNova subscribes to Hostinger directly
- Optional monthly SLA after the 30-day support window — separately invoiced at ฿5,000 / month if opted in

## Process Going Forward

1. **CastraNova reviews this estimate** and indicates which items K W G should procure on their behalf (CastraNova may also choose to procure any item directly from the listed vendor — please notify K W G).
2. **K W G obtains live quotes** from the listed Thai distributors and Hostinger and shares them with CastraNova within 3 business days.
3. **CastraNova confirms the firm vendor amounts** in writing.
4. **Final invoice is issued** matching the confirmed vendor amounts.
5. **Payment** of the final invoice is due within 14 calendar days. K W G then places the purchase orders and configures the Hostinger VPS.
6. **Vendor receipts** for all line items are provided to CastraNova upon procurement completion.

## Acknowledgement

By approving this estimate, CastraNova acknowledges that the indicative amounts above will be replaced by live vendor quotes before any procurement is initiated, that all items will be procured at pass-through vendor cost with no margin added by K W G, and that warranty, support, and replacement of all hardware items remain the responsibility of the underlying vendor.

For questions about this invoice, reply to the K W G project lead or contact K W G directly.

---

*Prepared by K W G · Estimate KWG-CN-2026-0602-INV-002 · Issued 2 June 2026 · Indicative — pending vendor-confirmation step*
