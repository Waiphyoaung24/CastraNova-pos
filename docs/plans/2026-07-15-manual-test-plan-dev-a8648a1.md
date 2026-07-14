# Manual test plan — `dev` @ `a8648a1` (PR #9, `dev_wth`)

Covers the 74 commits merged into `dev` on 2026-07-15: sliding-window sessions,
offline queue + sync-review producer, catalog pagination/search/pickers, the
atomic service-ticket record endpoint, margin drill-down, and the audit SKU filter.

Ordered by risk. Flows 1 and 2 are where data loss or a lockout would live.

## Setup

```bash
docker compose watch          # prestart runs alembic upgrade head (m028, m029)
```

Frontend `http://localhost:5173`, API `http://localhost:8000/docs`.

Also up: Adminer `http://localhost:8080`, Mailcatcher `http://localhost:1080`, Swagger
`http://localhost:8000/docs`. **Rate limiting is disabled in dev**
(`RATE_LIMIT_ENABLED=false`, `compose.override.yml:92`) — you will not get locked out by
repeated login attempts.

Use **three logins** to cover role gating:

- the seeded superuser (`FIRST_SUPERUSER`, `.env`),
- a plain **`BKK_ADMIN`** — a real, tested role. `notes.md` records a live bug where
  `BKK_ADMIN` hit a 403 on the audit page's user lookup, so it is worth its own pass.
- a **`YGN_STAFF`** user (create from `/admin`, which is superuser-only).

### Which screens each role can even open

`isAdmin = is_superuser OR role == BKK_ADMIN` (`backend\app\api\deps.py:74`).

| Guard | Routes |
|---|---|
| **superuser only** | `/admin` |
| **admin** (`requireAdmin`) | `/products`, `/customers`, `/suppliers`, `/projects`, `/receive`, `/audit`, `/channel-margin`, `/holding-period`, `/override-exceptions`, `/pricing-overrides`, `/stock-adjustment`, `/sync-review` |
| **any logged-in user** (`requireAuth`) | `/sale`, `/tickets`, `/pulls`, `/stock`, `/search`, `/low-stock`, `/notifications`, `/customer/$id`, `/project/$id` |

So **the catalog lists, filters and pagination in §3–§4 are admin-only screens** — don't
test them as staff. Staff testing lives in §2 (offline sale / ticket / pull) and §5 (the
pickers on `/sale` and `/tickets`).

---

## 1. Session & idle logout

Access tokens are now **15 minutes**; the refresh cookie is **12 hours, sliding**
(rotated + max-age-reset on every refresh). `backend/app/core/config.py:37,42`.
This is the change most likely to bite in production.

### Flow A — transparent refresh (happy path)

Log in, leave the tab idle **~16 minutes** (past access-token expiry, inside the
refresh window), then click something that hits the API (open `/products`, page forward).

**Expect:** it just works — no login screen, no error toast. DevTools → Network shows
one `401`, a call to `/login/refresh-token`, then the original request **retried and
succeeding**.

**If you get bounced to login:** the refresh cookie isn't reaching the API. This was a
real bug in this batch (`OpenAPI.WITH_CREDENTIALS` was `false`, so the cookie was never
sent cross-origin).

### Flow B — reload with a dead token

Log in. DevTools → Application → Cookies → delete the refresh cookie. Hard-reload.

**Expect:** the login screen immediately (boot-time session check) — not a half-rendered
app that 401s on every panel.

### Flow C — true logout

Log out, then press Back.

**Expect:** login screen. The refresh cookie is cleared server-side; you cannot resurrect
the session by navigating back.

### Flow D — the 12h window (optional)

You can't wait 12 hours, so shorten it: set `REFRESH_TOKEN_EXPIRE_MINUTES=2` in `.env`,
restart, log in, idle 3 minutes, click something.

**Expect:** forced back to login. **Restore the value afterward.**

---

## 2. Offline queue + sync review

Four mutation types now queue offline: **sales**, **serialized receipts**, **project-pull
fulfillment**, and **maintenance tickets**. Simulate with DevTools → Network → **Offline**
(not airplane mode — you want the API unreachable but the page alive).

### Flow A — offline sale replays exactly once

Log in. Go offline. On `/sale`, enter a **quantity-tracked** product and complete the sale.

**Expect while offline:** an amber banner at the bottom — `Offline — 1 change(s) queued,
will sync when you reconnect.` — and the checkout button reads **`Queued (offline)…`**
(`sale.tsx:95-99`). Not an error toast.

**Expect on reconnect:** the banner switches to `Syncing — N change(s) uploading…`, the
sale replays automatically and appears in `/audit` **exactly once**. Force a second replay
if you can and confirm **no duplicate sale** (idempotency keys are what prevent this).

**Reload while offline** with the sale still queued — it must survive (the queue is
persisted to IndexedDB, not memory).

### Flow B — offline maintenance ticket (new)

Go offline, record a ticket on `/tickets` **with parts**, hit **Close ticket**, go back
online.

**Expect:** one ticket, each part consumed **once**. This is the fix for the old
`ServiceTicketPart` duplicate-part-lines backlog item — a duplicate part line here is a
**genuine regression**, not a known issue.

Parts must be **QUANTITY**-tracked. Scanning a serialized unit is rejected up front with
**"Serialized units can't be added as repair parts."** — verify that guard while you're
here, since the equivalent guard is what's *missing* on `/sale` (see §9).

### Flow C — offline project pull + notification

Go offline, fulfill a pull on `/pulls`, go online.

**Expect:** replays, and `PULL_FULFILLED` fires on **full** fulfillment (check
`/notifications`). A **partial** fulfillment must **not** fire it.

### Flow D — conflict lands in sync review

The one that proves the producer works.

1. Queue a sale offline for a product with 1 unit left.
2. Before going back online, sell that same last unit from a **second, online session**.
3. Bring the offline tab back online.

**Expect:** the replay gets a 409 and the item appears in `/sync-review` (admin-only, State
filter defaults to `PENDING`) as a **CONFLICT**, with **Keep** / **Discard** buttons — not a
silent failure, not a lost sale.

Before this batch `/sync-review` had **no producer at all**, so an empty queue here means
the wiring didn't take.

**Control case — a live 409 must NOT divert.** While **online**, trigger the same
over-sell conflict directly. Expect the screen's own error toast and **nothing new in
`/sync-review`**. Only mutations that originated offline (`queuedOffline === true`) are
diverted (`sync-producer.ts:59-64`). If a live 409 shows up in the review queue, the
guard is broken.

### Flow E — 7-day stale cap (optional)

Queued mutations older than 7 days are dropped before replay
(`query-client.ts`, `staleItemFor`). Can't be tested without shortening the cap. Skip
unless you want to verify it explicitly.

---

## 3. Pagination (admin screens)

Page size is **25** everywhere (`frontend\src\hooks\usePagination.ts:3`); no screen
overrides it. Affected: `/products`, `/customers`, `/suppliers`, `/projects`,
`/pricing-overrides`, `/pulls`, `/admin` (users), `/audit`.

**Seed more than 25 rows** — the old code silently truncated at 100, so a 30-row table
looked fine and hid the entire bug class.

**The pager is hidden when there is only one page** (`PaginationControls.tsx:25-26`). With
≤25 rows you will see **no pagination UI at all**. That is correct, not a regression.

For each list expect: `Showing 1–25 of N` with a correct **N**; **first / prev / next /
last** buttons that actually change the rows and disable at the bounds; no flash of empty
content while paging (`keepPreviousData` + a loading overlay); and **page 5 showing
genuinely different rows from page 1**.

`/admin` previously had "pagination that lies" — client-side paging over a truncated
100-row fetch. Confirm it is real now: **user #101 must exist and be reachable.**

Lists sort **newest first** (`created_at DESC NULLS LAST, id`), so a row you just created
appears on page 1.

---

## 4. Search & filters (server-side)

| Screen | Filters | Match type |
|---|---|---|
| `/products` | search over **SKU or model**, **brand**, **category**, **tracking mode** | substring, case-insensitive (mode = exact enum) |
| `/customers` | **name** search, **country**, **type** (End customer / Dealer) | name substring; country **exact**; type exact |
| `/suppliers` | **name** search, **country** | name substring; country **exact** |

Country dropdowns are populated from the data itself — `GET /customers/countries` and
`GET /suppliers/countries` return only countries actually **in use**, alphabetically. An
unused country will not appear, by design.

Text inputs are **debounced 250 ms** — type fast and confirm **one** request fires, not one
per keystroke.

**Key scenario: apply a filter while on page 3.** Expect a reset to **page 1** with a
*filtered* count — not a stranded empty page 3 over a 12-row result. Every filter change
calls `pagination.reset()`.

Blank filters must be **omitted** from the request, not sent as empty strings. Watch the
query string in DevTools.

---

## 5. Pickers (`EntityCombobox`) — and one decision to confirm

Pickers appear on `/sale` and `/tickets` (customer), `/receive` (product + supplier),
`/pulls` → PullCreatePanel (project), `/stock` (supplier filter), `/audit` (SKU + user),
`/customers` + `/suppliers` (country).

**How it works, so you don't mis-file a bug:** `EntityCombobox` loads the whole option list
once from an unpaginated `/options` endpoint and filters it **client-side** (debounced
250 ms). It renders **50 rows at a time** and reveals the next 50 as you scroll near the
bottom; the footer reads `Showing 50 of 312`. So: **no request fires per keystroke** — that
is by design, not a broken search.

Per picker: type to filter; **mouse-wheel scroll inside the open dropdown** (just fixed);
scroll to the bottom and confirm more rows appear; clicking a picker inside a form **does
not submit the form** (just fixed on `/receive`).

Known and *not* worth filing: the picker popover is cramped on **mobile** — it's pinned to
the trigger width and doesn't reflow around the on-screen keyboard. Recorded in `notes.md`
with a suggested bottom-sheet fix. **Not built.**

### Pickers are now "active-only" — confirm this is wanted

`notes.md` flags this as owner-confirmation-pending:

- Mark a product **inactive** → it **disappears** from the `/sale`, `/receive`, `/tickets`
  and `/pulls` dropdowns.
- Set a project to **CLOSED** → it is **no longer selectable** when creating a project pull.

Both are intentional, but they change what staff can do:

1. Staff can no longer sell / receive / repair against a **discontinued** product.
2. Admin can no longer open a project pull against a **CLOSED** project.

**Deliberate exception:** the **audit** SKU filter still shows inactive products — a
discontinued SKU's historical ledger rows must stay filterable
(`GET /products/options?active_only=false`, the default).

The **tables** still list everything, so an admin can still see, edit, and re-activate an
inactive record.

**If either restriction is unwanted, it is a one-line `where` clause per endpoint to drop.**

---

## 6. Margin drill-down (`/channel-margin`)

Group by **Channel / Product / Customer / Project** — a 4-tab control
(`MarginDimension`, `models.py:1612`). A **Month** picker (required) and a **Channel**
scope filter (`All` / SALE / MAINTENANCE / PROJECT) sit beside it.

- Switch dimensions and confirm **totals reconcile** — revenue and COGS summed across
  groups must be identical regardless of grouping. (A COGS mismatch across groupings was
  the specific bug fixed here.)
- Sales with **no project** must land in an explicit **"(none)" bucket**, not vanish.
  There is no equivalent bucket for customer — `Sale.customer_id` is non-nullable.
- Test **group-by + channel filter together**.
- The **"Revenue mix by channel"** bar only renders when grouping by **channel**. Expected.
- **PDF** and **Excel** exports take the same three params; the filename carries a
  `-by-<dimension>` suffix (and `-<channel>` when scoped). Export from each tab and confirm
  the file matches what's on screen.

---

## 7. Audit ledger (`/audit`)

**Exactly five filters exist now:** **Event** (All / RECEIVED / SOLD / MAINTENANCE_OUT /
PROJECT_OUT / ADJUSTED_OUT), **User**, **From** (date), **To** (date), **SKU**.

The **batch-number filter was built and then removed** (migration `m029` drops its
indexes). If you see a Batch filter, something is stale. SKU now shows as a sub-line under
the **Model** column instead.

- Test the SKU filter across **both ledgers** — a SERIALIZED unit movement and a quantity
  PART consumption for the same SKU must both appear.
- Check pagination, the sticky header, and that there is **no horizontal page scroll** (the
  table body scrolls, the page does not).
- Confirm the **"By" column shows real names, not "Unknown user"** — including as a plain
  **`BKK_ADMIN`**, which is exactly where that bug lived.
- The SKU picker here **must still list discontinued products** (the deliberate exception in
  §5) — mark a product inactive, then confirm you can still filter its historical ledger
  rows by SKU.
- Note the **Movements** stat card counts the whole filtered set, but **Distinct users /
  Receipts / Outflows are computed over the current page only**. Not a bug.

---

## 8. Small behavior changes (one click each)

- **`/sale` no longer auto-selects the walk-in customer** (FR-007 — the PRD forbids
  walk-in sales). The customer field starts **empty** and **"Complete sale" stays disabled**
  until a real customer is picked. The escape hatch is the inline **create customer** dialog
  under the picker, which auto-selects the new customer on save — test that path too, since
  it's now the only way to sell to someone new.
- **`/override-exceptions`** is sorted by **deviation size, largest first** (ties break by
  oldest). Server-ordered — there is no client re-sort, so the order you see is the order
  the API returned.
- **`/suppliers`** country input caps at **64 chars**, matching the backend (used to 422
  silently).

---

## 9. Known open bug — do NOT report as a regression

On `/sale`, typing a **serialized** product's **SKU** (e.g. `iPhone-X`) adds a cart line
with no complaint, then fails at checkout:

```
POST /api/v1/sales -> 400
{"detail": "PART line requires a QUANTITY-tracked product"}
```

The correct input is the unit **barcode** (e.g. `CN-92E7DBDAD313458B`).

This is **deferred and undesigned** — recorded at the top of `notes.md`. It hinges on an
unresolved product question: *are serialized units interchangeable for identity, or only
for accounting?* It **predates this batch**.

---

## If you only have an hour

1. §1 Flow A — transparent refresh
2. §2 Flow D — conflict lands in sync-review
3. §2 Flow B — offline ticket, no duplicate parts
4. §5 — confirm the active-only picker decision
5. §3 — pagination on a >25-row list

Those five cover everything that could lose data or lock someone out. The rest is UI
surface that fails loudly.
