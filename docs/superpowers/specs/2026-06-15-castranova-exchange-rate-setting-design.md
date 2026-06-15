# CastraNova-POS — Exchange-Rate Setting + Stock-List Import Prep — Design

- **Date:** 2026-06-15
- **Status:** Approved design — ready for implementation planning
- **Scope:** Add an admin-configurable **USD→THB / MMK→THB exchange rate** stored in the existing `SystemSetting` (key/jsonb) store, exposed via a new `/settings/exchange-rates` API and an admin-only tab on the Settings page. Then use that rate to produce a faithful, import-ready Markdown table of the 214-line Aquamarine Moon "Balance Stock (1/2026)" PDF, rebranded as **CastraNova** stock, mapped toward the `Product` model.
- **Authoritative source:** `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (§4.2 row 8 — SystemSetting singleton key/jsonb store). `Product` model: `backend/app/models.py` (`ProductBase`).
- **Origin:** User request — convert a supplier stock list (USD + Kyat) into THB "in accordance" with the system, which is THB-only in the database.

---

## 1. Problem

The CastraNova database is **THB-only** — every price field is `*_thb` (`Product.retail_price_thb`, `repair_price_thb`; `Unit.purchase_cost_thb`; etc.). The incoming supplier stock list prices items in **two foreign currencies**:

- **USD** — most items (e.g. `$1,250` condensing unit).
- **MMK (Kyat)** — copper fittings, gauges, switches, lighting, gas, oil, copper pipe (e.g. `12,000`, `450,000`).
- A handful (IDs 0191–0197, 0204) have **no price** (`-`).

To bring this stock into the system as `Product` rows, those prices must be converted to THB by a **single, auditable, admin-controlled rate** — not a number hardcoded into a one-off script. There is currently **no UI and no API** to read or set any `SystemSetting`; the two existing keys (`override_deviation_threshold_pct`, `holding_period_threshold_days`) are seeded at init and read only internally.

## 2. Scope boundary (what this is NOT)

This is an **import-time conversion config**, not a live multi-currency feature. We are **not**:

- storing prices in any currency other than THB in the DB,
- adding runtime currency switching / per-request currency display,
- auto-fetching live FX rates.

The rate is a manually-entered constant the admin maintains, used to convert source data → THB. (CLAUDE.md §2 — no speculative flexibility.)

## 3. Decision

**Sub-project 1 — Exchange-rate setting (feature; full skill loop).**
Store one grouped setting `exchange_rates_thb` whose jsonb value is `{"USD_THB": "<decimal>", "MMK_THB": "<decimal>"}`. Expose `GET`/`PUT /settings/exchange-rates`, gated by the existing **`AdminUser`** dependency (superuser *or* `BKK_ADMIN`). Add an admin-only **"Exchange Rates"** tab to the existing `/settings` page.

- **Why one grouped jsonb key, not two scalar keys:** the two rates are one conceptual config block ("the FX table"); the `SystemSetting.value` column is jsonb precisely so a setting can hold its natural type (here, a dict). Read/written atomically in one upsert.
- **Why strings inside the jsonb:** `Decimal` is not JSON-serializable; storing the rates as decimal **strings** (`"36.50"`, `"0.0135"`) preserves precision through JSONB and round-trips back to `Decimal` on read. (The existing scalar settings store native float/int; money-grade precision warrants strings here.)
- **Why `AdminUser` (not `get_current_active_superuser`):** matches every other admin-gated write in the app (`stock_adjustments.py`, etc.); a `BKK_ADMIN` who is not a superuser must be able to maintain rates.
- **Default `0`:** seeded as `{"USD_THB": "0", "MMK_THB": "0"}` = "not configured yet" (consistent with the zero-placeholder convention chosen for `repair_price_thb`). Conversion treats an unset (`0`) rate as "THB not yet computable" rather than silently producing `0` THB prices.

**Sub-project 2 — Stock-list import-prep Markdown (data artifact; lightweight, no skill loop).**
After the feature ships and the admin enters a rate, generate `docs/imports/2026-01-castranova-balance-stock.md`: one row per item, SKUs `CN-0001 … CN-0214`, mapped toward `Product`, with `retail_price_thb` **computed** = `orig_price × rate` and `repair_price_thb = 0`. Original price + currency always preserved for audit.

## 4. Sub-project 1 — Change set (one feature PR off `dev`)

| Layer | File | Change |
|---|---|---|
| Backend | `app/crud.py` | Add `EXCHANGE_RATES_KEY = "exchange_rates_thb"` + `DEFAULT_EXCHANGE_RATES = {"USD_THB": "0", "MMK_THB": "0"}`. Add a `get_exchange_rates(*, session) -> ExchangeRatesPublic` (reads via existing `get_setting`, parses str→`Decimal`) and `set_exchange_rates(*, session, rates: ExchangeRatesUpdate, updated_by_user_id) -> ExchangeRatesPublic` (writes via existing `upsert_setting`, dict-of-strings). Add the key to `seed_system_settings()` defaults. **Reuses** `get_setting`/`upsert_setting` — no new DB primitives; keeps all DB access in `crud.py`. |
| Backend | `app/models.py` | Add `ExchangeRatesUpdate(SQLModel)` — `usd_thb: Decimal = Field(ge=0, le=1_000_000)`, `mmk_thb: Decimal = Field(ge=0, le=1_000_000)` (both rejecting NaN via `ge`). Add `ExchangeRatesPublic(SQLModel)` — `usd_thb`, `mmk_thb`, `updated_at: datetime \| None`. |
| Backend | `app/api/routes/system_settings.py` *(new)* | `router = APIRouter(prefix="/settings", tags=["settings"])`. `GET /settings/exchange-rates` → `ExchangeRatesPublic` (dep `AdminUser`). `PUT /settings/exchange-rates` → body `ExchangeRatesUpdate`, dep `AdminUser`, calls `crud.set_exchange_rates(..., updated_by_user_id=admin.id)`, returns `ExchangeRatesPublic`. |
| Backend | `app/api/main.py` | `from app.api.routes import ... system_settings` + `api_router.include_router(system_settings.router)`. |
| Backend tests | `tests/crud/test_system_setting.py` | Add: `set_exchange_rates` → `get_exchange_rates` round-trips the two `Decimal`s; `seed_system_settings` includes the FX key at default `0/0`; precision (e.g. `0.0135`) survives the str↔Decimal round-trip. |
| Backend tests | `tests/api/routes/test_system_settings.py` *(new)* | Admin `GET` returns seeded defaults; admin `PUT` persists and a subsequent `GET` reflects it; **staff (`YGN_STAFF`) → 403**; unauthenticated → 401/403; negative rate → 422; non-numeric → 422. |
| Frontend | *(SDK)* | `bun run generate-client` after backend lands → typed `getExchangeRates` / `putExchangeRates` (or hey-api equivalents) + `ExchangeRatesPublic` / `ExchangeRatesUpdate` types. |
| Frontend | `src/components/SystemSettings/ExchangeRates.tsx` *(new)* | react-hook-form + zod resolver (two non-negative number fields), loads current rates via TanStack Query (generated SDK), `PUT` mutation on submit, success/error toast, invalidate the rates query. Mirrors existing form components under `components/UserSettings/`. |
| Frontend | `src/routes/_layout/settings.tsx` | Add an admin-only **"Exchange Rates"** tab (rendered when `currentUser.is_superuser \|\| currentUser.role === "BKK_ADMIN"`) wiring in `ExchangeRates`. Non-admins never see the tab. |

**No Alembic migration** — the `SystemSetting` table already exists (m006); we only add a new *row key*, seeded idempotently.

## 5. What is explicitly NOT changing

- **Existing settings untouched.** `override_deviation_threshold_pct` and `holding_period_threshold_days` keep their internal reads (reports/overrides); we only add a third key and the first HTTP surface over the store.
- **No change to any price field or money flow.** No `Product`, `Sale`, FIFO, or ledger code is touched by sub-project 1. The rate is read by the *import* step (sub-project 2), not by any runtime pricing path.
- **`get_setting`/`upsert_setting`/`seed_system_settings` signatures unchanged** — we add a key and two typed wrappers, not modify the primitives.
- **Staff redaction model intact.** Rates are admin-only read+write; staff have no endpoint and no tab.

## 6. Sub-project 2 — Markdown structure (data artifact)

File: `docs/imports/2026-01-castranova-balance-stock.md`. Header block (source, date, 214 items, rules applied, FX rate + date used). One table row per item:

| Column | Source / rule |
|---|---|
| `sku` | `CN-0001 … CN-0214` (Item ID is the only guaranteed-unique key; descriptions repeat) |
| `model_name` | "Description for Sales" |
| `model_no` | "Molden No" (= Model No), preserved (blank where blank) |
| `size` | "Size no", preserved |
| `brand` | Extracted: Danfoss, WELCOLD, HEOK/HPEOK, Castal, Sanhua, Hongsen, ANACONDA, Opple, Damppro… else blank |
| `category` | Derived (Condensing Unit, Compressor, Unit Cooler, Oil Separator, Receiver, Ball/Hand/Solenoid/Expansion/Check/Angle Valve, Filter Drier, Sight Glass, Copper Fitting, Pipe, Gauge, Lighting, Oil, Gas, …) |
| `tracking_mode` | `QUANTITY` for all (matches the Qty-based source) |
| `qty_on_hand` | "Qty" — **flagged**: becomes a receive / stock-adjustment movement at import, NOT a `Product` column |
| `orig_price` / `orig_currency` | Original price + `USD` / `MMK` / *(none)*, classified per row from which Total column is populated |
| `retail_price_thb` | **Computed** = `orig_price × rate` (USD_THB or MMK_THB from the setting), rounded to 2 dp; blank where `orig_price` is missing |
| `repair_price_thb` | `0` placeholder |
| `flags` | `NO PRICE` (0191–0197, 0204), `MMK-priced`, `Model No missing`, etc. |

Plus a "Before import" checklist + flag summary (USD vs MMK vs no-price counts, missing Model No). The importer itself (creating `Product` rows + initial stock movements) is **out of scope here** and, being inventory/financial code, gets its own full skill loop later.

## 7. Testing strategy

- **Backend (pytest):** crud round-trip + seed-default + precision tests; API tests for admin success, staff 403, unauth, and 422 validation (negative / non-numeric). Full `uv run pytest` green; `ruff` + `mypy app` clean.
- **Frontend:** `tsc` + `biome` clean after SDK regen; the Exchange Rates tab renders for an admin, is absent for staff; saving a rate round-trips (loads back the saved value).
- **Manual:** log in as BKK_ADMIN → Settings → Exchange Rates → set USD/MMK rates → reload shows persisted values; log in as staff → no Exchange Rates tab; `GET /settings/exchange-rates` with a staff token → 403.
- **Markdown:** row count = 214; per-currency subtotals reconcile against the PDF's printed totals (USD `$51,160`; the Kyat-priced subtotal); spot-check 5–10 rows (incl. a no-price row and an MMK row) against the source.

## 8. Definition of Done

- `GET`/`PUT /settings/exchange-rates` work for admin; staff → 403; unauth rejected; negative/non-numeric → 422; values persist across requests.
- Admin-only Exchange Rates tab on `/settings`; absent for staff; save round-trips.
- Backend `pytest` green; `ruff` + `mypy` + `biome` + `tsc` clean; SDK regenerated and committed.
- `docs/imports/2026-01-castranova-balance-stock.md` generated with 214 rows, THB computed from the configured rate, totals reconciled.
- Reviewed via `requesting-code-review` **+ `ecc:database-reviewer` + `ecc:security-reviewer`** (financial/settings surface) before the PR into `dev`.
