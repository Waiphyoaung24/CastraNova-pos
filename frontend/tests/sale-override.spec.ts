import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  PricingOverridesService,
  ProductsService,
  ReceiptsService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// FR-010 staff override flow on the Sale screen (S3.5/S3.6 shapes). Node-side
// SDK seeding + admin decisions, browser drives the staff-facing flow.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SeededPart {
  sku: string
  productId: string
  customerName: string
}

/** Seed a sellable QUANTITY (PART) product at ฿1,800 retail with stock. */
async function seedSellablePart(): Promise<SeededPart> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `OVR-${r}`,
      model_name: `Override ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "1800.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  const customerName = `Customer ${r}`
  await CustomersService.createCustomer({ requestBody: { name: customerName } })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 10,
      purchase_cost_thb: "900.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  return { sku: product.sku, productId: product.id, customerName }
}

async function scanCode(page: import("@playwright/test").Page, code: string) {
  const input = page.getByRole("textbox", { name: "Scan barcode" })
  await expect(input).toBeVisible()
  await input.fill(code)
  await input.press("Enter")
}

async function startSale(
  page: import("@playwright/test").Page,
  seeded: SeededPart,
) {
  await page.goto("/sale")
  await page.getByRole("combobox", { name: "Customer" }).click()
  await page
    .getByRole("option", { name: seeded.customerName, exact: true })
    .click()
  await scanCode(page, seeded.sku)
  await expect(
    page.getByRole("cell", { name: seeded.sku, exact: true }),
  ).toBeVisible()
}

/** Fill and submit the override dialog for the line with `sku`. */
async function requestOverride(
  page: import("@playwright/test").Page,
  sku: string,
  price: string,
  reason: string,
) {
  await page.getByRole("button", { name: `Change price of ${sku}` }).click()
  await page.getByLabel("New unit price (฿)").fill(price)
  await page.getByLabel("Reason").fill(reason)
  await page.getByRole("button", { name: "Save price" }).click()
}

/** The browser creates the override; poll the admin list until it appears. */
async function pendingOverrideIdFor(productId: string): Promise<string> {
  let id: string | undefined
  await expect
    .poll(
      async () => {
        const res = await PricingOverridesService.listPricingOverrides({
          state: "PENDING",
          limit: 100,
        })
        id = res.data.find((o) => o.product_id === productId)?.id
        return id
      },
      { timeout: 10_000, intervals: [250, 500, 1_000] },
    )
    .toBeTruthy()
  if (!id) throw new Error("PENDING override not found")
  return id
}

test.describe("Sale price override (FR-010)", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  test("within threshold: override auto-approves and reprices immediately (S3.5 shape)", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)
    // Second scan merges into the same PART line (quantity 2).
    await scanCode(page, seeded.sku)

    await requestOverride(page, seeded.sku, "1750", "matched competitor quote")

    await expect(page.getByText("Price updated.")).toBeVisible()
    // Effective price + line total + subtotal all show the override (2 × 1750).
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿1,750.00")
    await expect(page.getByText("฿3,500.00")).toHaveCount(2) // line total + subtotal

    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText("Sale completed.")).toBeVisible()
  })

  test("over threshold: pending blocks checkout, approval flips the price live (S3.6 shape)", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)

    await requestOverride(page, seeded.sku, "900", "bulk discount")

    await expect(page.getByText("Sent for admin approval.")).toBeVisible()
    await expect(page.getByText(/Pending approval/)).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Complete sale" }),
    ).toBeDisabled()
    // CheckoutPanel renders twice (desktop `hidden md:block` + mobile
    // `md:hidden`, sale.tsx:323-341), so this <p> text resolves two DOM
    // nodes (getByRole for the button above stays unique because
    // display:none elements drop out of the accessibility tree). The desktop
    // pane renders first and is the one visible at Playwright's default
    // viewport, so .first() disambiguates.
    await expect(
      page.getByText("Waiting for override approval").first(),
    ).toBeVisible()

    // Admin decides via the API (Node side) — no reload in the browser.
    const overrideId = await pendingOverrideIdFor(seeded.productId)
    await PricingOverridesService.decidePricingOverride({
      overrideId,
      requestBody: { decision: "APPROVED" },
    })

    // The 4s poll picks the decision up and flips the line without a reload.
    await expect(page.getByText("Override approved.")).toBeVisible({
      timeout: 15_000,
    })
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿900.00")
    await expect(page.getByText(/Pending approval/)).toHaveCount(0)

    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText("Sale completed.")).toBeVisible()
  })

  test("over threshold: rejection reverts to retail and unlocks checkout", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)

    await requestOverride(page, seeded.sku, "900", "bulk discount")
    await expect(page.getByText(/Pending approval/)).toBeVisible()

    const overrideId = await pendingOverrideIdFor(seeded.productId)
    await PricingOverridesService.decidePricingOverride({
      overrideId,
      requestBody: { decision: "REJECTED" },
    })

    await expect(
      page.getByText("Override rejected — price reverted."),
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿1,800.00")
    await expect(
      page.getByRole("button", { name: "Complete sale" }),
    ).toBeEnabled()
  })
})
