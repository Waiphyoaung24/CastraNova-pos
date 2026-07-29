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

// Sale returns (design 2026-07-25). Node-side SDK seeding mirrors sale.spec.ts:
// these calls run in the Playwright process and authenticate independently as
// the superuser; the browser uses the storageState token.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

/** Random suffix to dodge shared-dev-DB collisions on sku/serial/name. */
const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SoldUnit {
  barcode: string
  customerName: string
}

/** Receive one SERIALIZED unit and sell it. */
async function seedSoldUnit(): Promise<SoldUnit> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `RET-U-${r}`,
      model_name: `Returnable ${r}`,
      tracking_mode: "SERIALIZED",
      retail_price_thb: "1500.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  const customerName = `Customer ${r}`
  const customer = await CustomersService.createCustomer({
    requestBody: { name: customerName },
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
  await SalesService.createSale({
    requestBody: {
      customer_id: customer.id,
      idempotency_key: crypto.randomUUID(),
      lines: [{ line_kind: "UNIT", castranova_barcode: barcode }],
    },
  })
  return { barcode, customerName }
}

interface SoldPart {
  sku: string
  customerName: string
}

/** Receive a QUANTITY batch and sell 5 of it. */
async function seedSoldPart(): Promise<SoldPart> {
  const r = rand()
  const sku = `RET-P-${r}`
  const product = await ProductsService.createProduct({
    requestBody: {
      sku,
      model_name: `Part ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "100.00",
      repair_price_thb: "20.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  const customerName = `Customer ${r}`
  const customer = await CustomersService.createCustomer({
    requestBody: { name: customerName },
  })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 10,
      purchase_cost_thb: "10.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  await SalesService.createSale({
    requestBody: {
      customer_id: customer.id,
      idempotency_key: crypto.randomUUID(),
      lines: [{ line_kind: "PART", sku, quantity: 5 }],
    },
  })
  return { sku, customerName }
}

test.beforeEach(async () => {
  await authSeedClient()
})

test("a sold unit can be returned to stock from the adjustment screen", async ({
  page,
}) => {
  const { barcode, customerName } = await seedSoldUnit()

  await page.goto("/stock-adjustment")
  await page.getByRole("tab", { name: "Serialized unit" }).click()
  await page.getByRole("textbox", { name: "Scan barcode" }).fill(barcode)

  // The lookup resolves the barcode to its sale and offers the return.
  await expect(page.getByText(/this unit was sold/i)).toBeVisible()
  await expect(page.getByText(customerName)).toBeVisible()
  // Write-off is withdrawn while a return is on offer.
  await expect(
    page.getByRole("button", { name: "Record adjustment" }),
  ).toHaveCount(0)

  await page
    .getByRole("textbox", { name: /reason for the return/i })
    .fill("customer changed their mind")
  await page.getByRole("button", { name: "Return to stock" }).click()

  await expect(page.getByText(/back on hand/i)).toBeVisible()

  // The unit really is IN_STOCK again — the return offer is gone on a re-scan.
  const { sales } = await SalesService.readReturnableSales({
    castranovaBarcode: barcode,
  })
  expect(sales).toHaveLength(0)
})

test("a quantity sale line can be partially returned via the sale picker", async ({
  page,
}) => {
  const { sku } = await seedSoldPart()

  await page.goto("/stock-adjustment")
  await page.getByRole("tab", { name: "Quantity SKU" }).click()
  await page.getByRole("tab", { name: "Return" }).click()
  await page.getByRole("textbox", { name: "Scan barcode" }).fill(sku)

  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: /5 of 5 returnable/ }).click()

  await page.getByRole("textbox", { name: /quantity returned/i }).fill("2")
  await page
    .getByRole("textbox", { name: /reason for the return/i })
    .fill("wrong part ordered")
  await page.getByRole("button", { name: "Record return" }).click()

  await expect(page.getByText(/back on hand/i)).toBeVisible()

  // 3 of the 5 remain returnable.
  const { sales } = await SalesService.readReturnableSales({ sku })
  expect(sales[0].lines[0].quantity_returnable).toBe(3)
  expect(sales[0].lines[0].quantity_returned).toBe(2)
})
