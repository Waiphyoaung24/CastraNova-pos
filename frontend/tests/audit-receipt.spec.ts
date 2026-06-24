import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SalesService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser coverage for the audit drawer's "View receipt" action: a sale-sourced
// movement exposes a button that fetches the sale's receipt PDF; a non-sale
// movement (RECEIVED) does not. Seeds a serialized unit, sells it via the SDK so
// both a SOLD and a RECEIVED movement reference the same unit, then drives /audit.

OpenAPI.BASE = `${process.env.VITE_API_URL}`
const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

/** Receive one serialized unit and sell it. Returns the unit id (its 8-char
 * prefix labels the audit rows). */
async function seedSoldUnit(): Promise<string> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `RCPT-${r}`,
      model_name: `Receipt Model ${r}`,
      tracking_mode: "SERIALIZED",
      retail_price_thb: "1500.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Sup ${r}` },
  })
  const recv = await ReceiptsService.receiveSerialized({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      pieces: [{ supplier_serial: `SN-${r}`, purchase_cost_thb: "800.00" }],
      idempotency_key: crypto.randomUUID(),
    },
  })
  const unit = recv.units[0]
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Walk-in ${r}` },
  })
  await SalesService.createSale({
    requestBody: {
      customer_id: customer.id,
      lines: [
        { line_kind: "UNIT", castranova_barcode: unit.castranova_barcode },
      ],
      idempotency_key: crypto.randomUUID(),
    },
  })
  return unit.id
}

test.describe("Audit drawer — receipt button", () => {
  test.beforeAll(authSeedClient)

  test("a sale movement exposes a receipt button that fetches the PDF", async ({
    page,
  }) => {
    const unitId = await seedSoldUnit()

    await page.goto("/audit")
    await page
      .getByRole("button", {
        name: `View details: SOLD Unit ·${unitId.slice(0, 8)}`,
      })
      .first()
      .click()

    const drawer = page.getByRole("dialog")
    await expect(drawer).toBeVisible()
    const receiptBtn = drawer.getByRole("button", { name: /view receipt/i })
    await expect(receiptBtn).toBeVisible()

    // Clicking issues the authed receipt PDF request for this sale.
    const pdfRequest = page.waitForRequest((req) =>
      /\/api\/v1\/sales\/.*\/receipt\.pdf/.test(req.url()),
    )
    await receiptBtn.click()
    await pdfRequest
  })

  test("a non-sale movement has no receipt button", async ({ page }) => {
    const unitId = await seedSoldUnit()

    await page.goto("/audit")
    await page
      .getByRole("button", {
        name: `View details: RECEIVED Unit ·${unitId.slice(0, 8)}`,
      })
      .first()
      .click()

    const drawer = page.getByRole("dialog")
    await expect(drawer).toBeVisible()
    await expect(
      drawer.getByRole("button", { name: /view receipt/i }),
    ).toHaveCount(0)
  })
})
