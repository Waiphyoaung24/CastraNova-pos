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

// Browser E2E for pull returns (design 2026-09-21). Same harness as
// pulls.spec.ts: Node-side SDK seeding, random suffixes for the shared dev
// DB. Run with `--workers=1`.

OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)
const ON_HAND = 5
const REQUESTED = 3

async function onHand(sku: string): Promise<number> {
  return (await SearchService.searchSku({ sku })).total_on_hand
}

/** A part with ON_HAND in stock and a pull that took REQUESTED of it. */
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

test.describe("Pull returns", () => {
  test.beforeAll(async () => {
    const tok = await LoginService.loginAccessToken({
      formData: { username: firstSuperuser, password: firstSuperuserPassword },
    })
    OpenAPI.TOKEN = tok.access_token
  })

  test("return 2 of 3 from a handed-out pull puts them back on hand", async ({
    page,
  }) => {
    const { r, product, pull } = await seedPull()
    await ProjectPullsService.fulfillProjectPull({
      pullId: pull.id,
      requestBody: { lines: [] }, // omitted lines default to full → FULFILLED
    })
    expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

    await page.goto("/pulls")
    // The queue defaults to waiting requests; a done one is under History.
    await page.getByRole("tab", { name: "History" }).click()
    // History rolls requests up per project; open the project, then the request.
    const project = page
      .locator("details")
      .filter({ hasText: `Return Project ${r}` })
    await expect(project.locator("summary")).toContainText("1 request")
    await project.locator("summary").click()
    await project.getByRole("button", { name: "Open" }).click()

    await page.getByRole("button", { name: "Return items to stock" }).click()
    const dialog = page.getByRole("dialog")
    const more = dialog.getByRole("button", { name: /Return more/ })
    await more.click()
    await more.click()
    await dialog.getByRole("button", { name: "Return 2 items" }).click()
    await expect(page.getByText("Items returned to stock.")).toBeVisible()

    await expect.poll(() => onHand(product.sku)).toBe(ON_HAND - REQUESTED + 2)
  })

  test("cancel a waiting pull puts its stock back", async ({ page }) => {
    const { r, product } = await seedPull()
    expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

    await page.goto("/pulls")
    await page
      .getByRole("row")
      .filter({ hasText: `Return Project ${r}` })
      .getByRole("button", { name: "Cancel" })
      .click()
    await expect(
      page.getByText("Request cancelled — stock put back."),
    ).toBeVisible()
    await expect.poll(() => onHand(product.sku)).toBe(ON_HAND)
  })
})
