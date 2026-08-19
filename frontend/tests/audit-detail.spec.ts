import { expect, test } from "@playwright/test"

import {
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser coverage for the audit ledger row -> detail drawer (FR-019): clicking
// a movement opens a Sheet carrying the enriched, human-readable detail (product
// model, full shop barcode, maker's serial) that the audit endpoint now
// hydrates — none of which the terse table row shows.

OpenAPI.BASE = `${process.env.VITE_API_URL}`
const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

test.describe("Audit ledger — row detail drawer", () => {
  test.beforeAll(authSeedClient)

  test("clicking a movement opens a drawer with enriched unit detail", async ({
    page,
  }) => {
    const r = rand()
    const product = await ProductsService.createProduct({
      requestBody: {
        sku: `AUD-${r}`,
        model_name: `Audit Model ${r}`,
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

    await page.goto("/audit")

    // The RECEIVED unit movement row is a button labelled by event + item ref.
    await page
      .getByRole("button", {
        name: `View details: RECEIVED Unit ·${unit.id.slice(0, 8)}`,
      })
      .first()
      .click()

    // The drawer surfaces the hydrated detail the table row doesn't carry.
    const drawer = page.getByRole("dialog")
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText(`Audit Model ${r}`)).toBeVisible()
    await expect(drawer.getByText(unit.castranova_barcode)).toBeVisible()
    await expect(drawer.getByText(`SN-${r}`)).toBeVisible()
  })
})
