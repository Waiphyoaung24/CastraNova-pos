import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ProjectPullsService,
  ProjectsService,
  ReceiptsService,
  SearchService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Returns page finds project pulls (design 2026-09-22): the Sell -> Return
// screen's picker also lists settled project requests, and a pulled-but-unsold
// serialized unit is offered "Return to stock" on the Unit tab. Same harness as
// pull-return.spec.ts / sale-return.spec.ts: Node-side SDK seeding, random
// suffixes for the shared dev DB. Run with `--workers=1`.

OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)
const ON_HAND = 5
const REQUESTED = 3

async function onHand(sku: string): Promise<number> {
  return (await SearchService.searchSku({ sku })).total_on_hand
}

/** A part with ON_HAND in stock and a pull that took REQUESTED of it.
 * Copied from pull-return.spec.ts — module-local there. */
async function seedPull() {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `PRET-${r}`,
      model_name: `Return Part ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "200.00",
      repair_price_thb: "80.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Return Supplier ${r}` },
  })
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Return Customer ${r}` },
  })
  const project = await ProjectsService.createProject({
    requestBody: {
      code: `PRJ-${r}`,
      name: `Return Project ${r}`,
      customer_id: customer.id,
    },
  })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: ON_HAND,
      purchase_cost_thb: "60.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  const pull = await ProjectPullsService.createProjectPull({
    requestBody: {
      project_id: project.id,
      lines: [
        { line_kind: "PART", product_id: product.id, requested_qty: REQUESTED },
      ],
    },
  })
  return { r, product, pull }
}

/** A SERIALIZED unit pulled (not sold) by a project request. */
async function seedPulledUnit() {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `PRET-U-${r}`,
      model_name: `Return Unit ${r}`,
      tracking_mode: "SERIALIZED",
      retail_price_thb: "1500.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Return Unit Supplier ${r}` },
  })
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Return Unit Customer ${r}` },
  })
  const project = await ProjectsService.createProject({
    requestBody: {
      code: `PRJ-U-${r}`,
      name: `Return Unit Project ${r}`,
      customer_id: customer.id,
    },
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
  const pull = await ProjectPullsService.createProjectPull({
    requestBody: {
      project_id: project.id,
      lines: [
        { line_kind: "UNIT", product_id: product.id, unit_serial: barcode },
      ],
    },
  })
  return { barcode, pull }
}

test.describe("Returns page finds project pulls", () => {
  test.beforeAll(async () => {
    const tok = await LoginService.loginAccessToken({
      formData: { username: firstSuperuser, password: firstSuperuserPassword },
    })
    OpenAPI.TOKEN = tok.access_token
  })

  test("Returns page brings back 2 of 3 parts from a project request", async ({
    page,
  }) => {
    const { product, pull } = await seedPull()
    await ProjectPullsService.fulfillProjectPull({
      pullId: pull.id,
      requestBody: { lines: [] }, // omitted lines default to full → FULFILLED
    })
    expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

    await page.goto("/returns")
    await page.getByRole("tab", { name: "Quantity SKU" }).click()
    await page.getByRole("textbox", { name: "Scan barcode" }).fill(product.sku)
    await page.getByRole("combobox").click()
    await page
      .getByRole("option", { name: /Return Project .* 3 of 3 returnable/ })
      .click()
    await page.getByRole("textbox", { name: /quantity returned/i }).fill("2")
    // A pull return has no reason field (the pull endpoint has none).
    await expect(
      page.getByRole("textbox", { name: /reason for the return/i }),
    ).toHaveCount(0)
    await page.getByRole("button", { name: "Record return" }).click()
    await expect(
      page.getByText("Return recorded. The stock is back on hand."),
    ).toBeVisible()
    await expect.poll(() => onHand(product.sku)).toBe(ON_HAND - REQUESTED + 2)
  })

  test("Returns page brings back a pulled unit from the Unit tab", async ({
    page,
  }) => {
    const { barcode, pull } = await seedPulledUnit()
    await ProjectPullsService.fulfillProjectPull({
      pullId: pull.id,
      requestBody: { lines: [] },
    })

    await page.goto("/returns")
    await page.getByRole("tab", { name: "Serialized unit" }).click()
    await page.getByRole("textbox", { name: "Scan barcode" }).fill(barcode)
    await expect(page.getByText(/went out on a project request/)).toBeVisible()
    // A pull return has no reason field.
    await expect(
      page.getByRole("textbox", { name: /reason for the return/i }),
    ).toHaveCount(0)
    await page.getByRole("button", { name: "Return to stock" }).click()
    await expect(
      page.getByText("Return recorded. The stock is back on hand."),
    ).toBeVisible()
    await expect
      .poll(
        async () =>
          (await SearchService.searchSerial({ barcode })).current_state,
      )
      .toBe("IN_STOCK")
  })
})
