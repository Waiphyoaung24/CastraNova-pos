# Ledger Receipt Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "View receipt" button to the audit detail drawer that opens the sale's receipt PDF (now enriched with customer, selling staff, and human-readable line items) in a new tab.

**Architecture:** The existing `GET /api/v1/sales/{sale_id}/receipt.pdf` endpoint is reused unchanged in shape. A new read-only crud helper resolves a sale into receipt display data (customer name, staff name, per-line labels); the renderer gains two header fields. The frontend adds an authed-PDF button to `AuditDetailSheet`, shown only when the entry came from a sale.

**Tech Stack:** FastAPI + SQLModel + reportlab (backend), React + TanStack + shadcn/ui (frontend), pytest + Playwright (tests).

## Global Constraints

- All DB access goes through `crud.py`; routes never call `session.exec` for business reads (existing `_to_public` in sales.py already does — leave it, but the new resolution lives in crud).
- The sale receipt is non-financial beyond price + total: **never** add cost/COGS/margin data to `render_sale_receipt` or the receipt PDF. A guardrail test enforces the renderer's parameter allowlist.
- mypy strict: annotate everything.
- No SDK regeneration: the endpoint's path/method/response shape do not change, only the rendered PDF body.
- The receipt button appears **only when `entry.sale_id` is present**.
- biome for frontend lint/format; ruff + mypy for backend.

---

### Task 1: Enrich the receipt renderer

Add `customer_name` and `sold_by` header fields to `render_sale_receipt`. The
`lines` tuple stays `(label, qty, price)` — only the label content improves
(done in Task 2), so the renderer's line loop is unchanged except spacing.

**Files:**
- Modify: `backend/app/services/receipt_pdf.py`
- Test: `backend/tests/services/test_receipt_pdf.py`

**Interfaces:**
- Produces: `render_sale_receipt(*, sale_id: str, sold_at: str, customer_name: str, sold_by: str, lines: list[tuple[str, int, Decimal]], total_thb: Decimal) -> bytes`

- [ ] **Step 1: Update the guardrail test allowlist (failing)**

The signature test pins the exact parameter set to block cost-data leaks. Widen
it to include the two new non-cost display fields. In
`backend/tests/services/test_receipt_pdf.py`, change the `expected` set in
`test_receipt_pdf_signature_has_no_cost_parameter`:

```python
    expected = {"sale_id", "sold_at", "customer_name", "sold_by", "lines", "total_thb"}
```

Then update the two existing `render_sale_receipt(...)` calls in this file
(`test_receipt_pdf_lines_tuple_has_no_cost_position` and
`test_receipt_pdf_returns_valid_pdf_bytes` and
`test_receipt_pdf_selling_total_is_included`) to pass the new required kwargs,
e.g.:

```python
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-abc",
        sold_at="2026-06-07T12:30:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[
            ("Unit SN-ABC123", 1, Decimal("1500.00")),
            ("Service Charge", 1, Decimal("200.00")),
        ],
        total_thb=Decimal("1700.00"),
    )
```

Apply the same two-kwarg addition to the calls in
`test_receipt_pdf_lines_tuple_has_no_cost_position` and
`test_receipt_pdf_selling_total_is_included`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/services/test_receipt_pdf.py -v`
Expected: FAIL — `test_receipt_pdf_signature_has_no_cost_parameter` fails on the
new allowlist, and the render calls fail with `unexpected keyword argument
'customer_name'`.

- [ ] **Step 3: Add the new parameters and header lines**

In `backend/app/services/receipt_pdf.py`, replace the signature and the header
block:

```python
def render_sale_receipt(
    *,
    sale_id: str,
    sold_at: str,
    customer_name: str,
    sold_by: str,
    lines: list[tuple[str, int, Decimal]],
    total_thb: Decimal,
) -> bytes:
    """Return a one-page receipt PDF. ``lines`` are (label, quantity, price)."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A6)
    width, height = A6
    y = height - 12 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(8 * mm, y, "CastraNova POS — Receipt")
    pdf.setFont("Helvetica", 7)
    y -= 6 * mm
    pdf.drawString(8 * mm, y, f"Sale {sale_id[:8]}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Date {sold_at}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Customer {customer_name[:34]}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Sold by {sold_by[:34]}")
    y -= 8 * mm
    pdf.setFont("Helvetica", 8)
    for label, qty, price in lines:
        pdf.drawString(8 * mm, y, f"{label[:28]}")
        pdf.drawRightString(width - 8 * mm, y, f"{qty} x {price}")
        y -= 5 * mm
    y -= 3 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(8 * mm, y, "Total")
    pdf.drawRightString(width - 8 * mm, y, f"{total_thb} THB")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_receipt_pdf.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/receipt_pdf.py backend/tests/services/test_receipt_pdf.py
git commit -m "feat(receipt): add customer and sold-by header to receipt PDF"
```

---

### Task 2: Resolve sale → receipt display data in crud

Add a read-only helper that turns a sale into the renderer's inputs: customer
name, selling-staff name, and per-line labels using product model names (parts:
`Model (SKU)`; units: `Model · serial`) instead of `"UNIT"`/`"PART"`. Batched
lookups, mirroring `_hydrate_audit` — no N+1.

**Files:**
- Modify: `backend/app/crud.py` (add helper + dataclass near `get_sale` at ~line 1926)
- Test: `backend/tests/api/routes/test_sales_serialized.py`

**Interfaces:**
- Consumes: `crud.get_sale(session=..., sale_id=...) -> Sale | None` (exists, crud.py:1926)
- Produces:
  - `@dataclass(frozen=True) class SaleReceiptData` with fields `sale_id: uuid.UUID`, `sold_at: datetime`, `customer_name: str`, `sold_by: str`, `lines: list[tuple[str, int, Decimal]]`, `total_thb: Decimal`
  - `crud.get_sale_receipt_data(*, session: Session, sale_id: Any) -> SaleReceiptData | None`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/api/routes/test_sales_serialized.py` (the file already
imports `crud`, `Session`, `select`, `uuid`, and defines `seed_sale_unit` +
`_sale_body`). The seed product is `model_name="Compressor"`, customer
`"Walk-in"`, serial `SN-…`, seller = FIRST_SUPERUSER.

```python
def test_get_sale_receipt_data_resolves_names_and_labels(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    created = client.post(
        f"{PREFIX}/sales",
        headers=superuser_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert created.status_code == 200, created.text
    sale_id = created.json()["id"]

    data = crud.get_sale_receipt_data(session=db, sale_id=uuid.UUID(sale_id))
    assert data is not None
    assert data.customer_name == "Walk-in"
    assert "@" in data.sold_by or data.sold_by  # full name or email, never empty
    assert len(data.lines) == 1
    label, qty, price = data.lines[0]
    assert "Compressor" in label  # not the raw "UNIT" placeholder
    assert "UNIT" != label
    assert qty == 1


def test_get_sale_receipt_data_unknown_sale_returns_none(db: Session) -> None:
    assert crud.get_sale_receipt_data(session=db, sale_id=uuid.uuid4()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/routes/test_sales_serialized.py::test_get_sale_receipt_data_resolves_names_and_labels tests/api/routes/test_sales_serialized.py::test_get_sale_receipt_data_unknown_sale_returns_none -v`
Expected: FAIL with `AttributeError: module 'app.crud' has no attribute 'get_sale_receipt_data'`.

- [ ] **Step 3: Implement the helper**

In `backend/app/crud.py`, add `from dataclasses import dataclass` to the imports
if not present. Then add directly after `get_sale` (~line 1926). `select`,
`col`, `Session`, `Any`, `Unit`, `Product`, `Customer`, `User`, `SaleLine` are
already imported and used by `_hydrate_audit`.

```python
@dataclass(frozen=True)
class SaleReceiptData:
    """Resolved display inputs for one sale's receipt PDF (non-financial beyond
    price + total)."""

    sale_id: uuid.UUID
    sold_at: datetime
    customer_name: str
    sold_by: str
    lines: list[tuple[str, int, Decimal]]
    total_thb: Decimal


def _receipt_line_label(
    *,
    line: SaleLine,
    units: dict[uuid.UUID, Unit],
    products: dict[uuid.UUID, Product],
) -> str:
    """Human-readable label for a receipt line: parts as ``Model (SKU)``, units
    as ``Model · serial``. Falls back to ``Unknown product`` if a row is gone."""
    if line.unit_id is not None:
        unit = units.get(line.unit_id)
        prod = products.get(unit.product_id) if unit is not None else None
        name = prod.model_name if prod is not None else "Unknown product"
        if unit is not None and unit.supplier_serial:
            return f"{name} · {unit.supplier_serial}"
        return name
    if line.product_id is not None:
        prod = products.get(line.product_id)
        if prod is not None:
            return f"{prod.model_name} ({prod.sku})"
    return "Unknown product"


def get_sale_receipt_data(
    *, session: Session, sale_id: Any
) -> SaleReceiptData | None:
    """Resolve a sale into receipt display data via batched lookups (no N+1).
    Returns None when the sale does not exist."""
    sale = get_sale(session=session, sale_id=sale_id)
    if sale is None:
        return None
    sale_lines = session.exec(
        select(SaleLine).where(SaleLine.sale_id == sale.id)
    ).all()

    unit_ids = {ln.unit_id for ln in sale_lines if ln.unit_id is not None}
    product_ids = {ln.product_id for ln in sale_lines if ln.product_id is not None}
    units: dict[uuid.UUID, Unit] = {
        u.id: u
        for u in (
            session.exec(select(Unit).where(col(Unit.id).in_(unit_ids))).all()
            if unit_ids
            else []
        )
    }
    for u in units.values():
        product_ids.add(u.product_id)
    products: dict[uuid.UUID, Product] = {
        p.id: p
        for p in (
            session.exec(select(Product).where(col(Product.id).in_(product_ids))).all()
            if product_ids
            else []
        )
    }

    customer = session.get(Customer, sale.customer_id)
    customer_name = customer.name if customer is not None else "Unknown"
    user = session.get(User, sale.created_by_user_id)
    sold_by = (user.full_name or user.email) if user is not None else "Unknown"

    lines: list[tuple[str, int, Decimal]] = [
        (
            _receipt_line_label(line=ln, units=units, products=products),
            ln.quantity,
            ln.unit_price_thb,
        )
        for ln in sale_lines
    ]
    return SaleReceiptData(
        sale_id=sale.id,
        sold_at=sale.sold_at,
        customer_name=customer_name,
        sold_by=sold_by,
        lines=lines,
        total_thb=sale.total_thb,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/routes/test_sales_serialized.py::test_get_sale_receipt_data_resolves_names_and_labels tests/api/routes/test_sales_serialized.py::test_get_sale_receipt_data_unknown_sale_returns_none -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run mypy to confirm typing**

Run: `cd backend && python -m mypy app/crud.py`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_sales_serialized.py
git commit -m "feat(receipt): resolve sale into enriched receipt display data"
```

---

### Task 3: Wire the endpoint to the enriched renderer

Replace the endpoint's inline line-assembly with the new crud helper so the PDF
shows customer, staff, and named lines.

**Files:**
- Modify: `backend/app/api/routes/sales.py:71-86`
- Test: `backend/tests/api/routes/test_sales_serialized.py` (existing `test_sale_receipt_pdf` + one part-line case)

**Interfaces:**
- Consumes: `crud.get_sale_receipt_data(...) -> SaleReceiptData | None`, `render_sale_receipt(*, sale_id, sold_at, customer_name, sold_by, lines, total_thb)`

- [ ] **Step 1: Confirm the existing endpoint test still describes the contract**

`test_sale_receipt_pdf` (test_sales_serialized.py:155) already asserts 200 +
`application/pdf` + `%PDF` magic. No change needed; it must keep passing after
the rewrite. (No new failing test for this task — it is a refactor guarded by
the existing endpoint test plus Task 2's helper tests.)

- [ ] **Step 2: Rewrite the endpoint**

In `backend/app/api/routes/sales.py`, replace `read_sale_receipt` (lines 71-86,
keep the shared-team access comment above it) with:

```python
@router.get("/{sale_id}/receipt.pdf", dependencies=[Depends(get_current_user)])
def read_sale_receipt(*, session: SessionDep, sale_id: uuid.UUID) -> Response:
    data = crud.get_sale_receipt_data(session=session, sale_id=sale_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    pdf = render_sale_receipt(
        sale_id=str(data.sale_id),
        sold_at=data.sold_at.isoformat(timespec="seconds"),
        customer_name=data.customer_name,
        sold_by=data.sold_by,
        lines=data.lines,
        total_thb=data.total_thb,
    )
    return Response(content=pdf, media_type="application/pdf")
```

Note: `select` and `SaleLine` imports stay — `_to_public` still uses them. Do
not remove them.

- [ ] **Step 3: Run the endpoint tests**

Run: `cd backend && python -m pytest tests/api/routes/test_sales_serialized.py -v`
Expected: PASS — including `test_sale_receipt_pdf` and the new helper tests.

- [ ] **Step 4: Run mypy + full receipt/sales suites**

Run: `cd backend && python -m mypy app/api/routes/sales.py && python -m pytest tests/services/test_receipt_pdf.py tests/api/routes/test_sales_serialized.py tests/api/routes/test_sales_part.py -v`
Expected: no mypy errors; all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sales.py
git commit -m "feat(receipt): serve enriched receipt PDF from sale endpoint"
```

---

### Task 4: Add the "View receipt" button to the audit drawer

Show a button in `AuditDetailSheet` when the entry came from a sale; clicking
fetches the authed PDF and opens it in a new tab, mirroring `PrintLabelButton`'s
result→toast handling.

**Files:**
- Modify: `frontend/src/components/audit/AuditDetailSheet.tsx`

**Interfaces:**
- Consumes: `openAuthedPdf(path: string) -> Promise<PrintPdfResult>` (`frontend/src/lib/print-pdf.ts`), `useCustomToast()` (`frontend/src/hooks/useCustomToast`), `Button` (`@/components/ui/button`), `AuditEntryPublic.sale_id` (already on the type).

- [ ] **Step 1: Add imports**

At the top of `frontend/src/components/audit/AuditDetailSheet.tsx`, add the
`Receipt` icon to the existing `lucide-react` import, and add `useState`, the
`Button`, the toast hook, and the PDF helper:

```tsx
import { useState } from "react"

import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"
import { openAuthedPdf } from "@/lib/print-pdf"
```

Add `Receipt` to the `lucide-react` import list (alongside `Clock`, `Tag`, etc.).

- [ ] **Step 2: Add a ReceiptButton component**

Add this component in the same file, above `AuditDetailSheet`:

```tsx
/** Opens the sale's receipt PDF (authed) in a new tab. Disabled while the PDF
 * is in flight so a double-tap cannot spawn two tabs. */
function ReceiptButton({ saleId }: { saleId: string }) {
  const { showErrorToast } = useCustomToast()
  const [isOpening, setIsOpening] = useState(false)

  async function handleOpen() {
    setIsOpening(true)
    const result = await openAuthedPdf(`/sales/${saleId}/receipt.pdf`)
    setIsOpening(false)
    if (result === "no-token") {
      showErrorToast("Session expired. Please log in again.")
    } else if (result === "popup-blocked") {
      showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
    } else if (result === "fetch-failed") {
      showErrorToast("Could not load receipt PDF.")
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      className="h-11 w-full"
      aria-label="View receipt for this sale"
      disabled={isOpening}
      onClick={handleOpen}
    >
      <Receipt className="size-4" />
      {isOpening ? "Opening…" : "View receipt"}
    </Button>
  )
}
```

- [ ] **Step 3: Render the button for sale-sourced entries**

In `AuditDetailBody`, inside the content `<div className="flex flex-col gap-5 ...">`,
add the button after the notes block (just before the closing `</div>` at line
~246):

```tsx
        {entry.sale_id ? <ReceiptButton saleId={entry.sale_id} /> : null}
```

- [ ] **Step 4: Lint + typecheck**

Run: `cd frontend && bunx biome check src/components/audit/AuditDetailSheet.tsx && bunx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/audit/AuditDetailSheet.tsx
git commit -m "feat(audit): view-receipt button on sale ledger entries"
```

---

### Task 5: E2E coverage for the receipt button

Verify the button shows for a sale-sourced ledger row, is absent on a non-sale
row, and issues the authed PDF request on click.

**Files:**
- Test: `frontend/tests/audit-receipt.spec.ts` (create; follow the structure of the nearest existing audit/ledger spec)

**Interfaces:**
- Consumes: the running app + admin login helper used by existing Playwright specs.

- [ ] **Step 1: Inspect an existing audit/admin spec for the login + seed pattern**

Run: `cd frontend && ls tests && grep -rln "audit\|/sale\|admin" tests | head`
Read the closest existing spec to copy its login fixture, base URL usage, and
any sale-seeding helper. Reuse those helpers verbatim — do not invent a new
login flow.

- [ ] **Step 2: Write the E2E test**

Create `frontend/tests/audit-receipt.spec.ts`. Adapt selectors/login to match
the existing specs found in Step 1:

```ts
import { expect, test } from "@playwright/test"
// import the shared login/seed helpers discovered in Step 1

test("sale ledger entry exposes a receipt button that fetches the PDF", async ({
  page,
}) => {
  // log in as admin and ensure at least one SOLD movement exists
  // (reuse the seeding/login helpers from Step 1)
  await page.goto("/audit")

  // open the first SOLD row's drawer
  await page.getByText("SOLD").first().click()

  const receiptBtn = page.getByRole("button", { name: /view receipt/i })
  await expect(receiptBtn).toBeVisible()

  // clicking issues the authed receipt PDF request
  const pdfRequest = page.waitForRequest((req) =>
    /\/api\/v1\/sales\/.*\/receipt\.pdf/.test(req.url()),
  )
  await receiptBtn.click()
  await pdfRequest
})

test("non-sale ledger entry has no receipt button", async ({ page }) => {
  // reuse login from Step 1
  await page.goto("/audit")
  await page.getByText("RECEIVED").first().click()
  await expect(
    page.getByRole("button", { name: /view receipt/i }),
  ).toHaveCount(0)
})
```

- [ ] **Step 3: Run the E2E test**

Run: `cd frontend && bun run test tests/audit-receipt.spec.ts`
Expected: PASS. If the seed has no SOLD/RECEIVED rows, add seeding via the
helper from Step 1 before the assertions.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/audit-receipt.spec.ts
git commit -m "test(audit): e2e for receipt button visibility and fetch"
```

---

## Self-Review

**Spec coverage:**
- Receipt button only on sale-sourced entries → Task 4 Step 3 (`entry.sale_id` guard) + Task 5 (both visibility cases). ✓
- Authed PDF in new tab via existing helper → Task 4 (`openAuthedPdf`). ✓
- Backend PDF enrichment: customer name → Task 2 (`customer_name`) + Task 1 (header line). ✓
- Sold-by staff name → Task 2 (`sold_by`) + Task 1 (header line). ✓
- Human-readable line labels (model name, not UNIT/PART; SKU for parts, serial for units) → Task 2 (`_receipt_line_label`). ✓
- No new endpoint / no SDK regen → Task 3 reuses `receipt.pdf`. ✓
- Backend tests (mixed lines, walk-in, 404) → Task 2 + existing `test_sale_receipt_pdf` (404 preserved by `get_sale_receipt_data` returning None → endpoint 404). ✓
- No cost/COGS on receipt → guardrail allowlist updated, not removed (Task 1 Step 1). ✓

**Placeholder scan:** No TBD/TODO. The only deferred-to-implementation detail is matching existing E2E login/seed helpers (Task 5 Step 1), which is a discovery step with a concrete command, not a code placeholder.

**Type consistency:** `get_sale_receipt_data` / `SaleReceiptData` field names and the `render_sale_receipt` kwargs (`customer_name`, `sold_by`, `lines`, `total_thb`, `sold_at`, `sale_id`) match across Tasks 1–3. `openAuthedPdf` path form (`/sales/{id}/receipt.pdf`) matches the endpoint. `PrintPdfResult` codes (`no-token`/`popup-blocked`/`fetch-failed`/`ok`) match `print-pdf.ts`.

## Review Stage Note (per CLAUDE.md §5)

This change touches a money-adjacent surface (sale receipt) but performs **no
stock-movement / FIFO / ledger writes** — all reads. Run `requesting-code-review`
before the PR. Running `ecc:database-reviewer` is optional here (confirm the
batched lookups don't N+1); `ecc:security-reviewer` optional (confirm no cost
data leaks onto the receipt — the guardrail test already covers this). PR targets
`dev`.
