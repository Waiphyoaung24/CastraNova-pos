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
 * Drive the scan field. ScanField is typing-first — the input's value is the
 * source of truth and Enter commits it via onScan. Fill the value (which fires
 * the change the controlled input needs) and press Enter; there is no wedge
 * inter-key timing to worry about on this path.
 */
async function scanBarcode(
  page: import("@playwright/test").Page,
  code: string,
) {
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
 */
async function waitForPersistedPausedMutation(
  page: import("@playwright/test").Page,
) {
  // expect.poll + page.evaluate, NOT page.waitForFunction: waitForFunction
  // treats the pending Promise an async predicate returns as truthy, which
  // would pass immediately — before the persister's throttled flush lands.
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

  // The 5.2 headline path. Two constraints shape the harness:
  // 1. The dev server runs without a service worker (VitePWA devOptions are
  //    off), so a network-level offline (context.setOffline) would make the
  //    post-queue reload unable to load the app shell. Instead the page goes
  //    offline *synthetically* via a window "offline" event — TanStack's
  //    onlineManager and the OfflineIndicator both subscribe to exactly that
  //    event, so the mutation pauses the same way it does on a dead network.
  // 2. The async-storage persister throttles IndexedDB writes, so the reload
  //    waits until the paused mutation is observed in IndexedDB.
  // The fresh load is online again (= reconnect), rehydrates the persisted
  // client, and resumePausedMutations replays the queued sale with its
  // original idempotency key.
  test("sale offline → reload → reconnect → replays exactly once (idempotent)", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    // Load online so products/customers cache and the persister is ready.
    await page.goto("/sale")
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await expect(page.getByRole("combobox", { name: "Customer" })).toHaveText(
      customerName,
    )
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    // Go offline and complete the sale — the mutation queues (pauses).
    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Complete sale" }).click()

    // OfflineIndicator renders an aria-live region with a queued-change count.
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()

    // Reload only once the queued mutation has been persisted, then let the
    // fresh (online) load rehydrate and replay it.
    await waitForPersistedPausedMutation(page)
    await page.reload()

    // The queue survived the reload: the replayed sale marks the unit SOLD.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSerial({ barcode })
          return res.current_state
        },
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")

    // No dup on replay: the unit's append-only ledger carries exactly one
    // SOLD movement (the idempotency key dedupes any second delivery).
    const res = await SearchService.searchSerial({ barcode })
    expect(res.movements.filter((m) => m.event_type === "SOLD")).toHaveLength(1)
  })
})
