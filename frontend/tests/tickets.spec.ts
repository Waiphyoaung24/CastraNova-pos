import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SearchService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser E2E for the Tickets screen (Task 5.2 path: "ticket close"). Same
// harness pattern as sale.spec.ts: Node-side SDK seeding against the live
// stack, random suffixes to dodge shared-dev-DB collisions, web-first /
// expect.poll assertions. Run with `--workers=1`.

OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

/** Authenticate the Node-side SDK client as the superuser for seeding. */
async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SeededPart {
  sku: string
  modelName: string
  customerName: string
}

/** Seed a QUANTITY repair part with stock on hand, plus a ticket customer. */
async function seedRepairPart(onHand: number): Promise<SeededPart> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `PART-${r}`,
      model_name: `Repair Part ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "300.00",
      repair_price_thb: "150.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Ticket Supplier ${r}` },
  })
  const customerName = `Ticket Customer ${r}`
  await CustomersService.createCustomer({ requestBody: { name: customerName } })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: onHand,
      purchase_cost_thb: "50.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  return { sku: product.sku, modelName: product.model_name, customerName }
}

/**
 * Drive the keyboard-wedge scan field. The wedge buffer resets on inter-key
 * gaps >50ms, and Playwright's per-key typing (one CDP roundtrip per key)
 * can stall past that under suite load — so dispatch the whole keydown burst
 * in one in-page evaluate, like a real wedge's ~1ms keystroke stream.
 */
async function scanCode(page: import("@playwright/test").Page, code: string) {
  await expect(
    page.getByRole("textbox", { name: "Scan barcode" }),
  ).toBeVisible()
  await page.evaluate((c) => {
    const el = document.querySelector('input[aria-label="Scan barcode"]')
    if (!el) throw new Error("scan input not found")
    for (const key of [...c, "Enter"]) {
      el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }))
    }
  }, code)
}

test.describe("Tickets screen", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  test("ticket close: issue + scanned part → close → parts consumed from stock", async ({
    page,
  }) => {
    const onHand = 5
    const { sku, modelName, customerName } = await seedRepairPart(onHand)

    // The screen's parts catalog comes from its products query, and a PART
    // scan that resolves before that query lands is silently dropped (no
    // catalog entry yet). Arm the wait before navigating so the scan below
    // can't race the catalog.
    const productsLoaded = page.waitForResponse((r) =>
      r.url().includes("/api/v1/products"),
    )
    await page.goto("/tickets")
    await expect(
      page.getByRole("heading", { name: "Service ticket" }),
    ).toBeVisible()

    await page.getByLabel("Issue").fill("Won't power on")

    // Scan the part SKU once the catalog is live; it lands in the cart at qty 1.
    await productsLoaded
    await scanCode(page, sku)
    await expect(page.getByText(modelName)).toBeVisible()

    // Bump to qty 2 so the quantity provably flows through to consumption.
    await page
      .getByRole("button", { name: `Increase quantity of ${sku}` })
      .click()

    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await page.getByLabel("Resolution (optional)").fill("Replaced part")

    await page.getByRole("button", { name: "Close ticket" }).click()

    // Success surfaces as a toast plus the post-close summary (1 part line,
    // 2 × ฿150.00 repair price = ฿300.00).
    await expect(page.getByText("Ticket closed.")).toBeVisible()
    await expect(
      page.getByText("Ticket closed — 1 part(s), ฿300.00."),
    ).toBeVisible()

    // Authoritative backend assertion: 2 consumed FIFO from the part's stock.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSku({ sku })
          return res.total_on_hand
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe(onHand - 2)
  })

  test("retry after a failed part-add reuses the same idempotency key", async ({
    page,
  }) => {
    const { sku, modelName, customerName } = await seedRepairPart(5)

    // Capture the idempotency_key sent on every openServiceTicket POST, and fail
    // the FIRST add-part so the ticket opens but never completes — exercising the
    // orphan/retry path.
    const openKeys: string[] = []
    let failNextPartAdd = true

    await page.route("**/api/v1/service-tickets", async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as {
          idempotency_key: string
        }
        openKeys.push(body.idempotency_key)
      }
      await route.continue()
    })
    await page.route("**/api/v1/service-tickets/*/parts", async (route) => {
      if (failNextPartAdd) {
        failNextPartAdd = false
        await route.fulfill({ status: 500, body: "{}" })
        return
      }
      await route.continue()
    })

    // Same UI drive as the happy-path test above.
    const productsLoaded = page.waitForResponse((r) =>
      r.url().includes("/api/v1/products"),
    )
    await page.goto("/tickets")
    await expect(
      page.getByRole("heading", { name: "Service ticket" }),
    ).toBeVisible()

    await page.getByLabel("Issue").fill("Won't power on")

    await productsLoaded
    await scanCode(page, sku)
    await expect(page.getByText(modelName)).toBeVisible()

    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()

    // First close: ticket opens, the part-add fails → explicit "retry to resume"
    // message (no cancel endpoint exists to roll the orphan back).
    await page.getByRole("button", { name: "Close ticket" }).click()
    await expect(page.getByText(/retry to resume it/i)).toBeVisible()

    // Retry: this time the part-add and close succeed.
    await page.getByRole("button", { name: "Close ticket" }).click()
    await expect(
      page.getByText("Ticket closed.", { exact: true }),
    ).toBeVisible()

    // The retry must reuse the SAME idempotency key, so the backend dedupes onto
    // the already-opened ticket instead of creating a duplicate.
    expect(openKeys.length).toBeGreaterThanOrEqual(2)
    expect(new Set(openKeys).size).toBe(1)
  })
})
