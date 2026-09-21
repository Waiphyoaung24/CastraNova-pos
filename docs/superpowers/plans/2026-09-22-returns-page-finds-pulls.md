# Returns Page Finds Pulls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell → Return can bring back stock that left on a project pull, from the same picker staff already use for sales.

**Architecture:** A new read endpoint `GET /project-pulls/returnable` mirrors `GET /sales/returnable` and reads what is still out from the ledgers via the existing `pull_line_returnable`. The Returns page runs both lookups for a scan, merges them into one picker (values prefixed `sale:`/`pull:`), and submits pull picks through the existing `POST /project-pulls/{id}/returns`. No migration.

**Tech Stack:** FastAPI, SQLModel, pytest; React + TanStack Query, shadcn/ui, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-22-returns-page-finds-pulls.md` (addendum to `docs/superpowers/specs/2026-09-21-pull-return-design.md`)

## Global Constraints

- All DB access in `backend/app/crud.py`; routes never call `session.exec`.
- No Alembic migration; `alembic check` stays clean.
- mypy strict; ruff clean on touched lines. Never `git add -A` (line-ending churn in the tree) — stage explicit paths.
- Staff must never receive cost fields: `ReturnablePullLinePublic` carries no cost/price. `assert_no_financial_keys` must pass on the new payload.
- Literal route `/returnable` must be declared before `/{pull_id}` in `routes/project_pulls.py` (FastAPI matches in order).
- SDK: regenerate with `cd backend && UV_LINK_MODE=copy uv run python -c "import app.main, json; print(json.dumps(app.main.app.openapi()))" > ../frontend/openapi.json && cd ../frontend && bun run generate-client`. Never `scripts/generate-client.sh` or repo-wide `bun run lint`.
- Backend tests truncate the dev DB. Restore before E2E with `docker compose exec -T backend bash -c "cd /app/backend && python app/initial_data.py && python -m app.seed_demo"`.
- E2E: `E2E_SKIP_DB_RESET=1 VITE_API_URL=http://localhost:8000 npx playwright test <specs> --workers=1` from `frontend/`; rebuild the backend container first (`docker compose up -d --build backend`).
- Commits end with: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`

## Review Focus

1. **A unit that was pulled, returned, then sold.** Scanning its barcode must offer the SALE, not the old pull (pull line nets to 0). (Task 1 `test_unit_returned_then_sold_offers_sale_not_pull`.)
2. **A SKU with both a sale and a pull outstanding.** Both appear; the picker is ordered newest first across the two. (Task 2 vitest `merges newest first across sales and pulls`.)
3. **Submitting a pull pick must not send a reason** (the pull endpoint has no such field → 422). (Task 2 vitest `pull payload has no reason`.)
4. **A PENDING pull for the scanned SKU must not be offered** — its stock is undone by Cancel. (Task 1 `test_pending_pull_not_offered`.)
5. **Return on the Unit tab for a pulled unit** works without a reason field. (Task 3 E2E.)

---

### Task 1: `GET /project-pulls/returnable`

**Files:**
- Modify: `backend/app/models.py` (after `ProjectPullsPublic`)
- Modify: `backend/app/crud.py` (after `pull_line_returnable`)
- Modify: `backend/app/api/routes/project_pulls.py`
- Create: `backend/tests/api/routes/test_returnable_pulls.py`

**Interfaces:**
- Produces: `ReturnablePullsPublic { pulls: list[ReturnablePullPublic] }`; `ReturnablePullPublic { pull_id, project_code, project_name, customer_name, created_at, lines }`; `ReturnablePullLinePublic { line_id, line_kind, product_id, label, quantity_out, quantity_returnable }`; `crud.list_returnable_pulls(*, session, castranova_barcode=None, sku=None, limit=20) -> ReturnablePullsPublic`; route fn `read_returnable_pulls` → SDK `ProjectPullsService.readReturnablePulls({ castranovaBarcode?, sku? })`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/api/routes/test_returnable_pulls.py`

```python
"""GET /project-pulls/returnable — the Returns page's project-request source."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    ProjectPullCreate,
    ProjectPullLineCreate,
    ProjectPullReturnCreate,
    ProjectPullReturnLine,
    SaleLineInput,
    SaleLineKind,
)
from tests.api.routes.test_project_pulls import (  # noqa: F401  (pull_ctx is a fixture)
    _create,
    _line_ids,
    pull_ctx,
)
from tests.utils.utils import assert_no_financial_keys

PREFIX = settings.API_V1_STR


def _settle(db: Session, pull_id: str, ctx: dict[str, Any]) -> None:
    crud.fulfill_project_pull(
        session=db, pull_id=uuid.UUID(pull_id), fulfill_lines=[], actor_user_id=ctx["admin_id"]
    )


def _part_pull(db: Session, ctx: dict[str, Any], *, qty: int) -> uuid.UUID:
    """A settled pull with only a PART line (the shared unit can be pulled once)."""
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=ctx["project_id"],
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART, product_id=ctx["part_product_id"], requested_qty=qty
                )
            ],
        ),
        created_by_user_id=ctx["admin_id"],
    )
    crud.fulfill_project_pull(session=db, pull_id=pull.id, fulfill_lines=[], actor_user_id=ctx["admin_id"])
    return pull.id


def _sku(db: Session, product_id: uuid.UUID) -> str:
    product = crud.get_product(session=db, product_id=product_id)
    assert product is not None
    return product.sku


def test_sku_lists_settled_pulls(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    first = _create(client, superuser_token_headers, pull_ctx, part_qty=2)  # UNIT + PART
    _settle(db, first["id"], pull_ctx)
    second = _part_pull(db, pull_ctx, qty=1)

    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200, r.text
    pulls = r.json()["pulls"]
    # Same-second created_at ties make the order random on Windows, so assert
    # membership; the query orders by created_at desc for the picker.
    assert {p["pull_id"] for p in pulls} == {first["id"], str(second)}
    by_id = {p["pull_id"]: p for p in pulls}
    line = by_id[first["id"]]["lines"][0]
    assert line["line_kind"] == "PART"
    assert line["quantity_out"] == 2 and line["quantity_returnable"] == 2
    assert by_id[first["id"]]["project_code"] and by_id[first["id"]]["customer_name"] == "Proj Cust"
    # Only the PART line matches a SKU lookup — the UNIT line is another product.
    assert all(ln["line_kind"] == "PART" for p in pulls for ln in p["lines"])


def test_barcode_resolves_a_pulled_unit(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    )
    assert r.status_code == 200, r.text
    pulls = r.json()["pulls"]
    assert len(pulls) == 1 and pulls[0]["pull_id"] == pull["id"]
    line = pulls[0]["lines"][0]
    assert line["line_kind"] == "UNIT" and line["quantity_returnable"] == 1


def test_fully_returned_line_disappears(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    crud.return_project_pull(
        session=db,
        pull_id=uuid.UUID(pull["id"]),
        payload=ProjectPullReturnCreate(
            idempotency_key=uuid.uuid4(),
            lines=[ProjectPullReturnLine(line_id=uuid.UUID(ids["PART"]), quantity=2)],
        ),
        actor_user_id=pull_ctx["admin_id"],
    )
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200
    assert r.json()["pulls"] == []


def test_pending_pull_not_offered(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    _create(client, superuser_token_headers, pull_ctx)  # stays PENDING: undo via Cancel
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200
    assert r.json()["pulls"] == []


def test_unit_returned_then_sold_offers_sale_not_pull(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    crud.return_project_pull(
        session=db,
        pull_id=uuid.UUID(pull["id"]),
        payload=ProjectPullReturnCreate(
            idempotency_key=uuid.uuid4(),
            lines=[ProjectPullReturnLine(line_id=uuid.UUID(ids["UNIT"]), quantity=1)],
        ),
        actor_user_id=pull_ctx["admin_id"],
    )
    crud.create_sale(
        session=db,
        customer_id=pull_ctx["customer_id"],
        created_by_user_id=pull_ctx["admin_id"],
        idempotency_key=uuid.uuid4(),
        lines=[SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=pull_ctx["barcode"])],
    )
    pulls = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    ).json()["pulls"]
    sales = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    ).json()["sales"]
    assert pulls == [] and len(sales) == 1


def test_requires_exactly_one_selector(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    none = client.get(f"{PREFIX}/project-pulls/returnable", headers=superuser_token_headers)
    both = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": "X", "castranova_barcode": "Y"},
    )
    assert none.status_code == 422 and both.status_code == 422
    unknown = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": f"NOPE-{uuid.uuid4().hex[:6]}"},
    )
    assert unknown.status_code == 404


def test_staff_can_use_lookup_and_sees_no_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=staff_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["pulls"]) == 1
    assert_no_financial_keys(r.json())
    assert "unit_price_thb" not in r.text and "cost" not in r.text
```

- [ ] **Step 2: Run to verify they fail**

Run (from `backend/`): `UV_LINK_MODE=copy uv run pytest tests/api/routes/test_returnable_pulls.py -q -p no:cacheprovider`
Expected: FAIL — 404/422 on the unknown route (`/returnable` parsed as a pull id).

- [ ] **Step 3: Models** (`models.py`, after `ProjectPullsPublic`)

```python
class ReturnablePullLinePublic(SQLModel):
    line_id: uuid.UUID
    line_kind: SaleLineKind
    product_id: uuid.UUID
    label: str  # "SKU — Model name"
    quantity_out: int  # the line's cap: 1 for UNIT, requested_qty for PART
    quantity_returnable: int


class ReturnablePullPublic(SQLModel):
    pull_id: uuid.UUID
    project_code: str
    project_name: str
    customer_name: str
    created_at: datetime
    lines: list[ReturnablePullLinePublic]


class ReturnablePullsPublic(SQLModel):
    # Cost-free on purpose: the Returns page is a staff surface.
    pulls: list[ReturnablePullPublic]
```

- [ ] **Step 4: crud** (`crud.py`, after `pull_line_returnable`; import the three models)

```python
_RETURNABLE_PULL_LIMIT = 20  # bounded, newest-first (same shape as sales)


def list_returnable_pulls(
    *,
    session: Session,
    castranova_barcode: str | None = None,
    sku: str | None = None,
    limit: int = _RETURNABLE_PULL_LIMIT,
) -> ReturnablePullsPublic:
    """Settled pulls (FULFILLED / SHORT / CANCELLED) that still have stock out
    for one unit or one SKU — the Returns page's project-request source.
    PENDING pulls are omitted: their stock comes back via admin Cancel. Lines
    with nothing left to return are dropped, so an empty result means "nothing
    here can be returned". Mirrors ``list_returnable_sales``."""
    if (castranova_barcode is None) == (sku is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of castranova_barcode or sku",
        )
    stmt = (
        select(ProjectPullLine, ProjectPull)
        .join(ProjectPull, col(ProjectPullLine.project_pull_id) == col(ProjectPull.id))
        .where(ProjectPull.state != ProjectPullState.PENDING)
        .order_by(col(ProjectPull.created_at).desc(), col(ProjectPull.id))
    )
    if castranova_barcode is not None:
        stmt = stmt.where(ProjectPullLine.unit_serial == castranova_barcode)
    else:
        product = session.exec(select(Product).where(Product.sku == sku)).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        stmt = stmt.where(
            ProjectPullLine.product_id == product.id,
            ProjectPullLine.line_kind == SaleLineKind.PART,
        )
    # Over-fetch: fully-returned lines are filtered out below.
    rows = session.exec(stmt.limit(limit * 4)).all()

    lines_by_pull: dict[uuid.UUID, list[ProjectPullLine]] = {}
    pulls: dict[uuid.UUID, ProjectPull] = {}
    for line, pull in rows:
        lines_by_pull.setdefault(pull.id, []).append(line)
        pulls[pull.id] = pull
    labels = _product_labels(session, list({ln.product_id for ln, _ in rows}))
    projects = {
        p.id: p
        for p in session.exec(
            select(Project).where(col(Project.id).in_([p.project_id for p in pulls.values()]))
        ).all()
    } if pulls else {}
    customers = _customer_labels(session, [p.customer_id for p in pulls.values()])

    out: list[ReturnablePullPublic] = []
    for pull_id, lines in lines_by_pull.items():  # insertion order == newest first
        # Whole-pull lines feed the netting so per-product caps are exact.
        all_lines = list_project_pull_lines(session=session, pull_id=pull_id)
        returnable = pull_line_returnable(session=session, pull_id=pull_id, lines=all_lines)
        offered = [
            ReturnablePullLinePublic(
                line_id=ln.id,
                line_kind=ln.line_kind,
                product_id=ln.product_id,
                label=labels.get(ln.product_id, ""),
                quantity_out=_pull_line_cap(ln),
                quantity_returnable=returnable.get(ln.id, 0),
            )
            for ln in lines
            if returnable.get(ln.id, 0) > 0
        ]
        if not offered:
            continue
        pull = pulls[pull_id]
        project = projects.get(pull.project_id)
        out.append(
            ReturnablePullPublic(
                pull_id=pull.id,
                project_code=project.code if project else "",
                project_name=project.name if project else "",
                customer_name=customers.get(pull.customer_id, ""),
                created_at=pull.created_at,
                lines=offered,
            )
        )
        if len(out) >= limit:
            break
    return ReturnablePullsPublic(pulls=out)
```

`list_project_pull_lines`, `_pull_line_cap`, `_product_labels`, `_customer_labels` already exist in `crud.py`.

- [ ] **Step 5: Route** — in `routes/project_pulls.py`, add `ReturnablePullsPublic` to the imports and insert this **above** `read_project_pull` (`@router.get("/{pull_id}", ...)`):

```python
# Declared before /{pull_id}: a literal segment must win over the parameterized
# one, or "returnable" is parsed as a pull id.
@router.get(
    "/returnable",
    response_model=ReturnablePullsPublic,
    dependencies=[Depends(get_current_user)],
)
def read_returnable_pulls(
    *,
    session: SessionDep,
    castranova_barcode: str | None = None,
    sku: str | None = None,
) -> ReturnablePullsPublic:
    """Settled pulls with stock still out for one unit or one SKU. Staff +
    admin — the payload carries no cost."""
    return crud.list_returnable_pulls(
        session=session, castranova_barcode=castranova_barcode, sku=sku
    )
```

- [ ] **Step 6: Run tests, mypy, ruff**

Run: `UV_LINK_MODE=copy uv run pytest tests/api/routes/test_returnable_pulls.py tests/api/routes/test_project_pulls.py tests/api/routes/test_project_pull_returns.py -q -p no:cacheprovider && UV_LINK_MODE=copy uv run mypy app && UV_LINK_MODE=copy uv run ruff check app/crud.py app/models.py app/api/routes/project_pulls.py tests/api/routes/test_returnable_pulls.py`
Expected: all PASS, clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/app/api/routes/project_pulls.py backend/tests/api/routes/test_returnable_pulls.py
git commit -m "feat(pulls): returnable-pulls lookup for the Returns page"
```

---

### Task 2: Returns page merges pulls into the picker

**Files:**
- Regenerate: `frontend/src/client/*.gen.ts` (expected diff: `ReturnablePull*` schemas + `readReturnablePulls`)
- Modify: `frontend/src/lib/sale-return.ts`, `frontend/src/lib/sale-return.test.ts`
- Modify: `frontend/src/routes/_layout/returns.tsx`

**Interfaces:**
- Consumes: `ProjectPullsService.readReturnablePulls`, `ProjectPullsService.returnProjectPull`, `ReturnablePullsPublic`.
- Produces (in `sale-return.ts`): `ReturnDraft.source: "sale" | "pull"`, `ReturnDraft.pullId`; `PickerOption { value, label, source, quantityReturnable, saleId?, pullId?, lineId }`; `pickerOptions(sales, pulls): PickerOption[]`; `canSubmitReturn` (reason not required for pull); `buildPullReturnPayload(d, key): ProjectPullReturnCreate`.

- [ ] **Step 1: Regenerate the SDK** (constraints block command). `git diff --ignore-cr-at-eol --stat src/client` must list only `schemas.gen.ts`, `sdk.gen.ts`, `types.gen.ts`.

- [ ] **Step 2: Failing vitest** — append to `src/lib/sale-return.test.ts`

```ts
import type {
  ReturnablePullsPublic,
  ReturnableSalesPublic,
} from "@/client/types.gen"
import { buildPullReturnPayload, pickerOptions } from "./sale-return"

const sales: ReturnableSalesPublic = {
  sales: [
    {
      sale_id: "s1",
      sold_at: "2026-09-20T10:00:00Z",
      customer_id: "c1",
      customer_name: "Thiri Trading",
      lines: [
        {
          sale_line_id: "sl1",
          line_kind: "PART",
          product_id: "p1",
          unit_id: null,
          label: "BAT — Battery",
          quantity_sold: 2,
          quantity_returned: 0,
          quantity_returnable: 2,
          unit_price_thb: "1900.00",
        },
      ],
    },
  ],
}
const pulls: ReturnablePullsPublic = {
  pulls: [
    {
      pull_id: "pu1",
      project_code: "PRJ-9",
      project_name: "Refit",
      customer_name: "Ko Min",
      created_at: "2026-09-21T10:00:00Z",
      lines: [
        {
          line_id: "pl1",
          line_kind: "PART",
          product_id: "p1",
          label: "BAT — Battery",
          quantity_out: 7,
          quantity_returnable: 5,
        },
      ],
    },
  ],
}

describe("returns picker with project pulls", () => {
  it("merges newest first across sales and pulls with prefixed values", () => {
    const opts = pickerOptions(sales, pulls)
    expect(opts.map((o) => o.value)).toEqual(["pull:pl1", "sale:sl1"])
    expect(opts[0].label).toContain("Refit (PRJ-9)")
    expect(opts[0].label).toContain("Ko Min")
    expect(opts[0].label).toContain("5 of 7 returnable")
    expect(opts[0]).toMatchObject({ source: "pull", pullId: "pu1", lineId: "pl1", quantityReturnable: 5 })
    expect(opts[1]).toMatchObject({ source: "sale", saleId: "s1", lineId: "sl1", quantityReturnable: 2 })
  })

  it("does not require a reason for a pull return", () => {
    const d = draft({ source: "pull", pullId: "pu1", saleLineId: "pl1", quantity: "3", reason: "" })
    expect(canSubmitReturn(d, 5)).toBe(true)
    expect(canSubmitReturn(draft({ source: "sale", saleLineId: "sl1", quantity: "1", reason: "" }), 2)).toBe(false)
  })

  it("pull payload has no reason", () => {
    const d = draft({ source: "pull", pullId: "pu1", saleLineId: "pl1", quantity: "3" })
    expect(buildPullReturnPayload(d, KEY)).toEqual({
      idempotency_key: KEY,
      lines: [{ line_id: "pl1", quantity: 3 }],
    })
  })
})
```

(`draft`, `KEY`, `canSubmitReturn` already exist at the top of that file; move the new `import` lines up with the other imports.)

Run: `bun run test:unit -- src/lib/sale-return.test.ts` → FAIL (`pickerOptions` not exported).

- [ ] **Step 3: `sale-return.ts`** — extend the draft and add the helpers

```ts
export interface ReturnDraft {
  /** Where the stock is coming back from. */
  source: "sale" | "pull"
  saleId: string
  pullId: string
  /** sale_line_id (sale) or pull line_id (pull) — the picker's line. */
  saleLineId: string
  /** Positive integer as typed; parsed at submit. */
  quantity: string
  /** Required for a sale return; a pull return has no reason field. */
  reason: string
}

export const emptyReturnDraft: ReturnDraft = {
  source: "sale",
  saleId: "",
  pullId: "",
  saleLineId: "",
  quantity: "1",
  reason: "",
}

export interface PickerOption {
  value: string // "sale:<sale_line_id>" | "pull:<line_id>"
  label: string
  source: "sale" | "pull"
  saleId?: string
  pullId?: string
  lineId: string
  quantityReturnable: number
  unitPriceThb?: string
  /** Sort key: when the sale/pull was made. */
  at: string
}

/** One list for the picker: sales and project requests, newest first. */
export function pickerOptions(
  sales: ReturnableSalesPublic | undefined,
  pulls: ReturnablePullsPublic | undefined,
): PickerOption[] {
  const day = (iso: string) => new Date(iso).toLocaleDateString()
  const fromSales: PickerOption[] = (sales?.sales ?? []).flatMap((s) =>
    s.lines.map((l) => ({
      value: `sale:${l.sale_line_id}`,
      label: `${day(s.sold_at)} · ${s.customer_name} · ${l.quantity_returnable} of ${l.quantity_sold} returnable`,
      source: "sale" as const,
      saleId: s.sale_id,
      lineId: l.sale_line_id,
      quantityReturnable: l.quantity_returnable,
      unitPriceThb: l.unit_price_thb,
      at: s.sold_at,
    })),
  )
  const fromPulls: PickerOption[] = (pulls?.pulls ?? []).flatMap((p) =>
    p.lines.map((l) => ({
      value: `pull:${l.line_id}`,
      label: `${day(p.created_at)} · ${p.project_name} (${p.project_code}) · ${p.customer_name} · ${l.quantity_returnable} of ${l.quantity_out} returnable`,
      source: "pull" as const,
      pullId: p.pull_id,
      lineId: l.line_id,
      quantityReturnable: l.quantity_returnable,
      at: p.created_at,
    })),
  )
  return [...fromSales, ...fromPulls].sort((a, b) => b.at.localeCompare(a.at))
}

export function buildPullReturnPayload(
  d: ReturnDraft,
  idempotencyKey: string,
): ProjectPullReturnCreate {
  return {
    idempotency_key: idempotencyKey,
    lines: [{ line_id: d.saleLineId.trim(), quantity: parseQuantity(d.quantity) ?? 0 }],
  }
}
```

Change `canSubmitReturn`: `if (d.source === "sale" && d.reason.trim() === "") return false`. Add the type imports (`ProjectPullReturnCreate`, `ReturnablePullsPublic`, `ReturnableSalesPublic`). Update the header comment: "a reason is required for a sale return; a project-pull return has none".

Run: `bun run test:unit -- src/lib/sale-return.test.ts` → PASS (all, including the old tests — `draft()` spreads `emptyReturnDraft`, so old tests keep `source: "sale"`).

- [ ] **Step 4: `returns.tsx`**

1. Imports: add `ProjectPullsService` from `@/client`; `buildPullReturnPayload`, `pickerOptions`, `type PickerOption` from `@/lib/sale-return`.
2. Second lookup, next to `lookup`:
```tsx
  const pullLookup = useQuery({
    queryKey: ["returnable-pulls", targetKind === "UNIT" ? "barcode" : "sku", scanned],
    queryFn: () =>
      targetKind === "UNIT"
        ? ProjectPullsService.readReturnablePulls({ castranovaBarcode: scanned })
        : ProjectPullsService.readReturnablePulls({ sku: scanned }),
    enabled: scanned.length > 0,
    retry: false,
  })
  const options = pickerOptions(lookup.data, pullLookup.data)
  const selected: PickerOption | undefined = options.find(
    (o) => o.lineId === draft.saleLineId && o.source === draft.source,
  )
```
   Replace the old `selectedLine` uses with `selected` (`quantityReturnable`, `unitPriceThb`).
3. Mutation: replace `mutationFn` with a branch on `vars.draft.source`:
```tsx
    mutationFn: (vars: { draft: ReturnDraft }) =>
      vars.draft.source === "pull"
        ? ProjectPullsService.returnProjectPull({
            pullId: vars.draft.pullId,
            requestBody: buildPullReturnPayload(vars.draft, crypto.randomUUID()),
          })
        : SalesService.createSaleReturn({
            saleId: vars.draft.saleId,
            requestBody: buildReturnPayload(vars.draft, crypto.randomUUID()),
          }),
```
   `onSuccess` also invalidates `["returnable-pulls"]` and `["project-pulls"]`. Both `mutate` calls become `mutation.mutate({ draft: … })`.
4. Picker `onValueChange`:
```tsx
                    onValueChange={(value) => {
                      const hit = options.find((o) => o.value === value)
                      if (!hit) return
                      set({
                        source: hit.source,
                        saleLineId: hit.lineId,
                        saleId: hit.saleId ?? "",
                        pullId: hit.pullId ?? "",
                        quantity: "1",
                      })
                    }}
```
   `value={draft.saleLineId ? `${draft.source}:${draft.saleLineId}` : ""}`; render `options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)`. Label text becomes "Sale or request being returned from"; keep `id={salePickerId}`.
5. Loading/empty branches use both lookups: error if `lookup.isError || pullLookup.isError`; empty when both have data and `options.length === 0`, copy: "Nothing from this SKU can be returned — no recent sale or project request still has returnable stock."
6. After a pick: the **reason** field and the **Refund** paragraph render only when `selected.source === "sale"`. The cap text reads "Up to N can still be returned from this {sale line|project request}."
7. Unit tab: `const unitPull = pullLookup.data?.pulls[0]; const unitPullLine = unitPull?.lines[0]`. When `!unitSale && unitPull && unitPullLine`, render a second card variant: "This unit went out on a project request — you can return it to stock." with `{unitPullLine.label} · {project_name} ({project_code}) · {customer_name}`, no refund line, no reason field, button **"Return to stock"** calling `mutation.mutate({ draft: { ...emptyReturnDraft, source: "pull", pullId: unitPull.pull_id, saleLineId: unitPullLine.line_id, quantity: "1" } })`. The "Nothing to return" copy becomes "…no recent sale or project request that can still be returned."
8. Page description: "Take stock back from a customer or a project. A sale refund is the original sale price; returns are recorded permanently." Help box: "…for a SKU, pick the sale or project request it is coming back from…".

- [ ] **Step 5: Verify**

Run (from `frontend/`): `bun run build && bun run test:unit && bunx biome check src/lib/sale-return.ts src/lib/sale-return.test.ts src/routes/_layout/returns.tsx`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/client/schemas.gen.ts frontend/src/client/sdk.gen.ts frontend/src/client/types.gen.ts frontend/src/lib/sale-return.ts frontend/src/lib/sale-return.test.ts frontend/src/routes/_layout/returns.tsx
git commit -m "feat(returns): Returns page also brings back project-pull stock"
```

---

### Task 3: E2E + docs

**Files:**
- Create: `frontend/tests/returns-pulls.spec.ts`
- Modify: `frontend/tests/sale-return.spec.ts` (only if a selector broke — the picker id/role is unchanged)
- Modify: `CLAUDE.md` (append one sentence to the "Project pull returns" bullet), `docs/testing/2026-09-22-pull-return-manual-test.md` (new section H)

- [ ] **Step 1: `returns-pulls.spec.ts`** — reuse `seedPull()` from `frontend/tests/pull-return.spec.ts` (copy it; it is module-local), plus a serialized variant:

```ts
test("Returns page brings back 2 of 3 parts from a project request", async ({ page }) => {
  const { product, pull } = await seedPull()
  await ProjectPullsService.fulfillProjectPull({ pullId: pull.id, requestBody: { lines: [] } })
  expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

  await page.goto("/returns")
  await page.getByRole("tab", { name: "Quantity SKU" }).click()
  await page.getByRole("textbox", { name: "Scan barcode" }).fill(product.sku)
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: /Return Project .* 3 of 3 returnable/ }).click()
  await page.getByRole("textbox", { name: /quantity returned/i }).fill("2")
  await expect(page.getByRole("textbox", { name: /reason for the return/i })).toHaveCount(0)
  await page.getByRole("button", { name: "Record return" }).click()
  await expect(page.getByText("Return recorded. The stock is back on hand.")).toBeVisible()
  await expect.poll(() => onHand(product.sku)).toBe(ON_HAND - REQUESTED + 2)
})

test("Returns page brings back a pulled unit from the Unit tab", async ({ page }) => {
  // seed: SERIALIZED product, receive 1 unit (ReceiptsService.receiveSerialized),
  // customer + project, pull with a UNIT line for that barcode, fulfill.
  ...
  await page.goto("/returns")
  await page.getByRole("textbox", { name: "Scan barcode" }).fill(barcode)
  await expect(page.getByText(/went out on a project request/)).toBeVisible()
  await page.getByRole("button", { name: "Return to stock" }).click()
  await expect(page.getByText("Return recorded. The stock is back on hand.")).toBeVisible()
  await expect.poll(async () =>
    (await SearchService.searchSerial({ castranovaBarcode: barcode })).current_state,
  ).toBe("IN_STOCK")
})
```

For the unit seed copy the `receiveSerialized` block from `frontend/tests/sale-return.spec.ts` `seedSoldUnit()` (it returns the barcode), then create the pull with `lines: [{ line_kind: "UNIT", product_id, unit_serial: barcode }]`. Check the exact SDK name for the serial lookup with `grep -n "searchSerial\|readSerial" frontend/src/client/sdk.gen.ts` and use what exists.

- [ ] **Step 2: Run** — rebuild backend, restore DB, then:
`E2E_SKIP_DB_RESET=1 VITE_API_URL=http://localhost:8000 npx playwright test tests/returns-pulls.spec.ts tests/sale-return.spec.ts tests/pull-return.spec.ts --workers=1` → all PASS. Restore the DB again afterwards.

- [ ] **Step 3: Docs** — CLAUDE.md pull-returns bullet: append "The Sell → Return page also lists settled project requests (`GET /project-pulls/returnable`) in its picker, so staff can bring pulled stock back from the same screen." Manual test plan: add section **H. Returns page** — scan `BAT-SG23-STD` on Sell → Return, the picker lists the Test/seed project requests alongside the sale, return 2, on hand +2; Unit tab with a pulled barcode offers "Return to stock" with no reason field.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/returns-pulls.spec.ts CLAUDE.md docs/testing/2026-09-22-pull-return-manual-test.md docs/superpowers/specs/2026-09-22-returns-page-finds-pulls.md docs/superpowers/plans/2026-09-22-returns-page-finds-pulls.md
git commit -m "test(returns): e2e for project-pull returns from the Returns page; docs"
```
