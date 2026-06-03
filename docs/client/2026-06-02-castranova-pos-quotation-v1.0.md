# CastraNova POS — Project Quotation

**Quotation Reference:** KWG-CN-2026-0602-Q1
**Date:** 2026-06-02
**Valid until:** 2026-07-02 (30 days)
**Prepared by:** K W G
**Prepared for:** CastraNova (Bangkok HQ + Yangon Warehouse)
**Scope artifact:** PRD v2.6 — [2026-06-02-castranova-pos-v2.6-prd.md](2026-06-02-castranova-pos-v2.6-prd.md)
**Companion artifact:** System Design Spec — [docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md](../superpowers/specs/2026-05-23-castranova-pos-system-design.md)

> **Note for KWG internal review:** This quotation uses indicative rates. Adjust the **Pricing** table to KWG's actual day rate before issuing to CastraNova. All other numbers (calendar weeks, phase split, deliverables) are derived from PRD v2.6 §10 (D37) and stand as-is.

---

## 1. Executive Summary

KWG will design, build, deploy, and support **CastraNova POS v1** — an inventory tracking and channel-margin reporting system covering Bangkok HQ administration and Yangon warehouse operations — per the locked scope in PRD v2.6 (FR-001 through FR-020, Decisions D1–D38).

**Engagement model:** Fixed-price per phase, milestone-billed. Six phases over **24–28 calendar weeks** (~5.5–6.5 months), delivered by a team of **1 senior full-stack engineer + 1 mid-level frontend engineer** working in parallel.

**Total quotation:** **฿2,800,000 THB** (excluding VAT, hardware, and recurring hosting costs — see §6 Exclusions).

**Includes:** all 20 functional requirements, append-only audit trail, offline operation, FIFO costing, LINE + Viber notifications, role-tiered customer/project dashboards, deployment, 2-week parallel run with existing spreadsheets, 1-day training per office, and a 30-day post-launch bug-fix window.

---

## 2. Scope Reference

The complete functional and non-functional scope of this engagement is defined in **PRD v2.6** ([2026-06-02-castranova-pos-v2.6-prd.md](2026-06-02-castranova-pos-v2.6-prd.md)). This quotation is priced against the v2.6 scope **as locked on 2026-06-02**. Any change to PRD v2.6 after this date is a **change order** (see §10) and is billable separately.

**In-scope summary (per PRD v2.6 §5):**

| Area | Requirements |
|---|---|
| Catalog & master data | FR-001 Product catalog · FR-002 Per-product pricing (FIFO) · FR-003 Suppliers/Customers/Projects · FR-004 User & role mgmt |
| Receiving | FR-005 Serialized receipt · FR-006 QUANTITY receipt with FIFO batches |
| Consumption | FR-007 Sale · FR-008 Maintenance · FR-009 Project Pull workflow · FR-010 Pricing overrides |
| Inventory mgmt | FR-011 Stock Adjustment (admin-only) |
| Reports | FR-012 Stock-on-Hand · FR-013 Channel margin · FR-014 Holding period · FR-015 Search · FR-016 Low-stock alerts · FR-017 PDF/Excel exports |
| Notifications | FR-018 LINE + Viber |
| Audit | FR-019 Append-only audit trail |
| Analytics | FR-020 Customer & Project detail dashboards (role-tiered) |

---

## 3. Team & Delivery Model

| Role | Headcount | Allocation | Responsibility |
|---|---|---|---|
| Senior Full-Stack Engineer (Lead) | 1 | 100% | Backend (FastAPI + SQLModel + Alembic), FIFO concurrency design, DB schema, code review, deployment, technical lead on client calls |
| Mid-Level Frontend Engineer | 1 | 100% | React + TanStack PWA, shadcn/ui screens, offline mutation queue, Playwright E2E |
| Project Manager (KWG) | 1 | ~20% | Weekly standups with CastraNova, phase sign-off coordination, change-order log |

**Communication cadence:**
- Weekly 30-min sync with CastraNova (BKK admin + 1 YGN staff rep)
- Mid-phase + end-of-phase demos
- Daily Slack/LINE/email response within 1 business day

**Delivery cadence:**
- Phase work committed to a private GitHub repo accessible to CastraNova on request
- Phase ends with a deployed staging build, demo video, and a sign-off checklist (per PRD v2.6 §13)

---

## 4. Phased Deliverables & Pricing

Phases align to PRD v2.6 §10 (D37). Calendar durations include design, implementation, code review, unit/integration/concurrency tests, and Playwright E2E. **Excludes** client review cycles and scope changes.

| Phase | Scope (FRs delivered) | Calendar | Person-wk | Price (THB) | % |
|---|---|---|---|---|---|
| **1 — Foundation** | FR-001 Catalog · FR-002 Pricing (SERIALIZED part) · FR-003 Master data · FR-004 Auth + role mgmt · FR-005 Serialized receive · FR-007 Sale (online) · FR-012 SoH dashboard (serialized) · PWA shell + offline foundations | 4–5 wk | ~7 | **฿616,000** | 22% |
| **2 — FIFO + Channels** | FR-006 QUANTITY receive (FIFO batches) · FR-002 (QUANTITY part with FIFO splits) · FR-008 Maintenance · FR-009 Project Pull workflow · FR-012 SoH QUANTITY drill-down · FR-013 Monthly margin · FR-016 Low-stock alerts · FR-018 Notifications base · FR-019 Append-only audit | 7–9 wk | ~12 | **฿924,000** | 33% |
| **3 — Controls & Reports** | FR-010 Pricing override approval · FR-011 Stock Adjustment · FR-014 Holding-period report · FR-015 Search & lookup · FR-017 PDF + Excel exports (all views) · Override exception report · Adjustments history | 3–4 wk | ~5 | **฿392,000** | 14% |
| **4 — Analytics** | FR-020 Customer detail dashboard · FR-020 Project detail dashboard · Pull history view · Per-batch drill in search · Role-tiered Pydantic schemas | 3 wk | ~4 | **฿336,000** | 12% |
| **5 — Go-Live** | Hostinger VPS provisioning · Traefik + Let's Encrypt · `pg_dump` cron + restore drill · Sentry wiring · Initial catalog seed import · LINE/Viber bot enrollment for first 10 users (D33) · BT scanner field tuning (D34) · 2-week parallel run with existing spreadsheets (D38) · 1-day on-site training per office (BKK + YGN) (D38) | 3–4 wk | ~3 | **฿392,000** | 14% |
| **6 — Post-Launch Support** | 30 calendar days of bug-fix-only support. Critical fixes within 1 business day, non-critical within 5 business days. Excludes new features or scope changes (those are change orders). | 4 wk calendar | ~1 | **฿140,000** | 5% |
| **Total** | All FR-001 → FR-020 + deployment + pilot + training + 30-day fix window | **24–28 wk** | **~32** | **฿2,800,000** | **100%** |

**Indicative blended day rate:** ~฿17,500 / person-day (senior + mid blended, including PM + overhead + KWG margin).
**To adjust before issuing:** if KWG's actual blended day rate is X, multiply all phase prices by `X / 17500`.

---

## 5. Payment Schedule

| Milestone | Trigger | % | Amount (THB) |
|---|---|---|---|
| **Mobilization** | Contract + PRD v2.6 sign-off | 10% | ฿280,000 |
| **Phase 1 acceptance** | Staging demo + §13 sign-off checklist | 17% | ฿476,000 |
| **Phase 2 acceptance** | Staging demo + §13 sign-off checklist | 28% | ฿784,000 |
| **Phase 3 acceptance** | Staging demo + §13 sign-off checklist | 12% | ฿336,000 |
| **Phase 4 acceptance** | Staging demo + §13 sign-off checklist | 10% | ฿280,000 |
| **Phase 5 go-live** | Production cutover + start of parallel run | 13% | ฿364,000 |
| **Final acceptance** | End of 30-day support window | 10% | ฿280,000 |
| **Total** | | **100%** | **฿2,800,000** |

**Terms:**
- Invoices issued upon milestone completion; payable net 14 days.
- Late payments accrue 1.5% / month interest after 30 days.
- Payment in THB to a KWG-nominated bank account; SWIFT/TT fees borne by CastraNova for non-Thai transfers.

---

## 6. What's NOT Included (Exclusions)

### 6.1 Client-supplied (CastraNova responsibility)
- **Hardware:** Bluetooth barcode scanners (reference models: Honeywell Voyager 1602g, Zebra DS2208 — per PRD D34), label printer (Brother QL-820NWB or Zebra ZD220 recommended), warehouse phones, BKK desktops/laptops.
- **Hosting:** Hostinger VPS Singapore (KVM 4 or equivalent — ~$20–40 USD/month). KWG will help with initial provisioning but ongoing subscription is CastraNova's.
- **Domain & SSL:** Domain registration (e.g., `pos.castranova.com`). SSL cert is auto-provisioned via Let's Encrypt (no separate cost).
- **LINE Messaging API channel + Viber Bot account:** Free tier sufficient at v1 volume; CastraNova owns the accounts and channel access tokens.
- **Existing catalog:** CSV/XLSX of current product list, supplier list, customer list, active projects for one-time seed import.
- **Tax invoicing tool:** Existing accounting tool (per PRD §9 out-of-scope).

### 6.2 KWG-out-of-scope (per PRD v2.6 §9)
- Customer-facing legal tax documents · Warranty tracking · Labor charges on repairs · BKK warehouse / in-transit tracking · Machine returns to warehouse · Multi-currency · Customer self-service portal · Native mobile app · Real-time multi-user live updates · Accounting tool integration · Multi-language UI · Staff scrap workflow · Machine-swap → original-sale data-model linkage · Staff-initiated Project consumption · On-site consumption recording · Returns-to-stock workflow · Weighted-average cost.

### 6.3 Deferred to v1.1 (separate engagement)
- **Admin customer-merge tool** for duplicate-customer reconciliation (D35).
- **Browser-side IDB encryption** (D32 — if CastraNova security policy later requires it).
- **Stock-out incident dashboard view** as a first-class report.
- **Bulk catalog re-import** beyond the v1 seed.
- **24×7 support or SLA tier.** Post-launch support beyond the 30-day window requires a retainer (see §9).

---

## 7. Assumptions

This quotation is built on the following assumptions. A material change to any of them is a change order.

1. **PRD v2.6 is the locked scope** as of 2026-06-02. No mid-flight FR additions.
2. **CastraNova provides the existing product catalog** (CSV/XLSX) within the first 2 weeks of Phase 1.
3. **CastraNova nominates a primary product owner** (BKK admin) available for ≤4h/week of review + sign-off.
4. **CastraNova provides BKK admin and YGN staff for testing** the staging build during the last week of each phase.
5. **CastraNova procures the reference Bluetooth scanners** (Honeywell 1602g and/or Zebra DS2208) at least 2 weeks before Phase 5 cutover.
6. **CastraNova procures the label printer** at least 2 weeks before Phase 1 cutover.
7. **CastraNova provides the Hostinger VPS** (KVM 4 or equivalent, Singapore region) at the start of Phase 5.
8. **CastraNova users are reachable on LINE and/or Viber** for the one-time bot enrollment during Phase 5.
9. **Phase sign-off occurs within 5 business days** of demo. Delayed sign-off does not delay invoicing.
10. **CastraNova absorbs ongoing recurring costs** (VPS, domain, LINE/Viber if exceeding free tier).

---

## 8. Hardware & Recurring Cost Estimates (Client-Owned)

Indicative — confirm with vendor:

| Item | Est. cost | Frequency | Owner |
|---|---|---|---|
| Honeywell Voyager 1602g BT scanner × 2 | ฿4,500 each | One-time | CastraNova |
| Zebra DS2208 BT scanner × 1 | ฿7,000 | One-time | CastraNova |
| Brother QL-820NWB label printer | ฿9,500 | One-time | CastraNova |
| 4×6 in label rolls (DK-1241, 200 ct) | ฿800 / roll | Consumable | CastraNova |
| Hostinger VPS KVM 4 (Singapore) | ฿1,400 / month | Recurring | CastraNova |
| Domain (`pos.castranova.com` or similar) | ฿500 / year | Recurring | CastraNova |
| LINE Messaging API | Free tier (500 push msgs/month free) | Recurring | CastraNova |
| Viber Bot API | Free | Recurring | CastraNova |
| **One-time hardware total** | **~฿25,500** | — | CastraNova |
| **Recurring annual ops** | **~฿17,300 / year** | — | CastraNova |

---

## 9. Post-Launch Support

### 9.1 Included (Phase 6 — first 30 calendar days post go-live)
- Bug fixes for issues traceable to the v2.6 scope.
- Hot-fix deployment via the same Hostinger pipeline.
- SLA: critical (system unavailable, data loss) — response within 4h, fix within 1 business day. Non-critical — response within 1 business day, fix within 5 business days.

### 9.2 Beyond Phase 6 (optional retainer)
Available as separate add-ons:

| Option | What | Price |
|---|---|---|
| **A. Pay-as-you-go** | Bug fix + small enhancement at KWG day rate | **฿17,500 / person-day** (4h minimum) |
| **B. Monthly retainer (Light)** | 8 person-hours / month — bug fix + minor tweaks. Unused hours expire monthly. | **฿20,000 / month** (3-month minimum) |
| **C. Monthly retainer (Pro)** | 24 person-hours / month — bug fix + enhancements + monthly health check. Unused hours roll up to 8h into next month. Priority response. | **฿55,000 / month** (3-month minimum) |
| **D. v1.1 engagement** | Customer merge tool + stock-out dashboard view + any deferred items. Separately quoted on signed scope. | T&M or fixed-price per scoped item |

---

## 10. Change Orders

Any change to PRD v2.6 scope after 2026-06-02 follows this process:

1. CastraNova requests a change (email or in the weekly sync).
2. KWG provides a written impact assessment within 3 business days: incremental person-days, calendar impact, price delta.
3. CastraNova signs off the change order in writing.
4. KWG begins work after sign-off.
5. Change orders are billed at **฿17,500 / person-day** (same as retainer rate Option A) or as a fixed-price addendum, at CastraNova's choice.

**Material changes that trigger a re-baseline** (rather than a change order):
- > 15% scope expansion (additional FRs adding ~3+ person-weeks)
- Hard timeline compression (>20% calendar reduction)
- Stack change (e.g., from FastAPI to a different backend)

---

## 11. Warranty

- KWG warrants the delivered software to perform per the PRD v2.6 acceptance criteria (§13) for **90 days post final acceptance**.
- Within the warranty window, KWG will fix defects (deviations from PRD acceptance criteria) at no charge.
- Warranty excludes: defects caused by hardware failure, infrastructure outage, third-party API changes (LINE, Viber, Hostinger), CastraNova-side data corruption, or unauthorized code modifications.

---

## 12. Intellectual Property

- All source code and deliverables become CastraNova's property upon **final payment** of the engagement total.
- Until final payment, KWG retains all IP rights to all code, designs, and documentation.
- KWG retains the right to reuse generic patterns (architectural approaches, reusable utilities) in future engagements; **no client-specific business logic, schemas, or data is reused.**
- Open-source dependencies retain their original licenses; KWG provides an OSS license inventory at handover.
- Client may not resell, sublicense, or open-source the deliverables without KWG's written consent (for 12 months post-handover).

---

## 13. Confidentiality & Data Handling

- KWG treats all CastraNova business data (catalog, customer lists, prices, margins) as confidential.
- KWG accesses production data only via the Hostinger VPS owned by CastraNova; no copies retained on KWG hardware after the engagement ends.
- Staging data used during development is synthetic or anonymized; real customer/supplier data is not loaded into staging without CastraNova approval.
- A standard mutual NDA can be attached on request.

---

## 14. Termination

- **For cause (either party):** 30 days written notice for material breach uncured within the notice period. Settlement covers work-completed-to-date at the phase pro-rata price.
- **For convenience (CastraNova):** 60 days written notice. Settlement covers (a) all completed phases at the full phase price, plus (b) work-in-progress in the current phase at 50% of that phase's price.
- **Source code transfer on termination:** KWG transfers all work-to-date in a private GitHub repo handover, regardless of cause, within 5 business days of effective termination.

---

## 15. Quotation Validity & Acceptance

- This quotation is valid for **30 days** from the date above (2026-06-02 → 2026-07-02).
- Acceptance: sign-and-date a copy of this document, or issue a purchase order referencing **KWG-CN-2026-0602-Q1**.
- Engagement starts on the first business day after KWG receives (a) signed acceptance + (b) mobilization payment.

---

## 16. Signatures

**For K W G:**

Name: ______________________
Title: ______________________
Signature: ______________________
Date: ______________________

**For CastraNova:**

Name: ______________________
Title: ______________________
Signature: ______________________
Date: ______________________

---

*This quotation incorporates PRD v2.6 (locked 2026-06-02) and the System Design Spec by reference. In case of conflict between this quotation and PRD v2.6, PRD v2.6 governs scope; this quotation governs commercial terms.*
