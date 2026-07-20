import { expect, test } from "@playwright/test"

import {
  LoginService,
  OpenAPI,
  ProductsService,
  ReceiptsService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

OpenAPI.BASE = `${process.env.VITE_API_URL}`
const rand = () => Math.random().toString(36).slice(2, 10).toUpperCase()

async function authSeedClient() {
  const token = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = token.access_token
}

test.describe("Stock on hand — server filters and pagination", () => {
  test.beforeAll(authSeedClient)

  test("supplier filter narrows rows and labels the scoped quantity", async ({
    page,
  }) => {
    const tag = rand()
    const supplierA = await SuppliersService.createSupplier({
      requestBody: { name: `Stock Supplier A ${tag}` },
    })
    const supplierB = await SuppliersService.createSupplier({
      requestBody: { name: `Stock Supplier B ${tag}` },
    })
    const productA = await ProductsService.createProduct({
      requestBody: {
        sku: `SOH-A-${tag}`,
        model_name: `Supplier A model ${tag}`,
        tracking_mode: "QUANTITY",
        retail_price_thb: "100.00",
        repair_price_thb: "20.00",
      },
    })
    const productB = await ProductsService.createProduct({
      requestBody: {
        sku: `SOH-B-${tag}`,
        model_name: `Supplier B model ${tag}`,
        tracking_mode: "QUANTITY",
        retail_price_thb: "100.00",
        repair_price_thb: "20.00",
      },
    })
    for (const [product, supplier] of [
      [productA, supplierA],
      [productB, supplierB],
    ] as const) {
      await ReceiptsService.receiveQuantity({
        requestBody: {
          product_id: product.id,
          supplier_id: supplier.id,
          received_qty: 3,
          purchase_cost_thb: "50.00",
          idempotency_key: crypto.randomUUID(),
        },
      })
    }

    await page.goto("/stock")
    const filter = page.getByRole("combobox", { name: "Supplier filter" })
    await filter.click()
    await page.getByPlaceholder("Search suppliers…").fill(supplierA.name)
    const filtered = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        url.pathname.endsWith("/dashboards/stock-on-hand") &&
        url.searchParams.get("supplier") === supplierA.id
      )
    })
    await page.getByRole("option", { name: supplierA.name }).click()
    await filtered

    await expect(page.getByText(productA.sku, { exact: true })).toBeVisible()
    await expect(page.getByText(productB.sku, { exact: true })).toHaveCount(0)
    await expect(
      page.getByRole("columnheader", {
        name: `In stock (${supplierA.name})`,
        exact: true,
      }),
    ).toBeVisible()
  })

  test("search results paginate at 25 rows", async ({ page }) => {
    const tag = rand()
    const skus: string[] = []
    for (let index = 0; index < 26; index += 1) {
      const sku = `PAGE-${tag}-${String(index).padStart(2, "0")}`
      skus.push(sku)
      await ProductsService.createProduct({
        requestBody: {
          sku,
          model_name: `Pagination model ${tag}`,
          tracking_mode: "QUANTITY",
          retail_price_thb: "100.00",
          repair_price_thb: "20.00",
        },
      })
    }

    await page.goto("/stock")
    const search = page.getByPlaceholder("Search by name or barcode…")
    const firstPage = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        url.pathname.endsWith("/dashboards/stock-on-hand") &&
        url.searchParams.get("q") === tag &&
        url.searchParams.get("skip") === "0"
      )
    })
    await search.fill(tag)
    await firstPage

    await expect(page.getByText(skus[0], { exact: true })).toBeVisible()
    await expect(page.getByText(skus[25], { exact: true })).toHaveCount(0)
    await expect(page.getByText("Page 1 of 2", { exact: true })).toBeVisible()

    const secondPage = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return (
        url.pathname.endsWith("/dashboards/stock-on-hand") &&
        url.searchParams.get("q") === tag &&
        url.searchParams.get("skip") === "25"
      )
    })
    await page.getByLabel("Go to next page").click()
    await secondPage

    await expect(page.getByText(skus[0], { exact: true })).toHaveCount(0)
    await expect(page.getByText(skus[25], { exact: true })).toBeVisible()
    await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible()
  })
})
