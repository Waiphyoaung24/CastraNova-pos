import type { Page } from "@playwright/test"
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
 * Drive the scan field. ScanField is typing-first — the input's value is the
 * source of truth and Enter commits it via onScan. Fill the value (which fires
 * the change the controlled input needs) and press Enter; there is no wedge
 * inter-key timing to worry about on this path.
 */
async function scanCode(page: import("@playwright/test").Page, code: string) {
  const input = page.getByRole("textbox", { name: "Scan barcode" })
  await expect(input).toBeVisible()
  await input.fill(code)
  await input.press("Enter")
}

/**
 * Deterministic reload point for the offline test: poll IndexedDB (idb-keyval's
 * `keyval-store`/`keyval`, where the async-storage persister writes under
 * REACT_QUERY_OFFLINE_CACHE) until a paused mutation has been flushed. The
 * persister throttles writes, so reloading before this would drop the queue.
 * (Copied from pulls-offline.spec.ts — same harness.)
 */
async function waitForPersistedPausedMutation(page: Page) {
  await expect
    .poll(
      () =>
        page.evaluate(async () => {
          const raw: unknown = await new Promise((resolve, reject) => {
            const open = indexedDB.open("keyval-store")
            open.onerror = () => reject(open.error)
            open.onsuccess = () => {
              const db = open.result
              if (!db.objectStoreNames.contains("keyval")) {
                db.close()
                resolve(undefined)
                return
              }
              const req = db
                .transaction("keyval", "readonly")
                .objectStore("keyval")
                .get("REACT_QUERY_OFFLINE_CACHE")
              req.onsuccess = () => {
                db.close()
                resolve(req.result)
              }
              req.onerror = () => {
                db.close()
                reject(req.error)
              }
            }
          })
          if (typeof raw !== "string") return false
          const persisted = JSON.parse(raw) as {
            clientState?: {
              mutations?: Array<{ state?: { isPaused?: boolean } }>
            }
          }
          return (persisted.clientState?.mutations ?? []).some(
            (m) => m.state?.isPaused,
          )
        }),
      { timeout: 10_000, intervals: [250, 500, 1_000] },
    )
    .toBe(true)
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
    await page.getByLabel("What was done (optional)").fill("Replaced part")

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

  // FR-008 / §8.3: a ticket closed offline is saved on the device and replays
  // once on reconnect. The atomic record endpoint is idempotent on its
  // idempotency_key, so the replay consumes stock exactly once (the old 3-call
  // flow could not guarantee this — its non-idempotent part-add could duplicate).
  test("ticket offline → reload → reconnect → replays once (parts consumed)", async ({
    page,
  }) => {
    const onHand = 5
    const { sku, modelName, customerName } = await seedRepairPart(onHand)

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
    // Bump to qty 2 so the consumed quantity is provable after replay.
    await page
      .getByRole("button", { name: `Increase quantity of ${sku}` })
      .click()
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()

    // Go offline and close the ticket — the record mutation queues (pauses).
    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Close ticket" }).click()

    // Reload only once the queued mutation is persisted; the fresh online load
    // rehydrates and resumePausedMutations replays the record.
    await waitForPersistedPausedMutation(page)
    await page.reload()

    // The queue survived and replayed exactly once: 2 consumed FIFO from stock.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSku({ sku })
          return res.total_on_hand
        },
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe(onHand - 2)
  })
})
