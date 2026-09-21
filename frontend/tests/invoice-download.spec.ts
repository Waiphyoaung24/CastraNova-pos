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

// Invoice download (design 2026-09-22): staff hand the customer a PDF from
// the customer page's Transactions table (and from the sale-complete card,
// which renders from the same button). Node-side SDK seeding as in
// sale-return.spec.ts. Run with `--workers=1`.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

test.beforeAll(async () => {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
})

test("a sale's invoice opens as a PDF from the customer page", async ({
  page,
  context,
}) => {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `INV-${r}`,
      model_name: `Invoice Part ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "195.00",
      repair_price_thb: "20.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Invoice Supplier ${r}` },
  })
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Invoice Customer ${r}` },
  })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 10,
      purchase_cost_thb: "60.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  await SalesService.createSale({
    requestBody: {
      customer_id: customer.id,
      idempotency_key: crypto.randomUUID(),
      lines: [{ line_kind: "PART", sku: product.sku, quantity: 3 }],
    },
  })

  await page.goto(`/customer/${customer.id}`)
  const row = page.getByRole("row").filter({ hasText: "SALE" })
  await expect(row).toHaveCount(1)

  // The button opens a tab synchronously, then fetches the authed PDF and
  // points the tab at its blob. Assert on the fetch (a blob: navigation is
  // not observable through page.url() in headless Chromium).
  const popup = context.waitForEvent("page")
  const pdf = page.waitForResponse((res) => res.url().includes("/receipt.pdf"))
  await row.getByRole("button", { name: "Download invoice" }).click()
  await popup
  const res = await pdf
  expect(res.status()).toBe(200)
  expect(res.headers()["content-type"]).toContain("application/pdf")
  await expect(page.getByText("Could not load the invoice PDF.")).toHaveCount(0)
})
