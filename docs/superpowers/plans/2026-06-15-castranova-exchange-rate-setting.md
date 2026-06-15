# Exchange-Rate Setting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-configurable USD→THB / MMK→THB exchange rate (stored in the existing `SystemSetting` key/jsonb store, exposed via `/settings/exchange-rates` and an admin-only Settings tab), then use it to generate a faithful, THB-priced Markdown of the CastraNova stock list.

**Architecture:** One grouped jsonb setting `exchange_rates_thb` = `{"USD_THB": "<dec>", "MMK_THB": "<dec>"}` (decimal strings for precision). Two thin `crud` wrappers over the existing `get_setting`/`set_setting`. A new `system_settings` router gated by the existing `AdminUser` dependency. Frontend: a react-hook-form tab on `/settings`, admin-only. No Alembic migration (table exists since m006).

**Tech Stack:** FastAPI + SQLModel + Pydantic v2, pytest; React + TanStack Query + react-hook-form + zod + shadcn/ui, `@hey-api/openapi-ts` SDK.

**Spec:** `docs/superpowers/specs/2026-06-15-castranova-exchange-rate-setting-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models.py` | `ExchangeRatesUpdate` (request) + `ExchangeRatesPublic` (response) schemas |
| `backend/app/crud.py` | `EXCHANGE_RATES_KEY`, `DEFAULT_EXCHANGE_RATES`, `get_exchange_rates`, `set_exchange_rates`, seed entry |
| `backend/app/api/routes/system_settings.py` (new) | `GET`/`PUT /settings/exchange-rates`, `AdminUser`-gated |
| `backend/app/api/main.py` | register the new router |
| `backend/tests/crud/test_system_setting.py` | crud round-trip / precision / seed-presence tests |
| `backend/tests/api/routes/test_system_settings.py` (new) | API auth + validation tests |
| `frontend/src/client/*` | regenerated SDK (`SettingsService`, `ExchangeRatesPublic/Update`) |
| `frontend/src/components/SystemSettings/ExchangeRates.tsx` (new) | the form |
| `frontend/src/routes/_layout/settings.tsx` | admin-only Exchange Rates tab |
| `docs/imports/2026-01-castranova-balance-stock.md` (new) | 214-row import-prep Markdown (sub-project 2) |

---

## Task 1: Backend schemas + crud helpers + seed (TDD via crud tests)

**Files:**
- Modify: `backend/app/models.py` (after the `Product`/price section, near other config schemas)
- Modify: `backend/app/crud.py` (system-settings section ~line 184–234)
- Test: `backend/tests/crud/test_system_setting.py`

- [ ] **Step 1: Write the failing crud tests**

Append to `backend/tests/crud/test_system_setting.py`:

```python
from decimal import Decimal

from app.models import ExchangeRatesUpdate


def test_default_exchange_rates_parse_to_zero() -> None:
    # Pure: no DB/order dependency (the shared session db is mutated by other tests).
    raw = crud.DEFAULT_EXCHANGE_RATES
    assert Decimal(raw["USD_THB"]) == Decimal("0")
    assert Decimal(raw["MMK_THB"]) == Decimal("0")


def test_seed_includes_exchange_rates_key(db: Session) -> None:
    crud.seed_system_settings(session=db)
    assert crud.get_setting(session=db, key=crud.EXCHANGE_RATES_KEY) is not None


def test_set_exchange_rates_roundtrip_preserves_precision(db: Session) -> None:
    crud.set_exchange_rates(
        session=db,
        rates=ExchangeRatesUpdate(
            usd_thb=Decimal("36.50"), mmk_thb=Decimal("0.0135")
        ),
    )
    rates = crud.get_exchange_rates(session=db)
    assert rates.usd_thb == Decimal("36.50")
    assert rates.mmk_thb == Decimal("0.0135")
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/crud/test_system_setting.py -v`
Expected: FAIL — `AttributeError: module 'app.crud' has no attribute 'set_exchange_rates'` / `ImportError: ExchangeRatesUpdate`.

- [ ] **Step 3: Add the schemas to `models.py`**

Insert after the `MinStockLevelUpdate` / price-change block (anywhere among the config schemas):

```python
# --- Exchange rates (import-time FX config; SystemSetting-backed) -------------


class ExchangeRatesUpdate(SQLModel):
    # THB per 1 unit of the source currency. ge=0 rejects negatives and NaN;
    # le bounds to a sane ceiling. Persisted as decimal strings in the jsonb
    # setting (Decimal is not JSON-serializable) to preserve precision.
    usd_thb: Decimal = Field(ge=0, le=1_000_000)
    mmk_thb: Decimal = Field(ge=0, le=1_000_000)


class ExchangeRatesPublic(SQLModel):
    usd_thb: Decimal
    mmk_thb: Decimal
    updated_at: datetime | None = None
```

(`Decimal`, `datetime`, `Field`, `SQLModel` are already imported at the top of `models.py`.)

- [ ] **Step 4: Add the crud constants + helpers + seed entry**

In `backend/app/crud.py`, add to the imports-from-`app.models` block: `ExchangeRatesPublic, ExchangeRatesUpdate`. Ensure `from decimal import Decimal` is present at the top (add if missing).

Below the existing `HOLDING_THRESHOLD_KEY` / `DEFAULT_HOLDING_THRESHOLD_DAYS` constants add:

```python
EXCHANGE_RATES_KEY = "exchange_rates_thb"
DEFAULT_EXCHANGE_RATES: dict[str, str] = {"USD_THB": "0", "MMK_THB": "0"}
```

In `seed_system_settings`, add to the `defaults` list:

```python
        (EXCHANGE_RATES_KEY, DEFAULT_EXCHANGE_RATES),
```

After `set_setting`, add the two typed wrappers (reuse the existing primitives — no new DB access pattern):

```python
def get_exchange_rates(*, session: Session) -> ExchangeRatesPublic:
    row = session.exec(
        select(SystemSetting).where(SystemSetting.key == EXCHANGE_RATES_KEY)
    ).first()
    raw = row.value if row else DEFAULT_EXCHANGE_RATES
    return ExchangeRatesPublic(
        usd_thb=Decimal(str(raw.get("USD_THB", "0"))),
        mmk_thb=Decimal(str(raw.get("MMK_THB", "0"))),
        updated_at=row.updated_at if row else None,
    )


def set_exchange_rates(
    *,
    session: Session,
    rates: ExchangeRatesUpdate,
    updated_by_user_id: uuid.UUID | None = None,
) -> ExchangeRatesPublic:
    set_setting(
        session=session,
        key=EXCHANGE_RATES_KEY,
        value={"USD_THB": str(rates.usd_thb), "MMK_THB": str(rates.mmk_thb)},
        updated_by_user_id=updated_by_user_id,
    )
    return get_exchange_rates(session=session)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/crud/test_system_setting.py -v`
Expected: PASS (all, including the 4 pre-existing tests).

- [ ] **Step 6: Lint + type-check**

Run: `cd backend && uv run ruff check app tests && uv run mypy app`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/tests/crud/test_system_setting.py
git commit -m "feat(settings): exchange-rate schemas + crud helpers + seed"
```

---

## Task 2: Backend route + registration (TDD via API tests)

**Files:**
- Create: `backend/app/api/routes/system_settings.py`
- Modify: `backend/app/api/main.py`
- Test: `backend/tests/api/routes/test_system_settings.py`

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/api/routes/test_system_settings.py`:

```python
"""Exchange-rate settings API (admin-only config over SystemSetting)."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import settings

URL = f"{settings.API_V1_STR}/settings/exchange-rates"


def test_admin_get_exchange_rates(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(URL, headers=superuser_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "usd_thb" in body and "mmk_thb" in body


def test_admin_put_then_get_persists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL,
        headers=superuser_token_headers,
        json={"usd_thb": "36.50", "mmk_thb": "0.0135"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["usd_thb"])) == Decimal("36.50")
    g = client.get(URL, headers=superuser_token_headers)
    assert Decimal(str(g.json()["usd_thb"])) == Decimal("36.50")
    assert Decimal(str(g.json()["mmk_thb"])) == Decimal("0.0135")


def test_staff_cannot_read(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    assert client.get(URL, headers=staff_token_headers).status_code == 403


def test_staff_cannot_write(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL, headers=staff_token_headers, json={"usd_thb": "1", "mmk_thb": "1"}
    )
    assert r.status_code == 403


def test_unauthenticated_rejected(client: TestClient) -> None:
    assert client.get(URL).status_code in (401, 403)


def test_negative_rate_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL,
        headers=superuser_token_headers,
        json={"usd_thb": "-1", "mmk_thb": "0"},
    )
    assert r.status_code == 422
```

(`client`, `superuser_token_headers`, `staff_token_headers` are session/module fixtures in `backend/tests/conftest.py`.)

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_system_settings.py -v`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Create the route**

Create `backend/app/api/routes/system_settings.py`:

```python
from fastapi import APIRouter

from app import crud
from app.api.deps import AdminUser, SessionDep
from app.models import ExchangeRatesPublic, ExchangeRatesUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/exchange-rates", response_model=ExchangeRatesPublic)
def get_exchange_rates(
    *, session: SessionDep, admin: AdminUser
) -> ExchangeRatesPublic:
    """Current USD/MMK -> THB conversion rates (admin-only config)."""
    return crud.get_exchange_rates(session=session)


@router.put("/exchange-rates", response_model=ExchangeRatesPublic)
def update_exchange_rates(
    *, session: SessionDep, admin: AdminUser, payload: ExchangeRatesUpdate
) -> ExchangeRatesPublic:
    """Set the USD/MMK -> THB conversion rates (admin-only)."""
    return crud.set_exchange_rates(
        session=session, rates=payload, updated_by_user_id=admin.id
    )
```

- [ ] **Step 4: Register the router**

In `backend/app/api/main.py`: add `system_settings` to the `from app.api.routes import (...)` block (keep alphabetical) and add `api_router.include_router(system_settings.router)` with the other includes.

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/api/routes/test_system_settings.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Full backend suite + lint + types**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run mypy app`
Expected: all green (no regressions).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/system_settings.py backend/app/api/main.py backend/tests/api/routes/test_system_settings.py
git commit -m "feat(settings): /settings/exchange-rates admin API"
```

---

## Task 3: Regenerate the SDK

**Files:** `frontend/src/client/*` (generated — never hand-edit)

- [ ] **Step 1: Ensure backend is importable, then generate**

Run (from repo root): `cd frontend && bun run generate-client`
(Fallback: `bash scripts/generate-client.sh`. The script dumps OpenAPI from the FastAPI app, so the backend `uv` env must be installed.)

- [ ] **Step 2: Verify the new service exists**

Run: `grep -r "exchange-rates\|ExchangeRates\|class SettingsService\|SettingsService" frontend/src/client | head`
Expected: a `SettingsService` with `getExchangeRates` + `updateExchangeRates` and `ExchangeRatesPublic` / `ExchangeRatesUpdate` types. **Note the exact generated method + type names** — Task 4 imports them; adjust Task 4 names to match if the generator differs.

- [ ] **Step 3: Commit the generated client**

```bash
git add frontend/src/client
git commit -m "chore(client): regenerate SDK for exchange-rates endpoint"
```

---

## Task 4: Exchange Rates form component

**Files:**
- Create: `frontend/src/components/SystemSettings/ExchangeRates.tsx`

- [ ] **Step 1: Confirm the shadcn primitives exist**

Run: `ls frontend/src/components/ui/input.tsx frontend/src/components/ui/form.tsx frontend/src/components/ui/loading-button.tsx`
Expected: all present. Confirm `FormDescription` is exported from `form.tsx` (`grep FormDescription frontend/src/components/ui/form.tsx`) — if absent, drop the `<FormDescription>` lines in Step 2.

- [ ] **Step 2: Write the component**

Create `frontend/src/components/SystemSettings/ExchangeRates.tsx`:

```tsx
import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type ExchangeRatesUpdate, SettingsService } from "@/client"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  usd_thb: z.coerce
    .number({ message: "Enter a number" })
    .min(0, { message: "Rate cannot be negative" }),
  mmk_thb: z.coerce
    .number({ message: "Enter a number" })
    .min(0, { message: "Rate cannot be negative" }),
})

type FormData = z.infer<typeof formSchema>

const ExchangeRates = () => {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ["exchange-rates"],
    queryFn: () => SettingsService.getExchangeRates(),
  })

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onSubmit",
    values: {
      usd_thb: Number(data?.usd_thb ?? 0),
      mmk_thb: Number(data?.mmk_thb ?? 0),
    },
  })

  const mutation = useMutation({
    mutationFn: (body: ExchangeRatesUpdate) =>
      SettingsService.updateExchangeRates({ requestBody: body }),
    onSuccess: () => {
      showSuccessToast("Exchange rates updated")
      queryClient.invalidateQueries({ queryKey: ["exchange-rates"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (values: FormData) => {
    mutation.mutate({
      usd_thb: String(values.usd_thb),
      mmk_thb: String(values.mmk_thb),
    })
  }

  return (
    <div className="max-w-md">
      <h3 className="text-lg font-semibold py-4">Exchange Rates</h3>
      <p className="text-muted-foreground text-sm pb-4">
        THB per 1 unit of the source currency. Used to convert imported supplier
        prices (USD / MMK) into THB.
      </p>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-4"
        >
          <FormField
            control={form.control}
            name="usd_thb"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>USD → THB</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="0.0001"
                    min="0"
                    inputMode="decimal"
                    data-testid="usd-thb-input"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormDescription>e.g. 1 USD = 36.50 THB</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="mmk_thb"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>MMK → THB</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="0.0001"
                    min="0"
                    inputMode="decimal"
                    data-testid="mmk-thb-input"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormDescription>e.g. 1 MMK = 0.0135 THB</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            className="self-start"
          >
            Save Rates
          </LoadingButton>
        </form>
      </Form>
    </div>
  )
}

export default ExchangeRates
```

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/components/SystemSettings/ExchangeRates.tsx`
Expected: clean. (If `getExchangeRates`/`updateExchangeRates` names differ from the generated SDK, fix the two call sites per Task 3 Step 2.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SystemSettings/ExchangeRates.tsx
git commit -m "feat(settings): Exchange Rates form component"
```

---

## Task 5: Wire the admin-only tab into the Settings page

**Files:**
- Modify: `frontend/src/routes/_layout/settings.tsx`

- [ ] **Step 1: Add the import + admin tab**

At the top of `settings.tsx`, add:

```tsx
import ExchangeRates from "@/components/SystemSettings/ExchangeRates"
```

After the existing `tabsConfig` declaration, add:

```tsx
const adminTabs = [
  { value: "exchange-rates", title: "Exchange Rates", component: ExchangeRates },
]
```

Replace the existing tab-selection line:

```tsx
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig.slice(0, 3)
    : tabsConfig
```

with:

```tsx
  const isAdmin =
    currentUser?.is_superuser || currentUser?.role === "BKK_ADMIN"
  const finalTabs = isAdmin ? [...tabsConfig, ...adminTabs] : tabsConfig
```

(The `if (!currentUser) return null` guard below already protects the render; `currentUser?.` keeps the pre-guard access safe.)

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/routes/_layout/settings.tsx`
Expected: clean. (`role` is present on the generated `UserPublic`; if its enum type rejects the `"BKK_ADMIN"` string literal, compare against the generated enum member instead.)

- [ ] **Step 3: Manual verification (dev stack running)**

With `docker compose watch` up: log in as the BKK_ADMIN superuser → `/settings` shows an **Exchange Rates** tab → set USD `36.5`, MMK `0.0135` → Save → toast → reload → values persist. Log in as `staff@example.com` → **no** Exchange Rates tab; `GET /api/v1/settings/exchange-rates` with a staff token → 403.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/settings.tsx
git commit -m "feat(settings): admin-only Exchange Rates tab"
```

---

## Task 6: Code review gate (before PR)

- [ ] **Step 1:** Run `requesting-code-review` over the diff (`dev..feat/exchange-rate-setting`).
- [ ] **Step 2:** Because this is settings/financial surface, also dispatch `ecc:database-reviewer` (jsonb setting round-trip, precision, seed idempotency) and `ecc:security-reviewer` (admin gating on both verbs, no staff leak, validation rejects negative/NaN).
- [ ] **Step 3:** Address findings; keep the suite green (`uv run pytest -q`, `bunx tsc --noEmit`, `bunx biome check`).

---

## Task 7: Generate the import-prep Markdown (sub-project 2 — human-in-the-loop)

**Files:** Create `docs/imports/2026-01-castranova-balance-stock.md`

> Gated on the feature shipping AND a real rate being set. The orchestrator (not a blind subagent) performs this, because the THB values depend on the live rate.

- [ ] **Step 1:** Obtain the rate to apply — either ask the user for the USD→THB / MMK→THB values, or read `GET /settings/exchange-rates` from the running stack.
- [ ] **Step 2:** Re-read the source PDF (`Read` tool) at `c:\Users\wai19\Downloads\Stock List.pdf` to get all 214 rows.
- [ ] **Step 3:** Build the Markdown per spec §6: `CN-0001…CN-0214` SKUs; `model_name`/`model_no`/`size` from the PDF; derived `brand`/`category`; `tracking_mode=QUANTITY`; `qty_on_hand` flagged as initial-stock; `orig_price`/`orig_currency`; `retail_price_thb = round(orig_price × rate, 2)` (blank where no price); `repair_price_thb = 0`; `flags`. Add the header block (FX rate + date used) and the "Before import" checklist.
- [ ] **Step 4: Validate** — row count = 214; USD subtotal reconciles to the PDF's `$51,160`; spot-check ≥5 rows incl. a no-price row (e.g. 0191) and an MMK row (e.g. 0096).
- [ ] **Step 5: Commit**

```bash
git add docs/imports/2026-01-castranova-balance-stock.md
git commit -m "docs(imports): CastraNova stock-list import-prep (THB via configured rate)"
```

---

## Self-Review

- **Spec coverage:** §3 setting/key → T1; §4 schemas/crud/route/main/tests → T1–T2; SDK → T3; component + tab → T4–T5; review gate (db+security) → T6; §6 Markdown → T7. All covered.
- **Placeholders:** none — every code/test step is complete; the only deferred values are the live FX numbers in T7 (by design, human-in-the-loop) and SDK method-name confirmation in T3 Step 2 (explicit verify-and-adjust).
- **Type consistency:** `ExchangeRatesUpdate`/`ExchangeRatesPublic` (models) used identically in crud, route, tests; `crud.set_setting` (real name, not `upsert_setting`); `EXCHANGE_RATES_KEY`/`DEFAULT_EXCHANGE_RATES` consistent across crud + tests; `usd_thb`/`mmk_thb` field names consistent backend↔frontend; SDK `SettingsService.getExchangeRates`/`updateExchangeRates` flagged for post-gen confirmation.
