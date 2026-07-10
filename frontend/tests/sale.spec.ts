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
 * + a customer + a received piece. Returns the unit's scannable
 * castranova_barcode and the customer name (which the Sale screen requires the
 * operator to select explicitly — nothing is auto-selected).
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
  const customerName = `Customer ${r}`
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

  test("sale: no customer is auto-selected and checkout is blocked until one is chosen (FR-007)", async ({
    page,
  }) => {
    const { barcode } = await seedSellableUnit()

    await page.goto("/sale")
    await expect(
      page.getByRole("heading", { name: "Sale", exact: true }),
    ).toBeVisible()

    // PRD FR-007: no walk-in / anonymous sales. The Customer field must start
    // empty (placeholder showing) — nothing is auto-selected on load.
    await expect(
      page.getByRole("combobox", { name: "Customer" }),
    ).toHaveText("Select a customer")

    // Even with a unit in the cart, checkout stays disabled until a customer
    // is explicitly chosen.
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Complete sale" }),
    ).toBeDisabled()
  })

  test("sale online: scan a serialized unit and complete the sale → unit is SOLD", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    await page.goto("/sale")
    await expect(
      page.getByRole("heading", { name: "Sale", exact: true }),
    ).toBeVisible()

    // No customer is auto-selected — the operator must choose one explicitly.
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

  // Task 3 — offline < 12h: the access token expired during the outage but the
  // refresh token is still valid, so reconnect refreshes silently and the queued
  // sale replays with the fresh token — no re-login, no data loss. The harness
  // is cross-site (SameSite=lax withholds the refresh cookie), so we mock
  // /login/refresh-token with a real minted token; the real cookie exchange is
  // covered by backend test_auth_refresh.py.
  test("offline < 12h → reconnect refreshes silently → sale replays once", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()
    const fresh = await LoginService.loginAccessToken({
      formData: {
        username: firstSuperuser,
        password: firstSuperuserPassword,
      },
    })
    await page.route("**/api/v1/login/refresh-token", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: fresh.access_token }),
      }),
    )

    await page.goto("/sale")
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    // Queue the sale offline.
    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()
    await waitForPersistedPausedMutation(page)

    // Simulate the access token expiring during the outage (the refresh cookie
    // is still valid → the mock stands in for it). Reconnect via reload.
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Stayed logged in; the replay committed exactly once with the fresh token.
    await expect
      .poll(
        async () =>
          (await SearchService.searchSerial({ barcode })).current_state,
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")
    await expect(page).not.toHaveURL(/\/login/)
    const okRes = await SearchService.searchSerial({ barcode })
    expect(okRes.movements.filter((m) => m.event_type === "SOLD")).toHaveLength(
      1,
    )
  })

  // Task 3 — offline > 12h: the refresh token has also expired, so reconnect
  // can't revive the session → redirect to /login. But the queued sale stays
  // PAUSED (never fired, never errored), survives the forced logout, and replays
  // after re-login (idempotency dedupes) — re-auth required, zero data loss.
  test("offline > 12h → reconnect forces re-login → queue survives → replays once", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    await page.goto("/sale")
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()
    await waitForPersistedPausedMutation(page)

    // Simulate 12h idle: the refresh cookie is gone AND the access token is
    // dead, so refresh can't revive the session. Reconnect via reload.
    await page.context().clearCookies()
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Forced re-login; the queued mutation is still persisted (not errored out).
    await expect(page).toHaveURL(/\/login/)
    await waitForPersistedPausedMutation(page)

    // Log back in; login() flushes the paused queue with the new token.
    await page.getByTestId("email-input").fill(firstSuperuser)
    await page.getByTestId("password-input").fill(firstSuperuserPassword)
    await page.getByRole("button", { name: "Log In" }).click()
    await page.waitForURL("/")

    await expect
      .poll(
        async () =>
          (await SearchService.searchSerial({ barcode })).current_state,
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")
    const okRes = await SearchService.searchSerial({ barcode })
    expect(okRes.movements.filter((m) => m.event_type === "SOLD")).toHaveLength(
      1,
    )
  })
})
