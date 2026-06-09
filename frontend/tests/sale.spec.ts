import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  type ReceiveSerializedResponse,
  SearchService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Node-side SDK seeding, mirroring tests/utils/privateApi.ts. The browser uses
// the storageState token; these calls run in the Playwright (Node) process and
// authenticate independently as the superuser.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

/** Random suffix to dodge shared-dev-DB collisions on sku/serial/name. */
const rand = () => Math.random().toString(36).slice(2, 10)

/** Authenticate the Node-side SDK client as the superuser for seeding. */
async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SeededUnit {
  barcode: string
  customerName: string
}

/**
 * Seed one sellable serialized UNIT end-to-end: product (SERIALIZED) + supplier
 * + a walk-in-named customer (so the Sale screen auto-selects it) + a received
 * piece. Returns the unit's scannable castranova_barcode and the customer name.
 */
async function seedSellableUnit(): Promise<SeededUnit> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `SKU-${r}`,
      model_name: `Model ${r}`,
      tracking_mode: "SERIALIZED",
      retail_price_thb: "1500.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  // Name matches the Sale screen's /walk[\s-]?in/i default-select pattern.
  const customerName = `Walk-in ${r}`
  await CustomersService.createCustomer({ requestBody: { name: customerName } })
  const recv: ReceiveSerializedResponse =
    await ReceiptsService.receiveSerialized({
      requestBody: {
        product_id: product.id,
        supplier_id: supplier.id,
        pieces: [{ supplier_serial: `SN-${r}`, purchase_cost_thb: "800.00" }],
        idempotency_key: crypto.randomUUID(),
      },
    })
  const unit = recv.units[0]
  expect(unit.current_state).toBe("IN_STOCK")
  return { barcode: unit.castranova_barcode, customerName }
}

/**
 * Drive the keyboard-wedge scan field: focus, type fast (<50ms inter-key gaps so
 * the wedge buffer doesn't reset), then commit with Enter.
 */
async function scanBarcode(
  page: import("@playwright/test").Page,
  code: string,
) {
  const scan = page.getByRole("textbox", { name: "Scan barcode" })
  await scan.click()
  await scan.pressSequentially(code, { delay: 5 })
  await page.keyboard.press("Enter")
}

test.describe("Sale screen", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  test("sale online: scan a serialized unit and complete the sale → unit is SOLD", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    await page.goto("/sale")
    await expect(
      page.getByRole("heading", { name: "Sale", exact: true }),
    ).toBeVisible()

    // The seeded customer is named "Walk-in …" so the screen auto-selects it;
    // make that explicit (and robust if multiple walk-ins exist in shared DB).
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await expect(page.getByRole("combobox", { name: "Customer" })).toHaveText(
      customerName,
    )

    await scanBarcode(page, barcode)

    // The scanned unit becomes a cart line keyed by its barcode. Use exact match:
    // the barcode also appears inside qty/remove button aria-labels in the row.
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    // Desktop checkout pane (md+ viewport — Playwright's default is 1280×720).
    await page.getByRole("button", { name: "Complete sale" }).click()

    // Success surfaces as a toast and the cart clearing.
    await expect(page.getByText("Sale completed.")).toBeVisible()
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toHaveCount(0)

    // Authoritative assertion: the backend marks the unit SOLD.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSerial({ barcode })
          return res.current_state
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")
  })

  // Finalized under Part 5.2: the offline → reload → reconnect → replay path
  // depends on TanStack Query mutation persistence rehydrating across a full
  // page reload and replaying exactly once on reconnect. Making that
  // deterministic in E2E needs a controlled service-worker / persist-cache
  // harness (waiting on the persister to flush before reload, and on rehydration
  // + resumePausedMutations after reconnect) that doesn't exist in this
  // environment. Authored here under the 5.2 banner; run when that harness lands.
  test.fixme(
    "sale offline → reload → reconnect → replays exactly once (idempotent)",
    async ({ page, context }) => {
      const { barcode, customerName } = await seedSellableUnit()

      // Load online so products/customers cache and the persister is ready.
      await page.goto("/sale")
      await page.getByRole("combobox", { name: "Customer" }).click()
      await page
        .getByRole("option", { name: customerName, exact: true })
        .click()
      await expect(page.getByRole("combobox", { name: "Customer" })).toHaveText(
        customerName,
      )
      await scanBarcode(page, barcode)
      await expect(
        page.getByRole("cell", { name: barcode, exact: true }),
      ).toBeVisible()

      // Go offline and complete the sale — the mutation should queue (pause).
      await context.setOffline(true)
      await page.getByRole("button", { name: "Complete sale" }).click()

      // OfflineIndicator renders an aria-live region with a queued-change count.
      await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()

      // Reload, then reconnect — the persisted mutation should rehydrate and
      // replay exactly once.
      await page.reload()
      await context.setOffline(false)

      // Exactly-once: the unit ends SOLD (single decrement, no double sale).
      await expect
        .poll(
          async () => {
            const res = await SearchService.searchSerial({ barcode })
            return res.current_state
          },
          { timeout: 15_000, intervals: [500, 1_000] },
        )
        .toBe("SOLD")
    },
  )
})
