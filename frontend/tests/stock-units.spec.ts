import { expect, test } from "@playwright/test"

import {
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser coverage for the serialized-unit drill-down on the Stock screen:
// expanding a SERIALIZED SKU lists its in-stock units with CastraNova barcodes
// (closes the "no UI shows a unit's barcode after receive" gap).

OpenAPI.BASE = `${process.env.VITE_API_URL}`
const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

test.describe("Stock — serialized unit drill-down", () => {
  test.beforeAll(authSeedClient)

  test("expanding a serialized SKU lists its units with CastraNova barcodes", async ({
    page,
  }) => {
    const r = rand()
    const sku = `SER-${r}`
    const product = await ProductsService.createProduct({
      requestBody: {
        sku,
        model_name: `Model ${r}`,
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
    const barcode = recv.units[0].castranova_barcode

    await page.goto("/stock")
    await page.getByPlaceholder("Search by name or barcode…").fill(sku)
    await page.getByRole("button", { name: `Expand ${sku}` }).click()

    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    // Each in-stock unit row carries a reprint action (lost-label reprint):
    // the button is labelled by supplier serial so it survives re-ordering.
    await expect(
      page.getByRole("button", { name: `Print label for serial SN-${r}` }),
    ).toBeVisible()
  })
})
