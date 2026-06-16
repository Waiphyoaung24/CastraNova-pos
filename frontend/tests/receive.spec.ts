import { expect, test } from "@playwright/test"

import {
  OpenAPI,
  type ProductPublic,
  ProductsService,
  ReceiptsService,
  SearchService,
  type SupplierPublic,
  SuppliersService,
  UsersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config"
import { tokenFor, withToken } from "./utils/auth"
import { createStaffUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

// E2E for the Receive screen (spec §5.2). Same harness pattern as the rest of
// the suite: SDK-based seeding against the live stack, random suffixes to avoid
// shared-DB collisions, and web-first / expect.poll assertions (no fixed
// sleeps). Run with `--workers=1`. These run "under the 5.2 banner".

OpenAPI.BASE = `${process.env.VITE_API_URL}`

// Unique suffix per spec run — keeps SKUs / serials collision-free on the
// shared dev DB.
const suffix = () => Math.random().toString(36).substring(2, 10)

// Track staff users seeded across the suite so an afterAll can delete them —
// the shared dev DB pitfall note flags test-user pollution explicitly.
const seededStaffUserIds: string[] = []

/** Create a staff user and remember its id for afterAll cleanup. */
async function seedStaffUser(): Promise<{ email: string; password: string }> {
  const email = randomEmail()
  const password = randomPassword()
  const user = await createStaffUser({ email, password })
  seededStaffUserIds.push(user.id)
  return { email, password }
}

async function seedProduct(
  tracking: "SERIALIZED" | "QUANTITY",
): Promise<ProductPublic> {
  return ProductsService.createProduct({
    requestBody: {
      sku: `CN-${tracking[0]}-${suffix()}`,
      model_name: `Receive E2E ${tracking}`,
      tracking_mode: tracking,
      retail_price_thb: "1000.00",
      repair_price_thb: "500.00",
    },
  })
}

async function seedSupplier(): Promise<SupplierPublic> {
  return SuppliersService.createSupplier({
    requestBody: { name: `Receive E2E Supplier ${suffix()}` },
  })
}

// Clean up every staff user this spec seeded, under a fresh superuser token, so
// they don't pollute the shared dev DB for later runs (no product/supplier
// delete endpoint exists, so those are intentionally left as-is). Each deletion
// is isolated so one failure can't fail the suite.
test.afterAll(async () => {
  if (seededStaffUserIds.length === 0) return
  const adminToken = await tokenFor(firstSuperuser, firstSuperuserPassword)
  await withToken(adminToken, async () => {
    for (const userId of seededStaffUserIds) {
      try {
        await UsersService.deleteUser({ userId })
      } catch {
        // Best-effort cleanup; a stale/already-deleted user must not fail the run.
      }
    }
  })
  seededStaffUserIds.length = 0
})

test.describe("Receive screen (admin)", () => {
  // Browser is authed as superuser via auth.setup.ts storageState. Mirror that
  // for the Node-side SDK so seeding + search assertions are authorized too.
  test.beforeAll(async () => {
    OpenAPI.TOKEN = await tokenFor(firstSuperuser, firstSuperuserPassword)
  })

  test("receive a serialized unit lands it IN_STOCK", async ({ page }) => {
    const product = await seedProduct("SERIALIZED")
    const supplier = await seedSupplier()
    const serial = `SER-${suffix()}`

    await page.goto("/receive")

    // Serialized tab is the default; select product + supplier by their labels.
    await page.getByRole("combobox", { name: "Product", exact: true }).click()
    await page
      .getByRole("option", { name: `${product.model_name} (${product.sku})` })
      .click()
    await page.getByRole("combobox", { name: "Supplier", exact: true }).click()
    await page.getByRole("option", { name: supplier.name }).click()

    // Fill one piece (serial + cost), Add, then Receive.
    await page.getByLabel("Supplier serial").fill(serial)
    await page.getByLabel("Purchase cost (THB)").fill("750.00")
    await page.getByRole("button", { name: "Add piece" }).click()

    // The piece appears in the Pieces table before submit.
    await expect(
      page.getByRole("cell", { name: serial, exact: true }),
    ).toBeVisible()

    await page.getByRole("button", { name: "Receive" }).click()

    // Received-units table renders; read the CastraNova barcode from the UI.
    await expect(
      page.getByRole("heading", { name: /Received units/ }),
    ).toBeVisible()
    const barcodeCell = page
      .getByRole("row")
      .filter({ hasText: serial })
      .getByRole("cell")
      .first()
    await expect(barcodeCell).toBeVisible()
    const barcode = (await barcodeCell.textContent())?.trim() ?? ""
    expect(barcode.length).toBeGreaterThan(0)

    // Authoritative backend confirmation: the unit is IN_STOCK.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSerial({ barcode })
          return res.current_state
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe("IN_STOCK")
  })

  test("receive quantity increases stock on hand", async ({ page }) => {
    const product = await seedProduct("QUANTITY")
    const supplier = await seedSupplier()
    const qty = 7

    await page.goto("/receive")
    await page.getByRole("tab", { name: "Quantity" }).click()

    await page.getByRole("combobox", { name: "Product", exact: true }).click()
    await page
      .getByRole("option", { name: `${product.model_name} (${product.sku})` })
      .click()
    await page.getByRole("combobox", { name: "Supplier", exact: true }).click()
    await page.getByRole("option", { name: supplier.name }).click()

    await page.getByLabel("Received qty", { exact: false }).fill(String(qty))
    await page.getByLabel("Purchase cost (THB)").fill("100.00")

    await page.getByRole("button", { name: "Receive" }).click()

    // Success toast confirms the batch landed; then assert on-hand via search.
    await expect(page.getByText(/Received batch/)).toBeVisible()

    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSku({ sku: product.sku })
          return res.total_on_hand
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe(qty)
  })

  test("quantity receive is idempotent on replayed key (API)", async () => {
    // API-level idempotency: replaying the SAME idempotency_key (same body)
    // must NOT double-count. This is the clean online replay assertion.
    const product = await seedProduct("QUANTITY")
    const supplier = await seedSupplier()
    const qty = 5
    const body = {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: qty,
      purchase_cost_thb: "100.00",
      idempotency_key: crypto.randomUUID(),
    }

    await ReceiptsService.receiveQuantity({ requestBody: body })
    await ReceiptsService.receiveQuantity({ requestBody: body })

    // On-hand reflects a single batch of `qty`, not 2 * qty.
    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSku({ sku: product.sku })
          return res.total_on_hand
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe(qty)
  })

  test("staff cannot receive over the receipts API", async () => {
    const { email, password } = await seedStaffUser()
    const staffToken = await tokenFor(email, password)

    const serProduct = await seedProduct("SERIALIZED")
    const qtyProduct = await seedProduct("QUANTITY")
    const supplier = await seedSupplier()

    await withToken(staffToken, async () => {
      // Receiving is admin-only at every layer (restricted 2026-06-17); the
      // backend returns 403 to staff on both receipt endpoints.
      await expect(
        ReceiptsService.receiveSerialized({
          requestBody: {
            product_id: serProduct.id,
            supplier_id: supplier.id,
            idempotency_key: crypto.randomUUID(),
            pieces: [
              {
                supplier_serial: `SN-${suffix()}`,
                purchase_cost_thb: "100.00",
              },
            ],
          },
        }),
      ).rejects.toMatchObject({ status: 403 })

      await expect(
        ReceiptsService.receiveQuantity({
          requestBody: {
            product_id: qtyProduct.id,
            supplier_id: supplier.id,
            received_qty: 5,
            purchase_cost_thb: "10.00",
            idempotency_key: crypto.randomUUID(),
          },
        }),
      ).rejects.toMatchObject({ status: 403 })
    })
  })
})

test.describe("Receive screen access control (staff browser)", () => {
  // Fresh browser context, NOT the superuser storageState — log in as a staff
  // user in the UI so the requireAdmin guard is exercised by a real staff
  // session (receiving is admin-only intake, restricted 2026-06-17 — staff are
  // redirected away from Receive, not allowed in).
  test.use({ storageState: { cookies: [], origins: [] } })

  test("staff are redirected away from /receive", async ({ page }) => {
    const { email, password } = await seedStaffUser()
    await logInUser(page, email, password)
    await page.goto("/receive")
    // requireAdmin() bounces non-admins back to "/".
    await expect.poll(() => new URL(page.url()).pathname).toBe("/")
    await expect(
      page.getByRole("heading", { name: "Receive stock" }),
    ).toBeHidden()
  })
})
