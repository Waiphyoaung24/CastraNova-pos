import { expect, test } from "@playwright/test"

import {
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SearchService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser coverage for the Stock adjustment page (FR-011). The Return flow
// moved to /returns on 2026-09-21, so this pins what is left: Found / Lost
// only, admin browser (superuser storageState).
OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

test.beforeEach(async () => {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
})

test("admin can write off one unit of a quantity SKU", async ({ page }) => {
  const r = rand()
  const sku = `ADJ-P-${r}`
  const product = await ProductsService.createProduct({
    requestBody: {
      sku,
      model_name: `Adjustable ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "100.00",
      repair_price_thb: "20.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 3,
      purchase_cost_thb: "10.00",
      idempotency_key: crypto.randomUUID(),
    },
  })

  await page.goto("/stock-adjustment")
  await page.getByRole("tab", { name: "Quantity SKU" }).click()
  // The Return toggle no longer lives here.
  await expect(page.getByRole("tab", { name: "Return" })).toHaveCount(0)

  await page.getByRole("textbox", { name: "Scan barcode" }).fill(sku)
  await page.getByRole("textbox", { name: /quantity delta/i }).fill("-1")
  await page.getByRole("textbox", { name: "Reason" }).fill("damaged in store")
  await page.getByRole("button", { name: "Record adjustment" }).click()

  await expect(page.getByText("Adjustment recorded.")).toBeVisible()
  const res = await SearchService.searchSku({ sku })
  expect(res.total_on_hand).toBe(2)
})
