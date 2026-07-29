# Open issues — 2026-07-29

Reported after manual verification of `dev_wth`. Each entry records what was
**verified in code or data**, not just the symptom. Ordered by severity.

---

## 1. Refresh-token 401 storm — logs the user out and floods the API ⚠️ HIGHEST

**Symptom.** `POST /api/v1/login/refresh-token` returns **401**, and the app
retries in a tight loop: `channel-margin` ×2 → `me` → `refresh-token`, repeating.
DevTools recorded **862 / 6351 requests** on one page.

**Verified.**
- `backend/app/api/routes/login.py:83` returns 401 for a missing/invalid/
  non-`refresh` cookie — the backend behaviour is correct on its own.
- `frontend/src/lib/auth-session.ts` looks right in isolation: single-flight
  refresh (`inFlight`), an `_authRetried` guard, and auth endpoints excluded
  from the interceptor.
- **`frontend/src/lib/query-client.ts` sets no `retry` option**, so TanStack
  Query's default (3 retries with backoff) applies to every query. Each retry
  re-triggers the 401 → refresh path, multiplying requests.
- Corroborated by the E2E run: **51 occurrences of `navigated to
  "http://127.0.0.1:5173/login"`** mid-suite, and 28 test failures that are
  mostly downstream of being logged out (see §7).

**Not yet root-caused.** The interceptor and `endSession()` logic read as
correct, so the loop is not explained by the code alone — needs reproduction.
Leads worth pulling:
- Why the refresh cookie is rejected in the first place (expiry? `SameSite`?
  cookie not sent on the XHR? rotation losing it?).
- Whether `endSession()`'s `window.location.href = "/login"` is being
  short-circuited or outrun by in-flight queries.
- Whether an explicit `retry: false` for 401s would stop the amplification
  even before the root cause is found (mitigation, not a fix).

---

## 2. Serialized item is offered as a PART line on the Sale page

**Verified — root cause found.** `frontend/src/hooks/useScanLookup.ts:44`
classifies **any** SKU hit as `PART`:

```ts
if (!(skuOutcome instanceof ApiError)) {
  return { kind: "PART", data: skuOutcome }   // never checks tracking_mode
}
```

`crud.search_sku` matches a product by SKU **regardless of tracking mode** and
returns `tracking_mode` in the payload — so scanning a SERIALIZED product's SKU
(rather than its unit barcode) resolves to a PART line. The backend then rejects
it with 400 *"PART line requires a QUANTITY-tracked product"*.

**Fix direction.** In `resolveScanResult`, treat a SKU hit whose
`tracking_mode === "SERIALIZED"` as its own outcome, and have the Sale page tell
the operator to scan the unit barcode instead. The data needed is already in the
response — no API change.

---

## 3. Low-stock alerts never fire for most products

**Verified — root cause found.** `backend/app/crud.py:1213`:

```python
threshold = product.default_min_stock_level if product else None
if threshold is not None and after < threshold:
```

`Product.default_min_stock_level` is `Field(default=None)`
(`models.py:480`), so **any product without an explicit threshold never alerts,
at any stock level** — including zero.

**Confirmed against dev data** (`select default_min_stock_level, count(*) from product group by 1`):

| default_min_stock_level | products |
|---|---|
| NULL | 6 |
| 10 | 1 |
| 5 | 1 |

Six of eight products can never raise a low-stock alert. This matches the
reported "only fires on 0 stock" — the only products that alert are the two with
a threshold set.

**Decision needed:** a system-wide default threshold, a required field at
product creation, or treat `NULL` as `0` and alert on stockout. This is a
product call, not just a code fix.

---

## 4. Returns: sale dropdown renders before a SKU is entered

**Verified** in `frontend/src/routes/_layout/stock-adjustment.tsx` (my code —
introduced with the returns feature). The label and `Select` render whenever the
Return action is active, so with an empty SKU the operator sees an empty
dropdown. The "nothing can be returned" message only appears once a SKU has been
typed *and* the query has resolved empty.

**Wanted behaviour.**
- SKU empty → render neither the label nor the dropdown.
- SKU entered, results exist → render label + dropdown.
- SKU entered, no results → render a clear "no sales to return for this SKU"
  message instead of an empty dropdown.

---

## 5. Returns: quantity input accepts invalid values

**Verified** in the same file. The quantity `Input` is free text
(`inputMode="numeric"` is a keyboard hint only, not a constraint). Zero,
negatives, decimals and values above the cap can all be typed. `canSubmitReturn`
blocks submission, so nothing invalid reaches the API — but the field should not
accept them in the first place.

**Wanted behaviour.** Constrain input to positive integers, upper-bounded by the
`N` already shown in *"Up to N can still be returned from this sale line."*

---

## 6. Project dialogs autofocus the Name field

**Verified.** Radix `DialogContent` focuses the first focusable element on open,
so the Project create/edit dialogs land on **Project name**.

**The pattern already exists elsewhere** — `EditProductDialog.tsx:187` and
`ProductCreateDialog.tsx:136` both pass `onOpenAutoFocus` to suppress it. The
project dialogs (`ProjectCreateDialog.tsx`, `ProjectEditDialog.tsx`) simply never
got the same treatment. Mirror it.

---

## 7. E2E suite: 28 failures, largely downstream of §1

**Run:** full suite on an isolated stack (own DB, `E2E_SKIP_DB_RESET=1`),
`306/306` executed, **28 failed**.

Affected specs: `admin`, `channel-margin-drilldown`, `product-active-toggle`,
`product-dialog-focus`, `product-edit-flow`, `product-filters`,
`project-edit-flow`, `reset-password`, `roles`, `sale`, `sale-return`,
`stock-supplier-filter`, `stock-units`, `supplier-edit-flow`.

**Do not triage these as 14 separate bugs.** 51 log entries show tests being
navigated to `/login` mid-run, and the failures are overwhelmingly
`locator.click` / `locator.fill` timeouts *after* that bounce — i.e. the page
was logged out, not broken. Fix §1 first, then re-run and re-triage whatever
survives.

Two known-independent items in that list:
- `project-edit-flow.spec.ts` was already broken before this work — its
  customer-create form moved behind a dialog.
- `sale-return.spec.ts` (2 failures) had never been executed before today; its
  selectors were desk-checked against the committed UI but are unproven until
  a run gets past the auth problem.

---

## Already fixed today

- **E2E user-dialog selectors** (`4d07887`) — `admin.spec.ts` / `roles.spec.ts`
  had queried placeholder copy changed by `8a90516` on **2026-06-19**, so 28 call
  sites had been timing out for over a month. The suite had not passed since.

## Environment notes

- `docker compose build` failed intermittently on
  `ghcr.io/astral-sh/uv:0.9.26` (registry blob EOF). It recovered on retry.
- The Playwright image **bakes `./frontend` in at build time**, so spec edits
  need `docker compose build playwright` before `run`. The backend gets live
  source via a volume mount; the frontend does not.
