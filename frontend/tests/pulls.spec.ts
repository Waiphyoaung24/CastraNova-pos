import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  type ProjectPullPublic,
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

  test("create via dropdown: QUANTITY + SERIALIZED → PENDING pull with PART and UNIT lines", async ({
    page,
  }) => {
    const r = rand()

    const partProduct = await ProductsService.createProduct({
      requestBody: {
        sku: `DPQ-${r}`,
        model_name: `Drop Part ${r}`,
        tracking_mode: "QUANTITY",
        retail_price_thb: "200.00",
        repair_price_thb: "80.00",
      },
    })
    const serialProduct = await ProductsService.createProduct({
      requestBody: {
        sku: `DPS-${r}`,
        model_name: `Drop Serial ${r}`,
        tracking_mode: "SERIALIZED",
        retail_price_thb: "900.00",
        repair_price_thb: "100.00",
      },
    })
    const supplier = await SuppliersService.createSupplier({
      requestBody: { name: `Drop Supplier ${r}` },
    })
    const customer = await CustomersService.createCustomer({
      requestBody: { name: `Drop Customer ${r}` },
    })
    const project = await ProjectsService.createProject({
      requestBody: {
        code: `DPRJ-${r}`,
        name: `Drop Project ${r}`,
        customer_id: customer.id,
      },
    })
    await ReceiptsService.receiveQuantity({
      requestBody: {
        product_id: partProduct.id,
        supplier_id: supplier.id,
        received_qty: 10,
        purchase_cost_thb: "60.00",
        idempotency_key: crypto.randomUUID(),
      },
    })
    const recv = await ReceiptsService.receiveSerialized({
      requestBody: {
        product_id: serialProduct.id,
        supplier_id: supplier.id,
        pieces: [
          { supplier_serial: `SN-${r}-1`, purchase_cost_thb: "500.00" },
          { supplier_serial: `SN-${r}-2`, purchase_cost_thb: "500.00" },
        ],
        idempotency_key: crypto.randomUUID(),
      },
    })
    const barcodes = recv.units.map((u) => u.castranova_barcode)
    expect(barcodes).toHaveLength(2)

    await page.goto("/pulls")
    await page.getByRole("button", { name: "New request" }).click()

    await page.getByRole("combobox", { name: "Project" }).click()
    await page
      .getByRole("option", { name: `Drop Project ${r} (DPRJ-${r})` })
      .click()

    // QUANTITY item, qty 2 → PART line
    await page.getByRole("combobox", { name: "Add item to request" }).click()
    await page
      .getByRole("option", { name: `Drop Part ${r} (DPQ-${r})` })
      .click()
    await page.getByRole("button", { name: "Increase quantity" }).click()
    await page.getByRole("button", { name: "Add", exact: true }).click()
    await expect(page.getByText(`Drop Part ${r}`)).toBeVisible()

    // SERIALIZED item, qty 2 → two UNIT lines (oldest 2 serials auto-claimed)
    await page.getByRole("combobox", { name: "Add item to request" }).click()
    await page
      .getByRole("option", { name: `Drop Serial ${r} (DPS-${r})` })
      .click()
    await page.getByRole("button", { name: "Increase quantity" }).click()
    await page.getByRole("button", { name: "Add", exact: true }).click()
    await expect(page.getByText(barcodes[0])).toBeVisible()
    await expect(page.getByText(barcodes[1])).toBeVisible()

    // Scanner is gone from the create screen.
    await expect(page.getByText("Scan with camera")).toHaveCount(0)

    await page.getByRole("button", { name: "Create request" }).click()
    await expect(page.getByText("Request created.")).toBeVisible()

    // Backend: the seeded project now has a PENDING pull with 1 PART (qty 2)
    // and 2 UNIT lines bound to the two oldest serials.
    let created: ProjectPullPublic | undefined
    await expect
      .poll(
        async () => {
          const list = await ProjectPullsService.readProjectPulls({
            state: "PENDING",
          })
          created = list.find((p) => p.project_id === project.id)
          return created ? created.lines.length : 0
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBeGreaterThan(0)

    expect(created).toBeTruthy()
    const partLines = created!.lines.filter((l) => l.line_kind === "PART")
    const unitLines = created!.lines.filter((l) => l.line_kind === "UNIT")
    expect(partLines).toHaveLength(1)
    expect(partLines[0].requested_qty).toBe(2)
    expect(unitLines).toHaveLength(2)
    expect(unitLines.map((l) => l.unit_serial).sort()).toEqual(
      [...barcodes].sort(),
    )
  })
})
