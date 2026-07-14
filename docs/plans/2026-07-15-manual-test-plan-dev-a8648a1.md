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

Use **three logins** to cover role gating:

- the seeded superuser (`FIRST_SUPERUSER`),
- a **staff** user (create from `/admin`),
- a plain **`BKK_ADMIN`** — a real, tested role. `notes.md` records a live bug where
  `BKK_ADMIN` hit a 403 on the audit page's user lookup, so it is worth its own pass.

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

**Expect:** the UI accepts it as queued/pending, not an error. Go back online — it replays
automatically and appears in `/audit` **exactly once**. Force a second replay if you can and
confirm **no duplicate sale** (idempotency keys are what prevent this).

### Flow B — offline maintenance ticket (new)

Go offline, record a ticket on `/tickets` **with parts**, go back online.

**Expect:** one ticket, each part consumed **once**. This is the fix for the old
`ServiceTicketPart` duplicate-part-lines backlog item — a duplicate part line here is a
**genuine regression**, not a known issue.

### Flow C — offline project pull + notification

Go offline, fulfill a pull on `/pulls`, go online.

**Expect:** replays, and `PULL_FULFILLED` fires on **full** fulfillment (check
`/notifications`). A **partial** fulfillment must **not** fire it.

### Flow D — conflict lands in sync review

The one that proves the producer works.

1. Queue a sale offline for a product with 1 unit left.
2. Before going back online, sell that same last unit from a **second, online session**.
3. Bring the offline tab back online.

**Expect:** the replay gets a 409 and the item appears in `/sync-review` as a **CONFLICT**
for an admin to resolve — not a silent failure, not a lost sale.

Before this batch `/sync-review` had **no producer at all**, so an empty queue here means
the wiring didn't take.

### Flow E — 7-day stale cap (optional)

Queued mutations older than 7 days are dropped before replay
(`query-client.ts`, `staleItemFor`). Can't be tested without shortening the cap. Skip
unless you want to verify it explicitly.

---

## 3. Pagination

Page size is **25** (`frontend/src/hooks/usePagination.ts:3`). Affected:
`/products`, `/customers`, `/suppliers`, `/projects`, `/admin` (users), `/audit`.

Seed **more than 25 rows** — the old code silently truncated at 100, so a 30-row table
looked fine and hid the bug class.

For each list, expect: a correct total count, Previous/Next that actually change rows, no
flash of empty content when paging, and **page 5 of products showing genuinely different
rows from page 1**.

`/admin` previously had "pagination that lies" (client-side paging over a truncated 100-row
fetch). Confirm it is real now by checking that **user #101 exists and is reachable**.

---

## 4. Search & filters (server-side)

| Screen | Filters |
|---|---|
| `/products` | text search over **SKU or model**, plus brand, category, tracking mode |
| `/customers` | name search, **country** dropdown, **customer type** |
| `/suppliers` | name search |

Search is **debounced** — type fast and confirm **one** request fires, not one per keystroke.

Key scenario: **apply a filter while on page 3.** Expect a reset to page 1 with a *filtered*
count — not a stranded empty page 3 over a 12-row result.

---

## 5. Pickers (`EntityCombobox`) — and one decision to confirm

Pickers appear on `/sale` and `/tickets` (customer), `/receive` (product + supplier),
`/pulls` → PullCreatePanel (project), `/stock` (supplier filter), `/audit` (SKU + user).

Per picker: type to search; **mouse-wheel scroll inside the open dropdown** (just fixed);
"Show more" loads additional options; clicking a picker inside a form **does not submit the
form** (just fixed on `/receive`).

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

Group by **channel, product, customer, project** (`MarginDimension`, `models.py:1612`).

- Switch dimensions and confirm **totals reconcile** — revenue and COGS summed across
  groups must be identical regardless of grouping. (A COGS mismatch across groupings was
  the specific bug fixed here.)
- Sales with **no project** must land in an explicit **"(none)" bucket**, not vanish.
- Test **group-by + channel filter together**.
- Check the CSV/export filename — it now carries a `-by-<dimension>` suffix.

---

## 7. Audit ledger (`/audit`)

Filters that exist **now**: date from/to, user, product, unit, **SKU**.

The **batch-number filter was built and then removed** (migration `m029` drops its
indexes). If you see a Batch filter, something is stale.

- Test the SKU filter across **both ledgers** — a SERIALIZED unit movement and a quantity
  PART consumption for the same SKU must both appear.
- Check pagination, the sticky header, and that there is **no horizontal page scroll**.
- Confirm the **"By" column shows real names, not "Unknown user"** — including as a plain
  **`BKK_ADMIN`**, which is exactly where that bug lived.

---

## 8. Small behavior changes (one click each)

- **`/sale` no longer auto-selects the walk-in customer** (FR-007 — the PRD forbids
  walk-in sales). The customer field starts **empty** and checkout requires a real customer.
- **`/override-exceptions`** is sorted by **deviation size**, largest first.
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
