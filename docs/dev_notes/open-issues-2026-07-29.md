# Open issues — 2026-07-29

Reported after manual verification of `dev_wth`. Each entry records what was
**verified in code or data**, not just the symptom. Ordered by severity.

**Status — all closed as of 2026-08-02.** §1, §2, §4, §5, §6 fixed; §3 closed as
**not a defect** (the behaviour is intended and test-locked); §7 resolved to
zero surviving failures. The §7 re-triage turned up one issue that was *not* in
the original report — see **§8**, a real bug that broke every emailed
password-reset link.

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

**ROOT-CAUSED AND FIXED — 2026-08-01.** Two independent defects, not one.

**(a) Why the refresh cookie is rejected: the page origin and the API origin
were cross-site.** A browser probe against the exact `Set-Cookie` header
`_set_refresh_cookie` emits shows the cookie is not merely withheld on send —
Chrome **never stores it at all** when the origins are cross-site:

| page | api | cross-site | cookie stored | refresh |
|---|---|---|---|---|
| `localhost:5173` | `localhost:8000` | no | yes | 200 |
| `127.0.0.1:5173` | `localhost:8000` | **yes** | **no** | **401** |
| `localhost:5173` | `127.0.0.1:8000` | **yes** | **no** | **401** |
| `127.0.0.1:5173` | `127.0.0.1:8000` | no | yes | 200 |

So refresh 401s from the first second of the session, not after 15 minutes.
E2E hit this by construction (`playwright.config.ts` pins `127.0.0.1:5173`,
`compose.e2e.yml` points the bundle at `backend:8000`), and so does anyone
browsing dev on `127.0.0.1:5173`. **Production is unaffected** —
`castranova.nexuslab.asia` and `api.castranova.nexuslab.asia` share a
registrable domain, so they are same-site.

*Fix:* the Vite dev server now proxies `/api` to the backend
(`vite.config.ts`), and `lib/api-base.ts` makes every browser-side call
same-origin in dev/E2E while production keeps the absolute `VITE_API_URL`.
`auth-session.spec.ts` consequently tests the **real** cookie exchange; it
previously had to mock `/login/refresh-token` to work around this very bug.

**(b) The amplifier — two multiplying bugs, both real.**
- `query-client.ts` set no `retry`, so TanStack's default 3 retries applied to
  every query, and `QueryCache.onError` (→ `endSession`) only fires after the
  last one — delaying logout by the whole backoff while queries kept firing.
- `auth-session.ts`'s single-flight guard cleared on settle, so it only ever
  collapsed *concurrent* callers. Sequential retries each started a **new**
  refresh against a session that could never come back.

*Fix:* `shouldRetryRequest` never retries 401/403; `refreshAccessToken` latches
a dead session on a 401 and answers later callers locally (a 429/5xx/offline
failure stays retryable). Re-armed by `markSessionAlive()` on login.

*Measured:* the new `a dead session costs ONE refresh attempt, not a storm`
E2E test, run against unmodified `HEAD`, records **5 refresh calls over 9.4s**
and the app sits on `/channel-margin` still hammering before it logs out.
Fixed: **1 call, 586 ms**. The reload path was never the storm — the boot check
in `main.tsx` ends the session before a query mounts; it takes a *mid-session*
death (client-side refetch) to reproduce.

---

## 2. Serialized item is offered as a PART line on the Sale page — ✅ FIXED

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

**FIXED — 2026-08-01.** `useScanLookup` gained a `SERIALIZED_SKU` outcome, and
all four consumers handle it: `sale.tsx:141`, `pulls.tsx:133`, `tickets.tsx:137`,
`sale-cart.ts:63`. Covered by `useScanLookup.test.ts`.

---

## 3. Low-stock alerts never fire for most products — ✅ NOT A DEFECT

**Closed 2026-08-02.** The code below is doing exactly what it was written and
tested to do; see the verdict at the end of this section. Original analysis kept
for the record.

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

Six of eight products can never raise a low-stock alert.

**Verdict — this was never a bug.** A NULL threshold means *"no threshold
configured"*, and you cannot be below a threshold nobody set. The behaviour is
deliberate and locked by an existing test —
`backend/tests/api/routes/test_low_stock.py:530`,
**`test_null_threshold_never_alerts`** — which builds a product with
`min_level=None`, stocks it to 6, sells 5, and asserts no low-stock log is
written. `list_low_stock` filters `is_not(None)` for the same reason. Low-stock
alerting is **opt-in per product**, and `default_min_stock_level` is the opt-in.

So the finding above restates how the catalog is *configured* (six products have
not opted in), not a code defect. Nothing to fix.

**One loose thread, if the original report is taken literally.** The report said
alerts fire "only at 0 stock". The six NULL products explain products that never
alert — but they do *not* explain the two products that **do** have thresholds
(10 and 5) allegedly alerting at zero rather than at their threshold. If that
part of the report was precise, it is a separate question worth a targeted
check; if it was shorthand for "most products never alert", it is fully
explained above.

---

## 4. Returns: sale dropdown renders before a SKU is entered — ✅ FIXED

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

**FIXED — 2026-08-01.** The label moved inside the branch that renders the
`Select`, so an empty SKU renders neither.

---

## 5. Returns: quantity input accepts invalid values — ✅ FIXED

**Verified** in the same file. The quantity `Input` is free text
(`inputMode="numeric"` is a keyboard hint only, not a constraint). Zero,
negatives, decimals and values above the cap can all be typed. `canSubmitReturn`
blocks submission, so nothing invalid reaches the API — but the field should not
accept them in the first place.

**Wanted behaviour.** Constrain input to positive integers, upper-bounded by the
`N` already shown in *"Up to N can still be returned from this sale line."*

**FIXED — 2026-08-01.** A `clampReturnQuantity(value, quantity_returnable)`
helper in `sale-return.ts` filters the value on every keystroke; unit-tested in
`sale-return.test.ts`.

---

## 6. Project dialogs autofocus the Name field — ✅ FIXED

**Verified.** Radix `DialogContent` focuses the first focusable element on open,
so the Project create/edit dialogs land on **Project name**.

**The pattern already exists elsewhere** — `EditProductDialog.tsx:187` and
`ProductCreateDialog.tsx:136` both pass `onOpenAutoFocus` to suppress it. The
project dialogs (`ProjectCreateDialog.tsx`, `ProjectEditDialog.tsx`) simply never
got the same treatment. Mirror it.

**FIXED — 2026-08-01.** Both dialogs now `preventDefault()` in
`onOpenAutoFocus` and focus the dialog content instead. Covered by
`project-dialog-focus.spec.ts`.

---

## 7. E2E suite: 33 failures, largely downstream of §1 — ✅ RESOLVED

**Run:** full suite on an isolated stack (own DB, `E2E_SKIP_DB_RESET=1`).
Final tally: **33 failed, 1 flaky, 272 passed** in 40.8 min.

| Spec | Failures |
|---|---|
| `sale.spec.ts` | 5 |
| `reset-password.spec.ts` | 5 |
| `user-settings.spec.ts` | 3 |
| `supplier-edit-flow.spec.ts` | 3 |
| `channel-margin-drilldown.spec.ts` | 3 |
| `tickets.spec.ts` | 2 |
| `stock-supplier-filter.spec.ts` | 2 |
| `sale-return.spec.ts` | 2 |
| `roles.spec.ts` | 2 |
| `stock-units`, `project-edit-flow`, `product-filters`, `product-edit-flow`, `product-dialog-focus`, `product-active-toggle`, `admin` | 1 each |

**Do not triage these as 16 separate bugs.** **66** log entries show tests being
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

**RESOLVED — 2026-08-01/02.** Confirming full run on the isolated stack:
**308 passed, 1 flaky, 0 failed in 4.1 min** (the flaky —
`user-settings › Update password successfully` — passed on retry). Note the
wall-clock: 40.8 min → **4.1 min**. The suite was not slow, it was spending its
time in 401 retry storms and post-logout locator timeouts.

The prediction held: 23 of 33 were pure fallout from §1 and went away with that
fix alone. Full accounting of the original 33:

| Cause | Count | Nature |
|---|---|---|
| §1 refresh-token storm | 23 | app bug (fixed) |
| `Retail price` → `Project price` label rename (`de8857d`, 2026-07-24) | 4 | stale selector |
| Customer form moved behind a dialog | 1 | stale selector |
| Supplier scope moved out of the column header | 1 | stale selector |
| Superuser control removed from Add User | 1 | obsolete test — deleted |
| Public auth routes bounced to `/login` | 3 | **app bug — see §8** |

Only **two** of the 33 were real application defects (§1 and §8). The other
eight were test debt: assertions still describing a UI that had moved on.

Fixes applied to the suite itself:
- `product-dialog-focus`, `product-active-toggle`, `product-filters`,
  `product-edit-flow` (×2) — `"Retail price (THB)"` → `"Project price (THB)"`.
- `project-edit-flow` — create the customer through the `New customer` dialog;
  scope the project combobox to the dialog.
- `stock-supplier-filter` — assert on the `Showing stock from: <supplier>`
  banner plus a plain `In stock` column header, not a supplier-named header.
- `admin.spec.ts` — the "Create a superuser" test was deleted, not repaired:
  the Add User form no longer exposes a superuser control, so the test asserted
  behaviour the product had deliberately removed.
- `compose.e2e.yml` — `SMTP_TLS: "false"`. `compose.override.yml` is **not**
  auto-loaded when files are passed with explicit `-f`, so the E2E backend was
  inheriting `SMTP_TLS=True` from `.env` and every send to plain-SMTP
  mailcatcher failed. Independently necessary, but *not* the cause of the
  reset-password failures — those never reached the API at all (§8).

---

## 8. Every emailed password-reset link was dead ⚠️ (found during §7 re-triage)

**Not in the original report** — surfaced by the three `reset-password.spec.ts`
failures that survived the §1 fix.

**Symptom.** A logged-out user who opened the reset link from their email landed
on `/login`. The token in the URL was discarded, so password reset was
unusable for exactly the people who need it.

**Root cause.** `main.tsx` runs a boot session check on load and calls
`endSession()` when it fails. It was guarded only against `/login`:

```ts
if (navigator.onLine && !window.location.pathname.startsWith("/login")) { … }
```

`/recover-password` and `/reset-password` are reached with **no session by
definition**, so the check failed, `endSession()` fired, and the browser was
sent to `/login` — throwing away `?token=…` on the way.

**Why it was invisible in manual testing.** Module-level boot code runs only on
a **hard page load**, never on an SPA soft navigation. Clicking *"Forgot
password?"* from the login screen is a soft navigation, so the flow worked
perfectly by hand. Only the emailed link — always a hard load — hit the bug.
That is also why a live refresh cookie masked it: with a valid session the check
passes and nothing redirects.

**Fix.** `PUBLIC_PATHS` + `isPublicAuthPath()` in `lib/auth-session.ts`, used in
two places: `main.tsx` skips the boot check on any public auth route, and
`endSession()` refuses to redirect away from one (so a mid-reset 401 cannot
discard the token either).

**Regression test.** `reset-password.spec.ts` — *"a hard load of a public auth
route is not bounced to /login"* hard-loads `/recover-password` and
`/reset-password?token=…` and asserts neither ends up on `/login`. The
end-to-end email-link test passes alongside it, which also proves the
`SMTP_TLS` fix.

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
