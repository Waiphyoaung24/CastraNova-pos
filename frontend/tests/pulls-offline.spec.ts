import type { Page } from "@playwright/test"
import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ProjectPullsService,
  ProjectsService,
  ReceiptsService,
  SuppliersService,
  SyncReviewService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Node-side SDK seeding, mirroring sale.spec.ts. These calls run in the
// Playwright (Node) process and authenticate independently as the superuser;
// the browser uses the storageState token.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

/** Random suffix to dodge shared-dev-DB collisions on sku/code/name. */
const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SeededPull {
  pullId: string
  projectCode: string
  partLabel: string
}

/**
 * Seed one PENDING project pull with a single in-stock QUANTITY (PART) line of
 * requested_qty 1 — enough stock so the fulfill can settle FULFILLED. Returns
 * the identifiers used to drive and assert the UI. Random suffixes keep this
 * isolated on the shared dev DB.
 */
async function seedPendingPartPull(): Promise<SeededPull> {
  const r = rand()
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Customer ${r}` },
  })
  const project = await ProjectsService.createProject({
    requestBody: {
      code: `PRJ-${r}`,
      name: `Project ${r}`,
      customer_id: customer.id,
    },
  })
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `SKU-${r}`,
      model_name: `Model ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "120.00",
      repair_price_thb: "0.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  // Stock the part so the pull line can be fulfilled from a FIFO batch.
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 5,
      purchase_cost_thb: "80.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  const pull = await ProjectPullsService.createProjectPull({
    requestBody: {
      project_id: project.id,
      lines: [{ line_kind: "PART", product_id: product.id, requested_qty: 1 }],
    },
  })
  return { pullId: pull.id, projectCode: `PRJ-${r}`, partLabel: `Model ${r}` }
}

/**
 * Deterministic reload point for the offline tests: poll IndexedDB (idb-keyval's
 * `keyval-store`/`keyval`, where the async-storage persister writes under
 * REACT_QUERY_OFFLINE_CACHE) until a paused mutation has been flushed. The
 * persister throttles writes, so reloading before this would drop the queue.
 * (Copied from sale.spec.ts — same harness.)
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

/**
 * Open the pull's fulfill panel from the queue (targeting its row by the unique
 * project code, since the shared DB holds many pulls) and stage its single PART
 * line to its cap (1 of 1).
 */
async function openAndStageFulfill(page: Page, seeded: SeededPull) {
  await page.goto("/pulls")
  await expect(
    page.getByRole("heading", { name: "Stock requests", exact: true }),
  ).toBeVisible()
  const row = page.getByRole("row").filter({ hasText: seeded.projectCode })
  await row.getByRole("button", { name: "Give out parts" }).click()
  await page
    .getByRole("button", { name: `Increase ${seeded.partLabel}` })
    .click()
  await expect(page.getByText("All items ready")).toBeVisible()
}

/** Current state of a pull, by id, via the Node SDK (no get-by-id endpoint). */
async function pullStateById(pullId: string): Promise<string | undefined> {
  const pulls = await ProjectPullsService.readProjectPulls({})
  return pulls.find((p) => p.id === pullId)?.state
}

/** Whether a PENDING CONFLICT sync-review item exists for this pull. */
async function hasConflictItemFor(pullId: string): Promise<boolean> {
  const items = await SyncReviewService.listSyncReviewItems({
    state: "PENDING",
  })
  return items.some(
    (it) =>
      it.mutation_kind === "pull-fulfill" &&
      it.reason === "CONFLICT" &&
      (it.payload as { pullId?: string }).pullId === pullId,
  )
}

test.describe("Project-pull offline", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  // Mirrors sale.spec.ts's offline harness: the dev server has no service
  // worker, so the page goes offline *synthetically* via a window "offline"
  // event (TanStack's onlineManager subscribes to it and pauses the mutation);
  // the reload waits until the paused mutation lands in IndexedDB, then the
  // fresh (online) load rehydrates and resumePausedMutations replays the fulfill.
  test("pull offline → reload → reconnect → replays once (FULFILLED)", async ({
    page,
  }) => {
    const seeded = await seedPendingPartPull()

    await openAndStageFulfill(page, seeded)

    // Go offline and give out the parts — the mutation queues (pauses).
    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Done — give out parts" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()

    // Reload only once the queued mutation is persisted; the fresh online load
    // rehydrates and replays it.
    await waitForPersistedPausedMutation(page)
    await page.reload()

    // The queue survived: the replayed fulfill settles the pull FULFILLED.
    await expect
      .poll(() => pullStateById(seeded.pullId), {
        timeout: 15_000,
        intervals: [500, 1_000],
      })
      .toBe("FULFILLED")

    // A clean replay is not a conflict: nothing was diverted to the review queue.
    expect(await hasConflictItemFor(seeded.pullId)).toBe(false)
  })

  // The producer's conflict path. fulfill_project_pull is idempotent for an
  // already-settled pull (returns 200), so a re-fulfill is NOT a conflict — a
  // genuine 409 comes from the pull being CANCELLED underneath the queued
  // fulfill (crud.py: "Project pull is cancelled", 409). That is the real
  // collision: admin cancels while staff's fulfill waits offline. On reconnect
  // the replay 409s and the producer diverts it to the admin review queue.
  test("pull cancelled online while queued offline → CONFLICT in review queue", async ({
    page,
  }) => {
    const seeded = await seedPendingPartPull()

    await openAndStageFulfill(page, seeded)

    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Done — give out parts" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()
    await waitForPersistedPausedMutation(page)

    // Cancel the pull online (admin), so the queued fulfill will 409 on replay.
    await ProjectPullsService.cancelProjectPull({ pullId: seeded.pullId })
    await expect
      .poll(() => pullStateById(seeded.pullId), {
        timeout: 10_000,
        intervals: [500, 1_000],
      })
      .toBe("CANCELLED")

    // Reconnect → replay 409s → the producer posts a CONFLICT review item.
    await page.reload()

    await expect
      .poll(() => hasConflictItemFor(seeded.pullId), {
        timeout: 15_000,
        intervals: [500, 1_000],
      })
      .toBe(true)
  })
})
