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

// Browser E2E for the Pulls screen (Task 5.2 path: "pull fulfill (with
// short)"). Same harness pattern as sale.spec.ts: Node-side SDK seeding,
// random suffixes for the shared dev DB, web-first / expect.poll assertions.
// Run with `--workers=1`.

OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

/** Authenticate the Node-side SDK client as the superuser for seeding. */
async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

test.describe("Pulls screen", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  test("pull fulfill with short: 2 of 3 fulfilled → pull settles SHORT, stock decremented", async ({
    page,
  }) => {
    const r = rand()
    const onHand = 5
    const requested = 3
    const fulfilled = 2

    // Seed the full chain: part with stock, customer, project, PENDING pull
    // requesting 3 of the part.
    const product = await ProductsService.createProduct({
      requestBody: {
        sku: `PULL-${r}`,
        model_name: `Pull Part ${r}`,
        tracking_mode: "QUANTITY",
        retail_price_thb: "200.00",
        repair_price_thb: "80.00",
      },
    })
    const supplier = await SuppliersService.createSupplier({
      requestBody: { name: `Pull Supplier ${r}` },
    })
    const customer = await CustomersService.createCustomer({
      requestBody: { name: `Pull Customer ${r}` },
    })
    const project = await ProjectsService.createProject({
      requestBody: {
        code: `PRJ-${r}`,
        name: `Pull Project ${r}`,
        customer_id: customer.id,
      },
    })
    await ReceiptsService.receiveQuantity({
      requestBody: {
        product_id: product.id,
        supplier_id: supplier.id,
        received_qty: onHand,
        purchase_cost_thb: "60.00",
        idempotency_key: crypto.randomUUID(),
      },
    })
    const pull = await ProjectPullsService.createProjectPull({
      requestBody: {
        project_id: project.id,
        lines: [
          {
            line_kind: "PART",
            product_id: product.id,
            requested_qty: requested,
          },
        ],
      },
    })
    expect(pull.state).toBe("PENDING")

    await page.goto("/pulls")
    await expect(
      page.getByRole("heading", { name: "Stock requests" }),
    ).toBeVisible()

    // The queue defaults to the PENDING filter; open our seeded pull's row
    // (the row text resolves to "Name (CODE)" once the projects query lands).
    await page
      .getByRole("row")
      .filter({ hasText: `Pull Project ${r}` })
      .getByRole("button", { name: "Give out parts" })
      .click()

    // Fulfill 2 of the 3 requested via the line's +/- stepper.
    const increase = page.getByRole("button", {
      name: `Increase Pull Part ${r}`,
    })
    await increase.click()
    await increase.click()
    await expect(page.getByText(`${fulfilled} / ${requested}`)).toBeVisible()

    // A line below its requested qty projects the pull to settle as SHORT.
    await expect(page.getByText("Some items short")).toBeVisible()

    await page.getByRole("button", { name: "Done — give out parts" }).click()

    // The success toast echoes the settled state returned by the backend.
    await expect(
      page.getByText("Parts given out — some items still short."),
    ).toBeVisible()

    // Authoritative backend assertions: the pull settled SHORT with the
    // partial quantity recorded, and stock dropped by exactly what was pulled.
    await expect
      .poll(
        async () => {
          const res = await ProjectPullsService.readProjectPull({
            pullId: pull.id,
          })
          return res.state
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe("SHORT")
    const settled = await ProjectPullsService.readProjectPull({
      pullId: pull.id,
    })
    expect(settled.lines).toHaveLength(1)
    expect(settled.lines[0].fulfilled_qty).toBe(fulfilled)
    expect(settled.lines[0].line_state).toBe("SHORT")

    await expect
      .poll(
        async () => {
          const res = await SearchService.searchSku({ sku: product.sku })
          return res.total_on_hand
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe(onHand - fulfilled)
  })
})
