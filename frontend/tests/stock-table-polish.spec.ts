import { expect, test } from "@playwright/test"

const admin = {
  email: "admin@example.test",
  is_active: true,
  is_superuser: true,
  role: "BKK_ADMIN",
  full_name: "Admin",
  id: "00000000-0000-4000-8000-000000000001",
}
const supplier = {
  id: "00000000-0000-4000-8000-000000000002",
  name: "TEST Comp",
}
const stock = {
  rows: [
    {
      product_id: "00000000-0000-4000-8000-000000000003",
      sku: "SKU-001",
      model_name: "Product",
      brand: "Brand",
      category: "Category",
      tracking_mode: "QUANTITY",
      quantity_on_hand: 1,
    },
  ],
  count: 1,
}

test.use({ storageState: { cookies: [], origins: [] } })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "e30.eyJleHAiOjk5OTk5OTk5OTl9.e30")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({ status: 200, json: admin }),
  )
  await page.route("**/api/v1/suppliers/options", (route) =>
    route.fulfill({ status: 200, json: [supplier] }),
  )
  await page.route("**/api/v1/dashboards/stock-on-hand*", (route) =>
    route.fulfill({ status: 200, json: stock }),
  )
})

test("the expander button fits without clipped overflow", async ({ page }) => {
  await page.goto("/stock")
  const cell = page
    .getByRole("button", { name: "Expand SKU-001" })
    .locator("..")
  expect(
    await cell.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true)
})

test("desktop columns follow the requested order", async ({ page }) => {
  await page.goto("/stock")
  await expect(
    page.getByRole("button", { name: "Expand SKU-001" }),
  ).toBeVisible()
  const labels = await page.getByRole("columnheader").allTextContents()
  expect(labels.map((label) => label.trim())).toEqual([
    "",
    "SKU",
    "Brand",
    "Model",
    "Category",
    "In stock",
    "",
  ])
})

test("supplier scope is shown above a short quantity header", async ({
  page,
}) => {
  await page.goto("/stock")
  await page.getByRole("combobox", { name: "Supplier filter" }).click()
  await page.getByText("TEST Comp", { exact: true }).click()

  await expect(page.getByText("Showing stock from: TEST Comp")).toBeVisible()
  await expect(
    page.getByRole("columnheader", { name: "In stock", exact: true }),
  ).toBeVisible()
})
