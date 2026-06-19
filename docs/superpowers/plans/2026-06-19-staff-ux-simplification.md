# Staff UX Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the staff-facing screens simpler and guided for non-technical staff — plain-language labels everywhere, and "reduce + reveal" layouts (essentials by default, dense detail behind a toggle) on the three dense screens.

**Architecture:** Frontend only. A new shared display-label module (`lib/labels.ts`) maps internal enum values to plain words; every screen imports it. Source enum/field values (`SERIALIZED`, `FIFO`, `UnitState`, …) and all backend/DB/API/SDK names are unchanged — this is display-only. Search and Stock wrap their existing dense tables in a collapsed `<details>` and add a clean result/summary view above. Pulls is reworded to "Stock requests / Give out parts" with a progress indicator.

**Tech Stack:** React + TypeScript, TanStack Router/Query, shadcn/ui, Tailwind v4. Tests: Playwright (`bunx playwright test`) — pure-logic helpers are tested as `test()` blocks that import the function directly (see `tests/useRole.spec.ts`).

**Spec:** `docs/superpowers/specs/2026-06-19-staff-ux-simplification-design.md`

---

## File Structure

**Create:**
- `frontend/src/lib/labels.ts` — pure display-label functions: `trackingModeLabel`, `unitStatusLabel`, `channelLabel`. One responsibility: map internal enum values → staff-friendly words.
- `frontend/tests/labels.spec.ts` — pure-logic tests for the above.

**Modify:**
- `frontend/src/routes/_layout/search.tsx` — result card + collapsible history; plain labels.
- `frontend/src/routes/_layout/stock.tsx` — slim "Product" table; reworded drill-down.
- `frontend/src/lib/pull-fulfill.ts` — add `fulfilledLineCount` helper (progress indicator).
- `frontend/tests/pull-fulfill.spec.ts` — test the new helper.
- `frontend/src/components/pos/PullQueue.tsx` — "Stock requests" list, plain status, waiting/all toggle.
- `frontend/src/components/pos/PullFulfillPanel.tsx` — "Give out parts" flow, progress, plain labels.
- `frontend/src/routes/_layout/pulls.tsx` — page title/description, friendly scan errors, plain toasts.
- `frontend/tests/pulls.spec.ts` — update assertions for the reworded Pulls flow.
- `frontend/src/routes/_layout/low-stock.tsx` — "Reorder at", plain tracking-mode label, "In stock".
- `frontend/src/routes/_layout/notifications.tsx` — "Send to", `channelLabel`.
- `frontend/src/routes/_layout/tickets.tsx` — "What was done (optional)".
- `frontend/tests/tickets.spec.ts` — update the "Resolution" label assertion.
- `frontend/src/routes/_layout/sale.tsx` — "Shop barcode" wording.

All commands below run from `frontend/`.

---

### Task 1: Shared plain-language label module

**Files:**
- Create: `frontend/src/lib/labels.ts`
- Test: `frontend/tests/labels.spec.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/labels.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

import {
  channelLabel,
  trackingModeLabel,
  unitStatusLabel,
} from "../src/lib/labels"

// Pure-logic coverage of the staff-facing display-label helpers.
// No browser / backend required — mirrors the useRole.spec.ts pattern.

test("trackingModeLabel maps known modes to plain words", () => {
  expect(trackingModeLabel("SERIALIZED")).toBe("Serial-tracked")
  expect(trackingModeLabel("QUANTITY")).toBe("Counted")
})

test("trackingModeLabel returns the raw value for unknown modes", () => {
  expect(trackingModeLabel("WHATEVER")).toBe("WHATEVER")
})

test("unitStatusLabel maps every UnitState to a plain word", () => {
  expect(unitStatusLabel("RECEIVED")).toBe("Just received")
  expect(unitStatusLabel("IN_STOCK")).toBe("In stock")
  expect(unitStatusLabel("SOLD")).toBe("Sold")
  expect(unitStatusLabel("MAINTENANCE_OUT")).toBe("In repair")
  expect(unitStatusLabel("PROJECT_OUT")).toBe("Used on project")
  expect(unitStatusLabel("ADJUSTED_OUT")).toBe("Removed")
})

test("unitStatusLabel humanizes an unknown state instead of showing raw enum", () => {
  expect(unitStatusLabel("SOME_NEW_STATE")).toBe("Some new state")
})

test("channelLabel keeps LINE and title-cases Viber", () => {
  expect(channelLabel("LINE")).toBe("LINE")
  expect(channelLabel("VIBER")).toBe("Viber")
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bunx playwright test tests/labels.spec.ts`
Expected: FAIL — cannot resolve `../src/lib/labels` (module does not exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `frontend/src/lib/labels.ts`:

```ts
/**
 * Staff-facing display labels.
 *
 * Maps internal enum values to plain words for non-technical staff. DISPLAY
 * ONLY — the database, API, and SDK keep their real values (SERIALIZED, FIFO,
 * the UnitState enum, …). These pure functions are unit-tested without React;
 * every staff screen imports from here so the wording stays consistent.
 */

/** Title-case a raw enum value as a readable fallback: FOO_BAR → "Foo bar". */
function humanize(value: string): string {
  const lower = value.replace(/_/g, " ").toLowerCase()
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

/** Product tracking mode → plain word. */
export function trackingModeLabel(mode: string): string {
  switch (mode) {
    case "SERIALIZED":
      return "Serial-tracked"
    case "QUANTITY":
      return "Counted"
    default:
      return mode
  }
}

/** A serialized unit's state → plain status word. */
export function unitStatusLabel(state: string): string {
  switch (state) {
    case "RECEIVED":
      return "Just received"
    case "IN_STOCK":
      return "In stock"
    case "SOLD":
      return "Sold"
    case "MAINTENANCE_OUT":
      return "In repair"
    case "PROJECT_OUT":
      return "Used on project"
    case "ADJUSTED_OUT":
      return "Removed"
    default:
      return humanize(state)
  }
}

/** Notification channel → friendly app name. */
export function channelLabel(channel: string): string {
  switch (channel) {
    case "LINE":
      return "LINE"
    case "VIBER":
      return "Viber"
    default:
      return channel
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bunx playwright test tests/labels.spec.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint**

Run: `bun run lint`
Expected: no errors on the two new files.

- [ ] **Step 6: Commit**

```bash
git add src/lib/labels.ts tests/labels.spec.ts
git commit -m "feat(staff-ux): add shared plain-language label module"
```

---

### Task 2: Search — result card + collapsible history

**Files:**
- Modify: `frontend/src/routes/_layout/search.tsx`

No dedicated E2E spec asserts Search wording (verified: `tests/` has `scanner.spec.ts` and `stock-units.spec.ts`, neither drives `/search`), so verification is the label unit tests (Task 1), the type-check, and lint. Do NOT add a new browser E2E for Search in this task — it would need seeded units + scanning that no existing harness covers.

- [ ] **Step 1: Import the label helpers**

In `search.tsx`, add to the imports (after the `route-guards` import at line 20):

```ts
import { trackingModeLabel, unitStatusLabel } from "@/lib/labels"
```

- [ ] **Step 2: Relabel the page header and tabs**

Replace the `PageHeader` (lines 48–51) and `TabsList` triggers (lines 54–57):

```tsx
      <PageHeader
        title="Search"
        description="Find one item by scanning its barcode, or find a product by its code."
      />

      <Tabs defaultValue="serial">
        <TabsList>
          <TabsTrigger value="serial">Find one item</TabsTrigger>
          <TabsTrigger value="sku">Find a product</TabsTrigger>
        </TabsList>
```

- [ ] **Step 3: Reword the serial scan field + help text**

In `SerialSearch`, replace the `ScanField` + help paragraph (lines 92–103):

```tsx
      <ScanField
        label="Shop barcode"
        placeholder="Scan or type a shop barcode…"
        value={input}
        onValueChange={setInput}
        onScan={setTerm}
        submitLabel="Search"
      />
      <p className="text-muted-foreground text-sm">
        The barcode label we printed and stuck on the unit at receiving — not
        the maker's serial number.
      </p>
```

- [ ] **Step 4: Replace the serial result block with a card + collapsible history**

In `SerialSearch`, replace the success branch — the `<div className="space-y-4">` that starts at line 112 and ends at line 165 (the block rendering the metadata row, "History" heading, and movements table) — with:

```tsx
        <div className="space-y-4">
          <div className="rounded-lg border p-4">
            <div className="num mb-3 text-base font-semibold">{data.sku}</div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt>
              <dd>{unitStatusLabel(data.current_state)}</dd>
              <dt className="text-muted-foreground">Shop barcode</dt>
              <dd className="num">{data.castranova_barcode}</dd>
              <dt className="text-muted-foreground">Maker's serial no.</dt>
              <dd className="num">{data.supplier_serial}</dd>
            </dl>
          </div>

          {data.movements.length === 0 ? null : (
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Show history
              </summary>
              <div className="pt-3">
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
                            : (m.to_location_name ??
                              m.from_location_name ??
                              "—")}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.actor_name ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.reference_label ?? m.reference_kind ?? "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {m.notes ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </details>
          )}
        </div>
```

(The movements table markup is unchanged from the original — only wrapped in a collapsed `<details>` with a clean card above it.)

- [ ] **Step 5: Reword the SKU scan field + help text**

In `SkuSearch`, replace the `ScanField` + help paragraph (lines 194–205):

```tsx
      <ScanField
        label="Product code (SKU)"
        placeholder="Scan or type a product code…"
        value={input}
        onValueChange={setInput}
        onScan={setTerm}
        submitLabel="Search"
      />
      <p className="text-muted-foreground text-sm">
        The product code shared by every unit of this item — the same code shown
        on the Products list.
      </p>
```

- [ ] **Step 6: Replace the SKU result summary row + wrap detail tables in "Show details"**

In `SkuSearch`, replace the metadata row (lines 215–221, the `<div className="flex flex-wrap items-center gap-x-6 gap-y-1">…</div>`) with the plain summary card:

```tsx
          <div className="rounded-lg border p-4">
            <div className="num mb-3 text-base font-semibold">{data.sku}</div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Type</dt>
              <dd>{trackingModeLabel(data.tracking_mode)}</dd>
              <dt className="text-muted-foreground">In stock</dt>
              <dd className="num">{data.total_on_hand}</dd>
            </dl>
          </div>
```

Then wrap the two existing detail blocks (the `Batches` block starting at line 222 `{data.tracking_mode === "QUANTITY" ? (` and the `Consumption` block) so they sit inside one collapsed `<details>`. Immediately AFTER the summary card above and BEFORE the `{data.tracking_mode === "QUANTITY" ? (` line, insert:

```tsx
          {data.tracking_mode === "QUANTITY" ? (
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Show deliveries &amp; history
              </summary>
              <div className="space-y-4 pt-3">
```

…and immediately AFTER the end of the consumption block (the `: null}` that closes the consumption ternary at line 381) and BEFORE the closing `</div>` of the success branch (line 382), insert the matching close:

```tsx
              </div>
            </details>
          ) : null}
```

Within those wrapped blocks, change the two section headings to plain words: `>Batches<` (line 224) → `>Deliveries<`, and leave `>Consumption<` as-is OR rename to `>Where it went<`. Keep the inner tables, `consumptionLabel`, and the admin FIFO-draws `<details>` exactly as they are.

> Note for the implementer: the SKU detail is only rendered for `QUANTITY` products today, so wrapping it in a single `tracking_mode === "QUANTITY"` `<details>` preserves current behavior (serialized SKUs show only the summary card, as before). Keep the existing inner `tracking_mode === "QUANTITY"` guards intact inside the wrapper — they are harmless (always true inside) and avoid reshuffling the consumption IIFE.

- [ ] **Step 7: Type-check and lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit`
Expected: no type errors.
Run: `bun run lint`
Expected: clean.

- [ ] **Step 8: Re-run the label tests (sanity, fast)**

Run: `bunx playwright test tests/labels.spec.ts`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/routes/_layout/search.tsx
git commit -m "feat(staff-ux): Search result card with collapsible history + plain labels"
```

---

### Task 3: Pulls → "Stock requests" + "Give out parts"

**Files:**
- Modify: `frontend/src/lib/pull-fulfill.ts`
- Test: `frontend/tests/pull-fulfill.spec.ts`
- Modify: `frontend/src/components/pos/PullQueue.tsx`
- Modify: `frontend/src/components/pos/PullFulfillPanel.tsx`
- Modify: `frontend/src/routes/_layout/pulls.tsx`
- Test: `frontend/tests/pulls.spec.ts`

#### 3a — Progress helper (TDD)

- [ ] **Step 1: Write the failing test**

Append to `frontend/tests/pull-fulfill.spec.ts` (after the existing tests):

```ts
// --- fulfilledLineCount --------------------------------------------------

test("fulfilledLineCount counts only lines drafted to their full cap", () => {
  const draft = seedFulfillDraft(LINES) // { "line-unit": 0, "line-part": 0 }
  expect(fulfilledLineCount(LINES, draft)).toBe(0)

  const partFull = setLineFulfilledQty(draft, PART_LINE, 3) // cap 3
  expect(fulfilledLineCount(LINES, partFull)).toBe(1)

  const both = { ...partFull, "line-unit": 1 } // UNIT cap 1
  expect(fulfilledLineCount(LINES, both)).toBe(2)
})
```

This reuses the existing `LINES`, `PART_LINE`, `seedFulfillDraft`, and `setLineFulfilledQty` fixtures already defined/imported in that spec. Add `fulfilledLineCount` to the import block at the top of the file (the `from "../src/lib/pull-fulfill"` import).

- [ ] **Step 2: Run the test to verify it fails**

Run: `bunx playwright test tests/pull-fulfill.spec.ts`
Expected: FAIL — `fulfilledLineCount` is not exported.

- [ ] **Step 3: Add the helper**

In `frontend/src/lib/pull-fulfill.ts`, append after `projectedPullState` (after line 92):

```ts
/** How many lines are drafted to their full cap (for the give-out progress). */
export function fulfilledLineCount(
  lines: ProjectPullLinePublic[],
  draft: FulfillDraft,
): number {
  return lines.filter((l) => (draft[l.id] ?? 0) >= lineCap(l)).length
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bunx playwright test tests/pull-fulfill.spec.ts`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add src/lib/pull-fulfill.ts tests/pull-fulfill.spec.ts
git commit -m "feat(staff-ux): add fulfilledLineCount helper for give-out progress"
```

#### 3b — PullQueue (request list)

- [ ] **Step 6: Add a plain status-label map and reword the queue**

In `PullQueue.tsx`, add a status label map next to `STATE_VARIANT` (after line 59):

```ts
const STATE_LABEL: Record<ProjectPullState, string> = {
  PENDING: "Waiting",
  FULFILLED: "Done",
  SHORT: "Short",
  CANCELLED: "Cancelled",
}
```

- [ ] **Step 7: Replace the alert, filter, and "New pull" controls**

Replace the `Alert` block (lines 115–123) with plain copy:

```tsx
      <Alert>
        <ClipboardList />
        <AlertTitle>Stock requests waiting</AlertTitle>
        <AlertDescription>
          These are parts requested for projects. Tap “Give out parts” on a
          request, then scan each part to hand it out.{" "}
          {isAdmin ? "Use “New request” to raise one." : null}
        </AlertDescription>
      </Alert>
```

Replace the filter row (lines 125–147 — the `<div className="flex items-center justify-between gap-4">…</div>` containing the state `Select` and the New-pull `Button`) with a simple waiting/all toggle + reworded create button:

```tsx
      <div className="flex items-center justify-between gap-4">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() =>
            onStateFilterChange(stateFilter === "PENDING" ? "ALL" : "PENDING")
          }
        >
          {stateFilter === "PENDING"
            ? "Show all (incl. completed)"
            : "Show only waiting"}
        </Button>

        {isAdmin ? (
          <Button type="button" onClick={onNew}>
            New request
          </Button>
        ) : null}
      </div>
```

This removes the `Select`/`SelectContent`/`SelectItem`/`SelectValue`/`SelectTrigger` usage and the `PULL_STATE_FILTERS` constant from this component. Delete the now-unused `Select*` import (lines 8–13) and the `PULL_STATE_FILTERS` export/const (lines 27–33). Keep `export type PullStateFilter` (still used by `pulls.tsx`).

- [ ] **Step 8: Reword the empty state, list labels, and action button**

- Empty state (line 150): `No pulls for this filter.` → `No requests to show.`
- Mobile card state badge (line 166): `{pull.state}` → `{STATE_LABEL[pull.state]}`
- Mobile card line count (lines 172–175): replace with `{pull.lines.length} {pull.lines.length === 1 ? "item" : "items"} needed`
- Desktop table headers (lines 193–198): `Project / Customer / Created / Lines / State / Actions` → `Project / Customer / Created / Items / Status / Actions`
- Desktop "Lines" cell stays `{pull.lines.length}`; desktop State cell (lines 216–219): `{pull.state}` → `{STATE_LABEL[pull.state]}`

In `PullActions` (lines 76–83), reword the open button:

```tsx
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onSelect(pull)}
      >
        Give out parts
      </Button>
```

Leave the admin `Cancel` button as-is.

#### 3c — PullFulfillPanel (give-out flow)

- [ ] **Step 9: Import the progress helper**

In `PullFulfillPanel.tsx`, extend the `pull-fulfill` import (lines 18–22) to include `fulfilledLineCount`:

```ts
import {
  fulfilledLineCount,
  type FulfillDraft,
  lineCap,
  projectedPullState,
} from "@/lib/pull-fulfill"
```

- [ ] **Step 10: Add the progress indicator + reword the panel**

In `PullFulfillPanel`, after `const projected = projectedPullState(pull.lines, draft)` (line 69) add:

```ts
  const given = fulfilledLineCount(pull.lines, draft)
  const total = pull.lines.length
  const pct = total === 0 ? 0 : Math.round((given / total) * 100)
```

Change the Back button label (line 74): `Back to queue` → `Back to requests`.

Immediately after the `{projectLabel}` / `{customerLabel}` header `<div>` (closes at line 80) and before the `ScanField`, insert the progress bar:

```tsx
      <div>
        <p className="text-sm font-medium">
          Given out: {given} of {total} {total === 1 ? "item" : "items"}
        </p>
        <div className="bg-muted mt-2 h-2 w-full overflow-hidden rounded-full">
          <div className="bg-cta h-full" style={{ width: `${pct}%` }} />
        </div>
      </div>
```

Reword the offline/non-pending badge (line 110): `This pull is {pull.state}` → `This request is {pull.state.toLowerCase()}`.

Table headers (lines 116–118): `Line / Type / Fulfilled / Requested` → change `Line` to `Item`, keep the type column header but rename to `Kind`, and change the third header to `Given / Needed`.

Replace the projected-state footer (lines 171–176) with plain copy:

```tsx
      <div className="flex items-center justify-end gap-4">
        <span className="text-muted-foreground text-sm">When you finish</span>
        <Badge variant={projected === "FULFILLED" ? "default" : "destructive"}>
          {projected === "FULFILLED" ? "All items ready" : "Some items short"}
        </Badge>
      </div>
```

Reword the submit button (line 184): `{isPending ? "Fulfilling…" : "Fulfill pull"}` → `{isPending ? "Saving…" : "Done — give out parts"}`.

#### 3d — pulls.tsx (page copy, scan errors, toasts)

- [ ] **Step 11: Reword page header, scan-error notices, and toasts**

In `pulls.tsx`:

- `PageHeader` (lines 241–244):

```tsx
      <PageHeader
        title="Stock requests"
        description="Give out parts for project requests."
      />
```

- Create-cart scan notice (line 130): `That item can't be added as a pull line.` → `That item can't be added to this request.`
- Fulfill scan notice (line 138): `Scanned item isn't on this pull.` → `That part isn't on this request — scan a different one.`
- Fulfill success toast (line 167): replace

```ts
      showSuccessToast(`Pull ${pull.state.toLowerCase()}.`)
```

with

```ts
      showSuccessToast(
        pull.state === "FULFILLED"
          ? "Parts given out."
          : "Parts given out — some items still short.",
      )
```

- Fulfill error toast (line 173): `Could not fulfill the pull. Please try again.` → `Could not give out the parts. Please try again.`
- Create success toast (line 185): `Pull created.` → `Request created.`
- Create error toast (line 193): `Could not create the pull. Please try again.` → `Could not create the request. Please try again.`
- Cancel toasts (lines 201, 204): `Pull cancelled.` → `Request cancelled.`; `Could not cancel the pull. Please try again.` → `Could not cancel the request. Please try again.`

#### 3e — Update the Pulls E2E spec

- [ ] **Step 12: Update `tests/pulls.spec.ts` assertions**

Apply these replacements (current text → new text), matching the reworded UI:

- Heading (line 95): `name: "Project pulls"` → `name: "Stock requests"`
- Open button (line 103): `name: "Open"` → `name: "Give out parts"`
- Projected badge (line 115): `page.getByText("SHORT", { exact: true })` → `page.getByText("Some items short")`
- Submit button (line 117): `name: "Fulfill pull"` → `name: "Done — give out parts"`
- Success toast (line 120): `page.getByText("Pull short.")` → `page.getByText("Parts given out — some items still short.")`

Leave the `${fulfilled} / ${requested}` stepper assertion (line 112) unchanged — the per-line stepper still renders `qty / cap`.

- [ ] **Step 13: Type-check, lint, run the Pulls suite**

Run: `bunx tsc -p tsconfig.build.json --noEmit`
Expected: no type errors (confirm no dangling `Select`/`PULL_STATE_FILTERS` references).
Run: `bun run lint`
Expected: clean.
Run: `bunx playwright test tests/pulls.spec.ts tests/pull-fulfill.spec.ts`
Expected: PASS. (Requires the dev stack/backend per the existing E2E setup; if the harness is unavailable, note it and rely on the unit + type-check, then run the full suite at review.)

- [ ] **Step 14: Commit**

```bash
git add src/lib/pull-fulfill.ts src/components/pos/PullQueue.tsx \
  src/components/pos/PullFulfillPanel.tsx src/routes/_layout/pulls.tsx \
  tests/pulls.spec.ts
git commit -m "feat(staff-ux): Pulls becomes Stock requests with a give-out flow"
```

---

### Task 4: Stock — slim "Product" table + reworded drill-down

**Files:**
- Modify: `frontend/src/routes/_layout/stock.tsx`

`tests/stock-units.spec.ts` asserts only the expand button name (`Expand ${sku}`), the unit barcode cell value, and the print-label button name — all unchanged by this task, so that spec stays green. `tests/stock-on-hand.spec.ts` asserts no changed wording.

- [ ] **Step 1: Import the label helpers**

Add after the `stock-on-hand` import (line 31):

```ts
import { trackingModeLabel, unitStatusLabel } from "@/lib/labels"
```

- [ ] **Step 2: Reword the page header + alert**

Replace `PageHeader` (lines 76–79) and the `Alert` description (lines 84–89):

```tsx
      <PageHeader
        title="Stock on hand"
        description="What's in stock right now across the shop."
      />

      <Alert>
        <Warehouse />
        <AlertTitle>Check what's in stock</AlertTitle>
        <AlertDescription>
          Search by name or barcode, or narrow the list with the filters. Tap a
          row to see each delivery or unit. Print shelf or unit labels straight
          from the list.
        </AlertDescription>
      </Alert>
```

Also reword the search input placeholder (line 94): `Search SKU or model…` → `Search by name or barcode…`.

- [ ] **Step 3: Slim the desktop table header**

Replace the desktop `TableHeader` (lines 162–172) — drop the Model, Category, and Mode columns, fold them into one "Product" column:

```tsx
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Product</TableHead>
              <TableHead className="text-right">In stock</TableHead>
              <TableHead className="w-0" aria-label="Labels" />
            </TableRow>
          </TableHeader>
```

- [ ] **Step 4: Slim the desktop row body**

In `StockRow` (lines 326–356), replace the row cells so SKU/Model/Category/Mode collapse into one Product cell and "On hand" → the plain `In stock` column. First, remove `category` from `StockRow`'s destructured params (line ~319) — it is no longer rendered, and strict TS rejects an unused destructured local. Then replace the whole `<TableRow>…</TableRow>` (lines 328–356) with:

```tsx
      <TableRow>
        <TableCell>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
            aria-expanded={isOpen}
            onClick={onToggle}
          >
            {isOpen ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </TableCell>
        <TableCell>
          <div className="font-medium">{modelName}</div>
          <div className="text-muted-foreground num text-xs">
            {sku} · {trackingModeLabel(trackingMode)}
          </div>
        </TableCell>
        <TableCell className="num text-right">{quantityOnHand}</TableCell>
        <TableCell className="text-right">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
        </TableCell>
      </TableRow>
```

- [ ] **Step 5: Fix the expand-row colSpan**

The drill-down row spans the table width. Update the colSpan (line 359) from `7` to `4`:

```tsx
          <TableCell colSpan={4} className="bg-muted/30">
```

- [ ] **Step 6: Reword the mobile card**

In `StockCard` (lines 401–414), replace the `Badge` with quiet type text and change `on hand` → `in stock`:

Replace the header text block (lines 402–407):

```tsx
          <div className="flex items-center gap-2">
            <span className="num font-medium">{sku}</span>
          </div>
          <p className="truncate text-sm">{modelName}</p>
          <p className="text-muted-foreground text-xs">
            {trackingModeLabel(trackingMode)}
          </p>
```

Replace the on-hand caption (line 413): `on hand` → `in stock`.

Also remove `category` from `StockCard`'s destructured params (line ~379) — like `StockRow`, it is no longer rendered and would be an unused local.

> Keep the `StockItemProps.category` field in the interface and the `category={r.category}` props the parent passes (lines 152, 186) — passing a prop the child doesn't destructure is fine, and removing it would churn the interface and both call sites. `trackingMode` stays destructured (now used via `trackingModeLabel`); only `category` is dropped from the two destructures.

- [ ] **Step 7: Reword the drill-down (deliveries + units)**

In `StockDrillDown`:

- Batches table header (line 245): `Batch` → keep; the section is "deliveries" conceptually but headers `Batch / Remaining / Received` read fine — change only `Batch` → `Delivery`.
- Empty batches message (line 238): `No open batches.` → `No deliveries in stock.`
- Units table headers (lines 279–281): `CastraNova barcode` → `Shop barcode`; `Supplier serial` → `Maker's serial no.`; `State` → `Status`.
- Units empty message (line 271): `No units in stock.` → keep.
- Unit state badge (line 294): `{u.current_state}` → `{unitStatusLabel(u.current_state)}`.

- [ ] **Step 8: Type-check and lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit`
Expected: no type errors.
Run: `bun run lint`
Expected: clean.

- [ ] **Step 9: Run the Stock E2E specs (verify still green)**

Run: `bunx playwright test tests/stock-units.spec.ts tests/stock-on-hand.spec.ts`
Expected: PASS (unchanged assertions). If the E2E harness is unavailable, note it and rely on the type-check + lint; the full suite runs at review.

- [ ] **Step 10: Commit**

```bash
git add src/routes/_layout/stock.tsx
git commit -m "feat(staff-ux): slim Stock table to Product + In stock, plain drill-down"
```

---

### Task 5: Wording pass — Low stock, Notifications, Tickets, Sale

**Files:**
- Modify: `frontend/src/routes/_layout/low-stock.tsx`
- Modify: `frontend/src/routes/_layout/notifications.tsx`
- Modify: `frontend/src/routes/_layout/tickets.tsx`
- Test: `frontend/tests/tickets.spec.ts`
- Modify: `frontend/src/routes/_layout/sale.tsx`

- [ ] **Step 1: Low stock — "Reorder at", plain tracking mode, "In stock"**

In `low-stock.tsx`:

- Add the import after `route-guards` (line 24): `import { trackingModeLabel } from "@/lib/labels"`
- `PageHeader` description (line 76): `Products below their reorder threshold.` → `Products that have dropped to their reorder level.`
- Alert title (line 81): keep `Your reorder watchlist`.
- Desktop table header `Tracking` (line 168) → `Type`; header `Min level` (line 170) → `Reorder at`; header `On hand` (line 169) → `In stock`.
- Desktop tracking badge (line 179): `{r.tracking_mode}` → `{trackingModeLabel(r.tracking_mode)}`.
- Mobile tracking badge (line 125): `{r.tracking_mode}` → `{trackingModeLabel(r.tracking_mode)}`.
- Mobile `on hand` caption (line 134) → `in stock`.
- Mobile `Min level` label (line 139) → `Reorder at`.
- The two `aria-label={`Min stock level for ${r.sku}`}` (lines 145, 190) → `aria-label={`Reorder level for ${r.sku}`}`.

- [ ] **Step 2: Notifications — "Send to" + channelLabel**

In `notifications.tsx`:

- Add import after `route-guards` (line 23): `import { channelLabel } from "@/lib/labels"`
- `PageHeader` description (line 68): `Choose which events notify you over LINE / Viber.` → `Choose which events get sent to you on LINE or Viber.`
- Desktop header `Channel` (line 124) → `Send to`.
- Desktop + mobile channel badges (lines 100, 133): `{p.channel}` → `{channelLabel(p.channel)}`.

- [ ] **Step 3: Tickets — "What was done (optional)"**

In `tickets.tsx`, change the resolution field `Label` (line 364): `Resolution (optional)` → `What was done (optional)`.

- [ ] **Step 4: Update the Tickets E2E assertion**

In `tests/tickets.spec.ts` (line 122): `page.getByLabel("Resolution (optional)")` → `page.getByLabel("What was done (optional)")`.

- [ ] **Step 5: Sale — "Shop barcode" wording**

In `sale.tsx`, change the scan help text (lines 261–264):

```tsx
          <p className="text-muted-foreground text-sm">
            Scan the shop barcode on a unit, or a product code (SKU) for
            counted items.
          </p>
```

- [ ] **Step 6: Type-check and lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit`
Expected: no type errors.
Run: `bun run lint`
Expected: clean.

- [ ] **Step 7: Run the Tickets E2E spec**

Run: `bunx playwright test tests/tickets.spec.ts`
Expected: PASS. (If the harness is unavailable, note it and rely on type-check + lint; full suite at review.)

- [ ] **Step 8: Commit**

```bash
git add src/routes/_layout/low-stock.tsx src/routes/_layout/notifications.tsx \
  src/routes/_layout/tickets.tsx tests/tickets.spec.ts src/routes/_layout/sale.tsx
git commit -m "feat(staff-ux): plain-language wording pass on staff screens"
```

---

## Final verification

- [ ] **Full type-check:** `bunx tsc -p tsconfig.build.json --noEmit` → clean.
- [ ] **Full lint:** `bun run lint` → clean.
- [ ] **Full E2E suite:** `bun run test` → green (run against the dev stack per the project's E2E setup; expect the updated `pulls`/`tickets` specs to pass and all others unaffected).
- [ ] **Manual smoke (optional, via the run/verify skill):** log in as a `YGN_STAFF` user and walk Search → Stock → Stock requests to confirm the reduced default views and that "Show history / Show details" reveal the full data.

## Review (per CLAUDE.md §5)

This is display-only and **not** a high-risk (FIFO/ledger/consumption) change, so the mandatory FIFO concurrency test does not apply and `ecc:database-reviewer` / `ecc:security-reviewer` are not required. Before the PR, run `requesting-code-review`; `ecc:react-reviewer` and `ecc:typescript-reviewer` are the relevant specialists. PR targets `dev`.
