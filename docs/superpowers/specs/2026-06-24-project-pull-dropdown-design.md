# Project-Pull Create: Dropdown Item Selection (replace scanner)

**Date:** 2026-06-24
**Scope:** Frontend-only. No backend, no migration, no SDK regen.

## Problem

The project-pull *create* screen (`PullCreatePanel`, used by BKK management) adds
items by barcode scan. BKK allocates project stock **remotely** and isn't in the
warehouse, so scanning is impossible. They need to pick items from a dropdown.

## Decision

Replace the `ScanField` in **`PullCreatePanel` only** with a **product dropdown +
quantity stepper**. The warehouse *fulfill* panel (`PullFulfillPanel`) keeps its
scanner — staff are physically present there.

Same picker UX for both tracking modes ("product + count"):

- **QUANTITY product** → one `PART` line with the chosen `requested_qty`.
- **SERIALIZED product** → frontend claims the **N oldest in-stock serials** for
  that product and emits **N `UNIT` lines** (one per serial).

This produces the exact line shapes `buildCreatePayload` and the backend already
accept. **Zero backend change.**

## Why this approach (vs. alternatives)

Considered three options for serialized items:

1. **Request-by-quantity, warehouse assigns serial at fulfillment** — cleaner data
   model, but requires changing `fulfill_project_pull` to claim any available unit.
   That is the append-only / FIFO / consumption path = "high-risk" per CLAUDE.md
   (mandatory FIFO concurrency test + database + security reviewers). Rejected:
   too much surgery on the riskiest path for a remote-UX convenience.
2. **Pick specific units (chosen)** — reuses everything. `GET
   /stock-on-hand/{product_id}/units` (`crud.py:3602`,
   `DashboardsService.getStockOnHandUnits`) already returns in-stock serials,
   oldest-first, for any logged-in user. Fulfillment already consumes those exact
   serials, untouched.
3. **Quantity-only (drop serialized from dropdown)** — too limiting; serialized
   stock is real and plausibly pulled for projects.

The frontend auto-picks the oldest N serials so BKK's UX is still "product + count"
— they never hand-pick a physical serial they can't see. The system's in-stock
list is the source of truth.

## Known ceiling (accepted)

Two concurrent BKK create requests can auto-pick the **same** serial → one of the
resulting `UNIT` lines goes `SHORT` at fulfillment (no substitution). This is the
**same race the scanner flow already tolerates**, and pull creation is low-volume
admin work. **Upgrade path if it ever bites:** move serial-claim to fulfill time
(= option 1's backend change). Not built now. Mark with a `ponytail:` comment at
the auto-pick site.

## Components & data flow

**`PullCreatePanel.tsx`** — remove scanner props/markup (`ScanField`, `scanRef`,
`onScan`, `isSearching`, `notFound`, `isError`, `scanNotice`). Add:

- **Item dropdown** — a `Select` over the existing `products` list (already fetched
  in `pulls.tsx`; `ProductPublic` carries `tracking_mode`, `sku`, `model_name`).
- **Quantity stepper** — reuse the existing `Minus`/`Plus` pattern already in this
  file, or a number input; min 1.
- **"Add" action** — appends to the cart via the existing line logic.

The cart table, qty controls, remove, and "Create request" button stay as-is.

**`pulls.tsx`** — create branch changes:

- Drop the scanner wiring for create mode: the `useScanLookup` result `useEffect`
  keeps only its **fulfill** branch (create no longer routes scans).
- New handler `onAddItem(productId, qty)`:
  - Look up the product in the existing `products`/`createCatalog` maps.
  - **QUANTITY** → build a `PART` `CreateLine` (or merge qty into an existing one),
    reusing `addScanToCreateCart`'s PART branch by synthesizing a `PART`
    `ScanLookupResult`, **or** a small dedicated cart helper in `pull-create.ts`.
  - **SERIALIZED** → `await DashboardsService.getStockOnHandUnits({ productId })`,
    take the oldest `qty` serials, append one `UNIT` `CreateLine` per serial
    (skipping serials already in the cart). If fewer than `qty` available, add
    what's available and surface a notice ("only K in stock").

**`pull-create.ts`** — reuse `addScanToCreateCart` / `CreateLine` shapes. If a
synthesized-scan call site is awkward, add one focused helper (e.g.
`addUnitToCreateCart(lines, {productId, sku, modelName, serial})` and
`addPartToCreateCart(...)`) rather than faking `ScanLookupResult`. Keep
`buildCreatePayload` unchanged.

## Error handling

- Serialized product with **0 in-stock** units → don't add a line; show a notice.
- Fewer than requested in stock → add available, notice the shortfall.
- `getStockOnHandUnits` request failure → notice, no cart mutation.

## Testing

- **Unit (`pull-create.ts`)**: PART add/merge; UNIT add appends N distinct lines;
  re-add skips serials already in cart; `buildCreatePayload` output unchanged for
  both kinds. (One small `*.test.ts` next to existing pure-logic tests.)
- **E2E (Playwright)**: BKK create flow — pick a QUANTITY product + qty → PART line;
  pick a SERIALIZED product + qty → N UNIT lines; submit → request created. Verify
  the scanner is gone from create but present in fulfill.

## Out of scope

- Backend, migrations, SDK regen.
- Fulfill panel (keeps scanner).
- Any change to serial-claim timing (the accepted ceiling above).
