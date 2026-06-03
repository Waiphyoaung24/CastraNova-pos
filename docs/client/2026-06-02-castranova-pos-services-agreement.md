<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
  --primary: #0f3a52; --accent: #0d9488; --accent-light: #ccfbf1; --gold: #BF9A4A;
  --text: #1f2937; --muted: #6b7280; --border: #e5e7eb; --stripe: #f8fafc; --code-bg: #f1f5f9;
}
@page { size: A4; margin: 20mm 18mm 20mm 18mm; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; color: var(--text); line-height: 1.65; font-size: 10.5pt; margin: 0; padding: 0; }
h1 { color: var(--primary); font-size: 26pt; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 0.4em 0; padding-bottom: 0.3em; border-bottom: 3px solid var(--gold); line-height: 1.2; page-break-after: avoid; }
h2 { color: var(--primary); font-size: 17pt; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 0.5em 0; padding-left: 0.4em; border-left: 4px solid var(--accent); line-height: 1.25; page-break-before: always !important; break-before: page !important; page-break-after: avoid; break-after: avoid; }
h1 + h2 { page-break-before: avoid !important; break-before: avoid !important; }
h3 { color: var(--accent); font-size: 12pt; font-weight: 600; margin: 1.4em 0 0.4em 0; page-break-after: avoid; }
h4 { color: var(--primary); font-size: 10.5pt; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin: 1em 0 0.3em 0; page-break-after: avoid; }
p { margin: 0 0 0.7em 0; text-align: justify; }
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
.clause { margin-bottom: 0.9em; }
.clause-num { font-weight: 700; color: var(--primary); margin-right: 0.3em; }
.signature-block { display: flex; gap: 2em; margin-top: 2.5em; page-break-inside: avoid; }
.signature-col { flex: 1; border-top: 2px solid var(--primary); padding-top: 0.7em; }
.signature-col-label { font-size: 9pt; font-weight: 700; color: var(--gold); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.5em; }
.signature-line { border-bottom: 1px solid var(--border); height: 1.6em; margin-bottom: 0.7em; }
.signature-meta { font-size: 9pt; color: var(--muted); margin-top: 0.4em; }
</style>

<div class="cover-watermark">
  <img src="pdf/kwg-logo.png" alt="K W G" />
</div>

# Services Agreement

## CastraNova POS v1 — Development, Support & Procurement

<div class="meta-grid">
  <div><div class="meta-label">Agreement Reference</div><div class="meta-value">KWG-CN-2026-0602-MSA-001</div></div>
  <div><div class="meta-label">Effective Date</div><div class="meta-value">2 June 2026</div></div>
  <div><div class="meta-label">Project Scope</div><div class="meta-value">PRD v3.0 (Exhibit A)</div></div>
  <div><div class="meta-label">Commercial Reference</div><div class="meta-value">Quotation v2.0 (Exhibit B)</div></div>
</div>

<div class="parties">
  <div class="party">
    <div class="party-label">Service Provider</div>
    <div class="party-name">Wai Phyo Aung trading as K W G</div>
    <div class="party-detail">Software development services<br/>Email: <a href="mailto:waiphyoag.cs34@gmail.com">waiphyoag.cs34@gmail.com</a><br/>(hereinafter "<strong>KWG</strong>")</div>
  </div>
  <div class="party">
    <div class="party-label">Client</div>
    <div class="party-name">CastraNova</div>
    <div class="party-detail">Bangkok HQ + Yangon Warehouse<br/>Refrigeration trading business<br/>(hereinafter "<strong>CastraNova</strong>" or the "<strong>Client</strong>")</div>
  </div>
</div>

**This Services Agreement** (the "**Agreement**") is entered into between the parties identified above (each a "**Party**" and together the "**Parties**") with effect from the Effective Date above. The Parties agree as follows.

## 1. Background

<div class="clause">
<span class="clause-num">1.1</span> CastraNova operates a B2B refrigeration trading business between Bangkok HQ (administration) and Yangon (warehouse + on-site service) and requires a barcode-tracked inventory and channel-margin reporting system to replace its current spreadsheet-and-memory workflow.
</div>

<div class="clause">
<span class="clause-num">1.2</span> KWG is a software development service provider and has prepared a product requirements document and quotation describing such a system, which CastraNova has reviewed and accepted.
</div>

<div class="clause">
<span class="clause-num">1.3</span> The Parties now wish to formalise the engagement under the terms of this Agreement.
</div>

## 2. Definitions

In this Agreement, the following terms have the meanings given below:

- **"PRD"** means the Product Requirements Document version 3.0 dated 2 June 2026, attached as **Exhibit A** and incorporated by reference.
- **"Quotation"** means Project Quotation v2.0 (reference KWG-CN-2026-0602-Q2) dated 2 June 2026, attached as **Exhibit B** for background only; in the event of any conflict between the Quotation and this Agreement, **this Agreement prevails**.
- **"System"** means the CastraNova POS v1 software application described in the PRD, including the small AI integration referenced therein.
- **"Project"** means the development, deployment, training, and 30-day post-launch support of the System, per Section 4.1.
- **"SLA"** means the monthly support arrangement described in Section 4.2.
- **"Procurement Services"** means the hardware and hosting procurement described in Section 4.3.
- **"Deliverables"** means the items listed in Section 6.
- **"Effective Date"** means 2 June 2026 or the date on which both Parties have signed this Agreement, whichever is later.
- **"Production Cutover"** means the moment the System is deployed to the production environment and made available to CastraNova users in live operation.

## 3. Scope of Services

KWG agrees to provide the following services to CastraNova under this Agreement, comprising three distinct streams:

### 3.1 The Project (one-off development)
KWG will design, build, deploy, train CastraNova staff on, and support the System per the scope set out in the PRD (Exhibit A). The Project includes all twenty functional requirements (FR-001 through FR-020) and the small AI integration described in the PRD §1.

### 3.2 The Monthly SLA (recurring support)
Following the 30-day post-launch bug-fix support window included in the Project, KWG will provide ongoing monthly Service Level Agreement coverage as set out in Section 4.2, **unless CastraNova opts out** in writing before the included 30-day window ends.

### 3.3 Procurement Services (pass-through)
KWG will procure barcode scanners, a label printer, label rolls, and the first-year Hostinger VPS subscription on CastraNova's behalf as set out in Section 4.3, **subject to vendor-quote confirmation** before any purchase order is placed.

## 4. Detailed Service Streams

### 4.1 The Project

<div class="clause">
<span class="clause-num">4.1.1</span> <strong>Timeline.</strong> KWG will deliver the System within <strong>two to four (2&ndash;4) weeks</strong> of the Effective Date, including a two-week parallel run with CastraNova's existing spreadsheet system and one day of on-site training per office (Bangkok HQ and Yangon warehouse).
</div>

<div class="clause">
<span class="clause-num">4.1.2</span> <strong>Scope.</strong> Bound by the PRD as of 2 June 2026. Any post-signing edit to the PRD does not change the binding scope of this Agreement unless agreed in writing as a change order under Section 13.
</div>

<div class="clause">
<span class="clause-num">4.1.3</span> <strong>30-day post-launch support.</strong> KWG will provide bug-fix support at no additional charge for thirty (30) calendar days following Production Cutover, covering defects traceable to the PRD acceptance criteria. Response SLA: critical issues within one (1) business day, non-critical within five (5) business days.
</div>

### 4.2 The Monthly SLA

<div class="clause">
<span class="clause-num">4.2.1</span> <strong>Start date.</strong> Day thirty-one (31) after Production Cutover.
</div>

<div class="clause">
<span class="clause-num">4.2.2</span> <strong>Fee.</strong> <strong>฿5,000 THB per month</strong>, invoiced on the first day of each calendar month, payable within fourteen (14) calendar days.
</div>

<div class="clause">
<span class="clause-num">4.2.3</span> <strong>Coverage.</strong> Bug-fix support for any defect traceable to the PRD; monthly system health check (logs, backups, hosting status, notification delivery); LINE / Viber bot enrollment for new user accounts; admin runbook updates as the System evolves. Same response SLAs as Clause 4.1.3.
</div>

<div class="clause">
<span class="clause-num">4.2.4</span> <strong>Exclusions.</strong> The SLA does not cover new features or scope changes beyond the PRD (those are change orders under Section 13), hardware repair or replacement (vendor responsibility), or third-party API outages.
</div>

<div class="clause">
<span class="clause-num">4.2.5</span> <strong>Minimum commitment.</strong> Three (3) months once the SLA is activated.
</div>

<div class="clause">
<span class="clause-num">4.2.6</span> <strong>Opt-out.</strong> CastraNova may decline the SLA entirely by written notice to KWG before the included 30-day window under Clause 4.1.3 ends. In that case, post-month-1 support is handled ad-hoc on terms mutually agreed per request before any work starts.
</div>

<div class="clause">
<span class="clause-num">4.2.7</span> <strong>Pause and termination.</strong> After the three-month minimum, either Party may terminate the SLA with thirty (30) calendar days' written notice. CastraNova may also request a one-month pause by providing fourteen (14) days' written notice before that month's billing date; resumption requires written re-activation.
</div>

### 4.3 Procurement Services

<div class="clause">
<span class="clause-num">4.3.1</span> <strong>Reference items.</strong> Bluetooth scanners (TYSSO BCP-2DC, Posiflex CD-3870), label printer (TSC TDP-225), direct thermal label rolls, and Hostinger KVM 8 first-year VPS subscription, per PRD §8.4–8.5 and itemised in Exhibit C (Invoice 002).
</div>

<div class="clause">
<span class="clause-num">4.3.2</span> <strong>Process.</strong> The amounts in Exhibit C are indicative. KWG will obtain live vendor quotes, share them with CastraNova within three (3) business days, and only place purchase orders after CastraNova confirms the firm vendor amounts in writing. The final procurement invoice will match the confirmed vendor amounts.
</div>

<div class="clause">
<span class="clause-num">4.3.3</span> <strong>Pass-through pricing.</strong> KWG procures at vendor cost and charges no margin. Vendor receipts are provided to CastraNova upon procurement completion.
</div>

<div class="clause">
<span class="clause-num">4.3.4</span> <strong>Direct procurement.</strong> CastraNova may elect to procure any item directly from the listed vendor, in which case the item is removed from the procurement invoice. Such election must be notified to KWG before payment of the procurement invoice.
</div>

<div class="clause">
<span class="clause-num">4.3.5</span> <strong>Year-2 hosting.</strong> CastraNova subscribes to Hostinger directly from year two onward. KWG does not invoice for Hostinger renewals.
</div>

<div class="clause">
<span class="clause-num">4.3.6</span> <strong>Hardware warranty.</strong> Warranty, repair, and replacement for all hardware procured under this Section remain the responsibility of the underlying vendor.
</div>

## 5. Fees and Payment

<div class="clause">
<span class="clause-num">5.1</span> <strong>The Project fee.</strong> <strong>$1,000 USD (approximately ฿35,000 THB)</strong>, fixed-price, all-in for the scope in Section 4.1.
</div>

<div class="clause">
<span class="clause-num">5.2</span> <strong>Payment schedule for the Project.</strong> Two milestones:
<ul>
<li><strong>Mobilization &mdash; 50% ($500 USD)</strong>: due upon signature of this Agreement.</li>
<li><strong>Delivery &mdash; 50% ($500 USD)</strong>: due upon Production Cutover.</li>
</ul>
Each milestone is invoiced separately (Invoice KWG-CN-2026-0602-INV-001) and payable within fourteen (14) calendar days of the milestone trigger.
</div>

<div class="clause">
<span class="clause-num">5.3</span> <strong>SLA fee.</strong> As stated in Clause 4.2.2: ฿5,000 THB per month, invoiced monthly.
</div>

<div class="clause">
<span class="clause-num">5.4</span> <strong>Procurement fee.</strong> Pass-through vendor cost, invoiced via Invoice KWG-CN-2026-0602-INV-002 (estimate) and re-issued at firm vendor amounts after the confirmation step in Clause 4.3.2.
</div>

<div class="clause">
<span class="clause-num">5.5</span> <strong>Banking details.</strong> KWG's bank details are provided as a separate scan accompanying the first invoice. Payment by international wire transfer is acceptable.
</div>

<div class="clause">
<span class="clause-num">5.6</span> <strong>Currency.</strong> Project fees are stated in USD; SLA, procurement, and other recurring amounts are in THB. Exchange rate referenced at approximately 35 THB / USD for indicative conversion only; actual rate is determined by the receiving bank at payment time.
</div>

<div class="clause">
<span class="clause-num">5.7</span> <strong>Taxes.</strong> Each Party bears its own taxes arising from its own activities. Any withholding tax imposed by the jurisdiction of CastraNova on payments to KWG, if applicable, shall be deducted from the gross invoice amount and a withholding tax certificate provided to KWG. CastraNova will make commercially reasonable efforts to minimise such withholding.
</div>

## 6. Deliverables and Acceptance

<div class="clause">
<span class="clause-num">6.1</span> Upon completion of the Project, KWG will deliver to CastraNova:
<ul>
<li>The working web application accessible from Bangkok HQ and the Yangon warehouse</li>
<li>All source code transferred to a CastraNova-owned private GitHub repository</li>
<li>Production deployment with HTTPS, daily database backups, and a tested restore procedure</li>
<li>One-time catalog seed import from CastraNova's existing CSV / Excel product list</li>
<li>LINE / Viber bot setup for the first ten user accounts</li>
<li>Bluetooth scanner field tuning on the reference scanner models</li>
<li>Two-week parallel run with existing spreadsheets</li>
<li>One day of on-site training at each office (Bangkok HQ + Yangon warehouse)</li>
<li>An operations runbook covering user onboarding, label-printer setup, and routine admin tasks</li>
<li>30 calendar days of post-launch bug-fix support per Clause 4.1.3</li>
</ul>
</div>

<div class="clause">
<span class="clause-num">6.2</span> <strong>Acceptance.</strong> CastraNova shall have ten (10) business days from Production Cutover to test the System against the PRD acceptance criteria and notify KWG in writing of any non-conformance. If no written non-conformance is received within ten (10) business days, the System is deemed accepted, and the delivery milestone fee becomes due.
</div>

<div class="clause">
<span class="clause-num">6.3</span> <strong>Defect remediation.</strong> Any non-conformance notified within the acceptance window is remediated at no additional charge by KWG. The 30-day post-launch bug-fix window begins on the date of formal acceptance (or deemed acceptance) under Clause 6.2.
</div>

## 7. Term and Termination

<div class="clause">
<span class="clause-num">7.1</span> <strong>The Project term.</strong> Begins on the Effective Date and ends upon the later of (a) acceptance under Clause 6.2 plus the 30-day post-launch support window, or (b) full payment of the Project fee.
</div>

<div class="clause">
<span class="clause-num">7.2</span> <strong>SLA term.</strong> Begins on Day 31 after Production Cutover and continues monthly until terminated under Clause 4.2.7, opted out of under Clause 4.2.6, or terminated under Clause 7.4.
</div>

<div class="clause">
<span class="clause-num">7.3</span> <strong>Procurement Services term.</strong> Concluded upon vendor receipt provision under Clause 4.3.3 for the first-year items.
</div>

<div class="clause">
<span class="clause-num">7.4</span> <strong>Termination for cause.</strong> Either Party may terminate this Agreement, in whole or with respect to a specific service stream, by giving thirty (30) calendar days' written notice for material breach by the other Party that remains uncured during the notice period.
</div>

<div class="clause">
<span class="clause-num">7.5</span> <strong>Termination for convenience by CastraNova.</strong> CastraNova may terminate the Project for convenience by written notice. Settlement covers (a) the mobilization payment in full (non-refundable) and (b) pro-rata payment for work in progress at the date of termination based on KWG's good-faith assessment.
</div>

<div class="clause">
<span class="clause-num">7.6</span> <strong>Effect of termination.</strong> Upon termination, KWG will transfer all work to date to a CastraNova-owned private GitHub repository within five (5) business days. Sections 8 (IP), 9 (Confidentiality), 11 (Limitation of Liability), and 14 (General) survive termination.
</div>

## 8. Intellectual Property

<div class="clause">
<span class="clause-num">8.1</span> <strong>Pre-existing IP.</strong> Each Party retains ownership of all intellectual property it owned prior to the Effective Date and of any pre-existing tools, libraries, or frameworks it brings to the engagement.
</div>

<div class="clause">
<span class="clause-num">8.2</span> <strong>Project IP.</strong> Upon full payment of the Project fee under Clause 5.2, all source code, deployment configuration, designs, documentation, and other deliverables created specifically for CastraNova under the Project ("<strong>Project IP</strong>") shall be assigned to and become the property of CastraNova. Prior to full payment, KWG retains all rights in the Project IP.
</div>

<div class="clause">
<span class="clause-num">8.3</span> <strong>Reuse of generic patterns.</strong> KWG retains the right to reuse, in future engagements, generic architectural patterns, reusable utility functions, and general know-how acquired during the Project, provided that no client-specific business logic, schemas, data, or branding is reused.
</div>

<div class="clause">
<span class="clause-num">8.4</span> <strong>Open-source dependencies.</strong> The System uses open-source software libraries which retain their original licenses. KWG will provide an inventory of such licenses at handover.
</div>

<div class="clause">
<span class="clause-num">8.5</span> <strong>Restriction on onward distribution.</strong> CastraNova may not resell, sublicense, or open-source the Project IP without KWG's prior written consent for twelve (12) months following final acceptance.
</div>

## 9. Confidentiality

<div class="clause">
<span class="clause-num">9.1</span> <strong>Mutual obligation.</strong> Each Party agrees to treat as confidential, and not to disclose to any third party, any non-public information of the other Party that comes to its knowledge during the engagement, including but not limited to business data, customer lists, prices, margins, technical specifications, and commercial terms.
</div>

<div class="clause">
<span class="clause-num">9.2</span> <strong>Exclusions.</strong> The confidentiality obligation does not apply to information that (a) was in the public domain at disclosure, (b) was already known to the receiving Party from a non-confidential source, or (c) is required to be disclosed by law or court order, in which case the receiving Party will give prompt notice to the disclosing Party where lawful.
</div>

<div class="clause">
<span class="clause-num">9.3</span> <strong>Data handling.</strong> KWG accesses CastraNova production data only via the Hostinger VPS owned by CastraNova. KWG retains no copies of production data on its own systems after the Project ends. Staging data used during development is synthetic or anonymised; real customer or supplier data is not loaded into staging without CastraNova's prior approval.
</div>

<div class="clause">
<span class="clause-num">9.4</span> <strong>Survival.</strong> This Section survives termination of the Agreement for three (3) years.
</div>

## 10. Warranties

<div class="clause">
<span class="clause-num">10.1</span> <strong>KWG warranty.</strong> KWG warrants that the System, upon final acceptance under Clause 6.2, will materially perform per the PRD acceptance criteria for ninety (90) calendar days from final acceptance. Within the warranty window, KWG will remedy any non-conformance at no additional charge.
</div>

<div class="clause">
<span class="clause-num">10.2</span> <strong>Warranty exclusions.</strong> The warranty does not cover non-conformance caused by:
<ul>
<li>Hardware failure (scanners, printer, server hardware)</li>
<li>Third-party service outage or behaviour changes (Hostinger, LINE, Viber, label printer drivers, Thai distributors)</li>
<li>CastraNova-side data entry errors</li>
<li>Modifications to the System code by parties other than KWG</li>
<li>Use of the System outside the documented operational scope</li>
</ul>
</div>

<div class="clause">
<span class="clause-num">10.3</span> <strong>No other warranties.</strong> Except as expressly stated in this Section, KWG provides the System on an "as-is" basis. KWG makes no representation that it carries professional indemnity or errors-and-omissions insurance.
</div>

<div class="clause">
<span class="clause-num">10.4</span> <strong>CastraNova warranties.</strong> CastraNova represents that it has full authority to enter into this Agreement, that the data and content it provides to KWG (catalog, customer lists, etc.) are lawfully obtained and CastraNova's to share, and that it will pay all fees due under this Agreement when due.
</div>

## 11. Limitation of Liability

<div class="clause">
<span class="clause-num">11.1</span> <strong>Liability cap.</strong> The total aggregate liability of either Party to the other under or in connection with this Agreement, whether in contract, tort, or otherwise, shall not exceed the total fees actually paid by CastraNova to KWG under this Agreement at the time the liability arises.
</div>

<div class="clause">
<span class="clause-num">11.2</span> <strong>Excluded damages.</strong> Neither Party shall be liable for indirect, consequential, special, punitive, or exemplary damages, including loss of profits, loss of business, or loss of data, however arising.
</div>

<div class="clause">
<span class="clause-num">11.3</span> <strong>Exceptions.</strong> The caps and exclusions in this Section do not apply to liability for (a) breach of confidentiality under Section 9, (b) wilful misconduct or gross negligence, or (c) unpaid fees owed by CastraNova.
</div>

## 12. Force Majeure

<div class="clause">
<span class="clause-num">12.1</span> Neither Party shall be liable for failure or delay in performance caused by events beyond its reasonable control, including but not limited to acts of God, natural disasters, war, civil unrest, government action, regulatory restrictions, prolonged internet or electricity outages exceeding seven (7) consecutive days, or pandemic-related restrictions.
</div>

<div class="clause">
<span class="clause-num">12.2</span> The affected Party shall notify the other Party promptly in writing and use reasonable efforts to mitigate the impact. If a force majeure event continues for more than sixty (60) consecutive days, either Party may terminate the affected service stream by written notice.
</div>

## 13. Change Orders

<div class="clause">
<span class="clause-num">13.1</span> Any change to the PRD scope after the Effective Date follows this process:
<ol>
<li>CastraNova requests the change in writing.</li>
<li>KWG provides a written impact assessment within three (3) business days, covering scope, effort, calendar impact, and a proposed price.</li>
<li>CastraNova approves the proposed price in writing.</li>
<li>KWG begins the work after approval; the change-order amount is invoiced separately.</li>
</ol>
</div>

<div class="clause">
<span class="clause-num">13.2</span> <strong>Pricing.</strong> Each change order is priced by mutual agreement between the Parties — typically as a flat fee per change. No standing day rate is set in advance under this Agreement.
</div>

## 14. Dispute Resolution

<div class="clause">
<span class="clause-num">14.1</span> <strong>Good-faith negotiation.</strong> If a dispute arises between the Parties in connection with this Agreement, the Parties shall first attempt to resolve the dispute through good-faith negotiation between authorised representatives.
</div>

<div class="clause">
<span class="clause-num">14.2</span> <strong>Escalation to mediation.</strong> If the dispute remains unresolved after thirty (30) calendar days of good-faith negotiation, the Parties may mutually agree on the appointment of an independent mediator to assist the resolution. Mediation costs are shared equally.
</div>

<div class="clause">
<span class="clause-num">14.3</span> <strong>No court designation.</strong> The Parties have intentionally not designated a specific court or arbitral forum, given the engagement scale. Should the Parties wish to escalate beyond mediation, they will agree on the forum at that point.
</div>

## 15. General Provisions

<div class="clause">
<span class="clause-num">15.1</span> <strong>Notices.</strong> All formal notices under this Agreement shall be in writing and may be sent by email to the addresses set out in the signature block (or such other address as the recipient designates in writing). Notice is deemed received on the next business day after sending.
</div>

<div class="clause">
<span class="clause-num">15.2</span> <strong>Amendments.</strong> No amendment, modification, or waiver of any provision of this Agreement is effective unless made in writing and signed by both Parties.
</div>

<div class="clause">
<span class="clause-num">15.3</span> <strong>Entire Agreement.</strong> This Agreement, together with Exhibits A, B, and C, constitutes the entire agreement between the Parties with respect to its subject matter and supersedes all prior negotiations, representations, and understandings.
</div>

<div class="clause">
<span class="clause-num">15.4</span> <strong>Severability.</strong> If any provision of this Agreement is held to be invalid or unenforceable, the remaining provisions remain in full force and effect, and the invalid provision shall be modified to the minimum extent necessary to be enforceable while reflecting the original intent.
</div>

<div class="clause">
<span class="clause-num">15.5</span> <strong>Counterparts.</strong> This Agreement may be executed in any number of counterparts and by electronic signature (PDF / DocuSign / equivalent), each of which is deemed an original and which together constitute one and the same instrument.
</div>

<div class="clause">
<span class="clause-num">15.6</span> <strong>No partnership.</strong> Nothing in this Agreement creates a partnership, joint venture, agency, or employment relationship between the Parties.
</div>

<div class="clause">
<span class="clause-num">15.7</span> <strong>Assignment.</strong> Neither Party may assign its rights or obligations under this Agreement without the prior written consent of the other, except that KWG may sub-contract specific technical tasks (e.g. design assistance) with prior written notice to CastraNova, while remaining fully responsible for the Sub-contractor's performance.
</div>

## 16. Exhibits

The following Exhibits are attached to and form part of this Agreement:

| Exhibit | Description |
|---|---|
| **A** | **PRD v3.0** &mdash; [2026-06-02-castranova-pos-v3.0-prd.pdf](pdf/2026-06-02-castranova-pos-v3.0-prd.pdf) (binding scope) |
| **B** | **Quotation v2.0** &mdash; [2026-06-02-castranova-pos-quotation-v2.0.pdf](pdf/2026-06-02-castranova-pos-quotation-v2.0.pdf) (background reference) |
| **C** | **Invoice 001 (Development)** &mdash; [INV-001](pdf/2026-06-02-castranova-pos-invoice-001-development.pdf) and **Invoice 002 (Hardware & Hosting, Estimate)** &mdash; [INV-002](pdf/2026-06-02-castranova-pos-invoice-002-hardware-hosting.pdf) |

## 17. Signatures

**IN WITNESS WHEREOF,** the Parties have executed this Agreement as of the Effective Date.

<div class="signature-block">
  <div class="signature-col">
    <div class="signature-col-label">For Service Provider</div>
    <div style="font-weight: 700; color: var(--primary); margin-bottom: 0.7em;">Wai Phyo Aung trading as K W G</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Signature</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Name (printed): Wai Phyo Aung</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Title: Proprietor</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Date</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Email: waiphyoag.cs34@gmail.com</div>
  </div>
  <div class="signature-col">
    <div class="signature-col-label">For Client</div>
    <div style="font-weight: 700; color: var(--primary); margin-bottom: 0.7em;">CastraNova</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Signature</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Name (printed)</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Title</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Date</div>
    <div class="signature-line"></div>
    <div class="signature-meta">Email</div>
  </div>
</div>

---

*Agreement KWG-CN-2026-0602-MSA-001 · Effective 2 June 2026 · Wai Phyo Aung trading as K W G &harr; CastraNova*
