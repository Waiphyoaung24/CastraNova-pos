# QA follow-up hardening — PR #10 (dev-kwg)

**Date:** 2026-07-16
**Branch:** `dev-kwg` → PR #10 (`QA follow-ups: FR-012 customer filter, inactive-product guard, per-client login rate limit`)
**Status:** design approved; implementation pending

## Purpose

A verification pass over PR #10's three fixes found one regression the PR itself introduced, two claims recorded in `notes.md` that nothing enforces, and one entry that is factually wrong for the production deploy path. This spec covers the three changes that land on `dev-kwg`. The rate-limit topology fix is explicitly **out of scope** here and gets its own PR (see "Deferred").

Every change traces to a claim `notes.md` or PR #10 already makes. Nothing here adds new product behaviour.

## Findings this addresses

All three were confirmed by running code, not by reading it.

### 1. `receive_serialized` breaks its own documented idempotency (regression, introduced by PR #10)

`crud.receive_serialized` calls `_require_active_product()` **before** resolving the replay; `crud.receive_quantity` resolves the replay **first**. The docstring promises "replaying the same idempotency_key returns the already-created units without inserting duplicates (FR-005, S5)".

Observed:

```
receive_serialized replay after deactivation → FAILED
  E  fastapi.exceptions.HTTPException: 400: Product RPRB-S-f149f1d4 is inactive
receive_quantity   replay after deactivation → PASSED
```

Impact: receive serialized stock → product is retired → an offline client replays that receipt → `400` instead of its units, and the client cannot reconcile. This is the S5 offline path the codebase explicitly designs for.

`notes.md` records the guard as landing "at all six resolution sites" but does not record this side effect. The database reviewer checked this exact property for sales and cleared it correctly (replay at `crud.py:2355` precedes the guards) — it did not check the other five sites.

### 2. Two documented decisions that nothing enforces

- `notes.md`: *"Deliberately **not** enforced on pull fulfillment or stock adjustments (draining a discontinued item must stay possible)"*. Nothing tests this. Adding the guard to `create_stock_adjustment` "for consistency" leaves all 7 existing tests green while silently breaking the reconciliation path for discontinued stock.
- The 7 existing guard tests all assert the reject direction using a fresh `uuid4()` idempotency key. None exercises replay — which is why finding 1 shipped.

### 3. FR-012's "admin-only" is enforced only in the UI

`notes.md`: *"owner chose admin-only over staff-visible for consistency"*. `GET /dashboards/stock-on-hand` is gated by `Depends(get_current_user)` only, and `crud.stock_on_hand` receives no user context, so it cannot role-check. A **staff** token read a customer's purchase history:

```
200 {"rows":[{"sku":"LEAK-4150fd43","model_name":"Leak Probe Widget", ...
```

`/customers/options` is also open to any authenticated user, so the UUIDs needed to enumerate are freely available.

Scope note: `?customer=` already existed at `82e2351`, so PR #10 did not introduce the exposure — it added the UI control and inherited the pattern from `?supplier=`. The change below makes the recorded owner decision true; it does not invent a policy.

## Design

### Change 1 — guard ordering in `receive_serialized` (`backend/app/crud.py`)

Move `_require_active_product(product)` from before the supplier/location lookups to immediately after the replay-return block, mirroring `receive_quantity`.

Behaviour after the change:
- replay of a receipt made while the product was active → returns the existing units (S5 honoured)
- fresh receive of an inactive product → still `400 "Product <SKU> is inactive"` (FR unchanged)

Applied and verified already; carried on the branch.

### Change 2 — two tests appended to `backend/tests/api/routes/test_inactive_product_guard.py`

Same file, same fixture style as the existing 7 — no new file, no new fixtures.

1. **Replay regression test.** Receive serialized pieces while active → deactivate → replay the same `idempotency_key` → assert the same unit ids come back. Must fail without Change 1 and pass with it.
2. **Adjustment-exception test.** A stock adjustment against an inactive QUANTITY product still succeeds, pinning the decision `notes.md` records and `crud.py` comments at the `create_stock_adjustment` site.

Transaction hygiene: tests must not leave the session-scoped `db` fixture idle-in-transaction. An exploratory probe that ended by touching an ORM attribute after a commit re-opened a transaction and deadlocked a later module's `TRUNCATE` (the suite hung ~30 min). Assert on values captured before the final commit, or go through the API client as the existing tests do.

### Change 3 — backend admin gate on `?customer=` (`backend/app/api/routes/dashboards.py`)

Chosen approach: in-path check reusing the existing `is_admin()` helper. This matches the FastAPI idiom (inject `current_user`, raise `HTTPException` in the path operation) and the codebase's own pattern — `get_admin`/`AdminUser` is already used across 10+ route files; `dashboards.py` is the outlier that never adopted it.

```python
def get_stock_on_hand(
    session: SessionDep,
    current_user: CurrentUser,
    category: str | None = None,
    supplier: uuid.UUID | None = None,
    customer: uuid.UUID | None = None,
) -> StockOnHandResponse:
    if customer is not None and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Customer filter is admin-only")
```

`CurrentUser` already authenticates, so it **replaces** `dependencies=[Depends(get_current_user)]` rather than adding to it.

Rejected alternatives:
- A dedicated dependency that inspects the query param — an abstraction for one call site (CLAUDE.md §2).
- OAuth2 scopes — rewrites the auth model for a single filter.

Deliberately **not** in scope (owner decision, tracked separately):
- `?supplier=` has the identical hole. Left open; supplier data is less sensitive than customer purchase history.
- `/customers/options` and `/suppliers/options` are open to any authenticated user, so enumeration remains possible. Gating them risks breaking non-admin UI that reads those lists and needs its own check.

No frontend change: the UI already gates both filters behind `isAdmin`. No SDK regeneration expected — query params and response model are unchanged; verify the OpenAPI output does not drift rather than assuming.

## Error handling

- Inactive product on a fresh transaction: `400 "Product <SKU> is inactive"` (unchanged).
- Non-admin passing `?customer=`: `403 "Customer filter is admin-only"`. `403` over silently ignoring the param — silent filtering would make the API lie about what it returned.
- Non-admin **without** `?customer=`: unchanged `200`. Staff stock view must not regress.

## Testing

Baseline is **576 passed / 3 failed**, not 579 green. These three fail identically on `82e2351` (dev) and on pristine `dev-kwg`, so they are not caused by any change here:

- `tests/api/test_staff_redaction_lock.py::test_staff_get_sweep_carries_no_financial_keys[/products/]`
- `tests/api/test_staff_redaction_lock.py::test_staff_get_sweep_carries_no_financial_keys[/project-pulls]`
- `tests/api/routes/test_reports.py::test_adjacent_month_not_counted`

Compare failure **names** against that list, not the pass count — PR #10's "576 passed, 0 new failures" is consistent with a red suite.

Gates before the PR update:
1. Both new tests fail first, then pass (TDD, per CLAUDE.md §5 stage 3).
2. New gate test: staff + `?customer=` → `403`; admin + `?customer=` → `200`; staff without `?customer=` → `200`.
3. Full suite: every pre-existing test still passing, the new tests passing, and the failure list still exactly the 3 named above — no new names.
4. FIFO concurrency suite green — mandatory, this touches the consumption path.
5. `ecc:database-reviewer` + `ecc:security-reviewer` on the diff (CLAUDE.md high-risk rule: append-only / FIFO / role-tiering).

**Environment trap:** `docker compose up` runs whatever is in the last-built image — `backend/Dockerfile` does not COPY `tests/`, which arrive only via `docker compose watch` sync. Running pytest after a plain `up` silently tests stale `app/` code. A probe for finding 1 initially **passed** against an image whose `crud.py` contained zero occurrences of the guard under test. Use `docker compose watch` or `scripts/test.sh`, and confirm the container has the symbol before trusting any result.

## Deferred — rate-limit topology (own PR)

Not in this PR; needs an owner decision this spec cannot make.

`notes.md` marks §8.2 **FIXED** on the premise *"Traefik as sole ingress; backend service publishes **no** ports"*. Verified per file:

| file | backend ports |
|---|---|
| `compose.yml` | none |
| `compose.override.yml` | `8000:8000` |
| `compose.dokploy.yml` | `8099:8000` |

The premise holds only for `compose.yml` in isolation. Production deploys via `compose.dokploy.yml`, which publishes `8099:8000` and never received `FORWARDED_ALLOW_IPS`. Therefore:

- The fix is **not deployed to production** — the shop-wide lockout remains live there, and the `notes.md` entry asserting otherwise needs correcting.
- **Do not copy `FORWARDED_ALLOW_IPS=*` to `compose.dokploy.yml`.** Traefik strips client-supplied `X-Forwarded-*`, but port `8099` bypasses Traefik entirely. Verified end-to-end through the real `fastapi run` path: `X-Forwarded-For: 203.0.113.9` → `request.client.host == 203.0.113.9`. With `*` on a published port, an attacker rotates the header per request and bypasses the login limit completely — strictly worse than the lockout it fixes. Pin to the proxy subnet instead.

Open question for that PR: which subnet Traefik occupies in the Dokploy deployment. The api host is unreachable from the dev machine, so this cannot be verified locally.

Also relevant, unchanged by this spec:
- `compose.override.yml` sets `RATE_LIMIT_ENABLED: "false"`, so the login limit is never exercised in local dev or E2E, and the fix has no automated coverage.
- Pre-existing: 4 uvicorn workers × slowapi in-memory storage means limits are per-worker (~4× nominal).
