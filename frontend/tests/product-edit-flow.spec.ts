import { expect, test } from "@playwright/test"

// Browser E2E coverage for the product Edit + Price History UX:
//   1. Admin creates a throwaway product via the create form.
//   2. Opens the Edit dialog for that product and changes the retail price.
//   3. Asserts the "Product updated" toast appears.
//   4. Opens the History dialog and confirms a retail_price_thb change row
//      is listed, showing the new price value.
// Runs against the shared dev DB (reset by global.setup), authed as the
// seeded superuser via storageState — no explicit login needed.

/** Random suffix to dodge shared-dev-DB SKU collisions. */
const rand = () => Math.random().toString(36).slice(2, 8).toUpperCase()

test("editing a product's retail price records it in price history", async ({
  page,
}) => {
  await page.goto("/products")

  // Create a throwaway product via the create form, behind the "New product"
  // dialog (ProductCreateDialog).
  const sku = `E2E-${rand()}`
  await page.getByRole("button", { name: "New product" }).click()
  const create = page.getByRole("dialog", { name: "New product" })
  await create.getByLabel("SKU").fill(sku)
  await create.getByLabel("Model name").fill("E2E Edit Target")
  await create.getByLabel("Retail price (THB)").fill("1000")
  await create.getByLabel("Repair price (THB)").fill("200")
  await create.getByRole("button", { name: "Create product" }).click()

  // Wait for the new row to appear in the catalog table. Catalog rows are
  // role="button" with aria-label="Edit {model_name}" (not role="row" —
  // that's overridden), and the label doesn't include the SKU, so filter by
  // the SKU's visible cell text to pick out this run's row.
  const row = page
    .getByRole("button", { name: "Edit E2E Edit Target" })
    .filter({ hasText: sku })
  await expect(row).toBeVisible()

  // Open that product's Edit dialog and change the retail price.
  await row.click()
  const dialog = page.getByRole("dialog", { name: /Edit product/ })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Retail price (THB)").fill("1500")
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()

  // Open History → it must now list the retail_price_thb change.
  await row.getByRole("button", { name: "History" }).click()
  const history = page.getByRole("dialog", { name: /Price history/ })
  await expect(history).toBeVisible()
  await expect(history.getByText("retail_price_thb")).toBeVisible()
  await expect(history.getByText("1500", { exact: false })).toBeVisible()
})
