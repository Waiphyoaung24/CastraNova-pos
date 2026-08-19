import { expect, test } from "@playwright/test"

// Browser E2E coverage for the Products list filters (brand/category/tracking):
//   1. Admin creates two throwaway products with distinct brand + tracking mode.
//   2. Typing a brand narrows the list to the matching product.
//   3. Switching Tracking to the other product's mode shows only that row and
//      hides the first; clearing the filter shows "No products match" is never
//      hit because a compatible filter always still narrows correctly.
//   4. Clearing all filters brings both rows back.
// Runs against the shared dev DB, authed as the seeded superuser via
// storageState — no explicit login needed.

/** Random suffix to dodge shared-dev-DB SKU collisions. */
const rand = () => Math.random().toString(36).slice(2, 8).toUpperCase()

async function createProduct(
  page: import("@playwright/test").Page,
  {
    sku,
    brand,
    trackingMode,
  }: { sku: string; brand: string; trackingMode: "QUANTITY" | "SERIALIZED" },
) {
  await page.getByRole("button", { name: "New product" }).click()
  const dialog = page.getByRole("dialog", { name: /New product/ })
  await dialog.getByLabel("SKU").fill(sku)
  await dialog.getByLabel("Model name").fill("E2E Filter Target")
  await dialog.getByLabel("Brand").fill(brand)
  await dialog.getByLabel("Tracking").click()
  await page.getByRole("option", { name: trackingMode }).click()
  await dialog.getByLabel("Project price (THB)").fill("1000")
  await dialog.getByLabel("Repair price (THB)").fill("200")
  await dialog.getByRole("button", { name: "Create product" }).click()
  await expect(page.getByText("Product created.")).toBeVisible()
}

test("brand and tracking filters narrow the products list", async ({
  page,
}) => {
  await page.goto("/products")

  const tag = rand()
  const skuA = `FLT-A-${tag}`
  const skuB = `FLT-B-${tag}`
  await createProduct(page, {
    sku: skuA,
    brand: `AcmeBrand-${tag}`,
    trackingMode: "SERIALIZED",
  })
  await createProduct(page, {
    sku: skuB,
    brand: `OtherBrand-${tag}`,
    trackingMode: "QUANTITY",
  })

  // Catalog rows are role="button" with aria-label="Edit {model_name}" (not
  // role="row" — that's overridden), and both products share a model name
  // here, so filter by each SKU's visible cell text to tell them apart.
  const rowA = page
    .getByRole("button", { name: "Edit E2E Filter Target" })
    .filter({ hasText: skuA })
  const rowB = page
    .getByRole("button", { name: "Edit E2E Filter Target" })
    .filter({ hasText: skuB })
  await expect(rowA).toBeVisible()
  await expect(rowB).toBeVisible()

  // Brand filter narrows to the matching product only.
  await page.getByLabel("Brand filter").fill(`acmebrand-${tag}`)
  await expect(rowA).toBeVisible()
  await expect(rowB).not.toBeVisible()

  // Clear brand, filter by tracking mode instead.
  await page.getByLabel("Brand filter").fill("")
  await page.getByLabel("Tracking filter").click()
  await page.getByRole("option", { name: "Quantity" }).click()
  await expect(rowB).toBeVisible()
  await expect(rowA).not.toBeVisible()

  // Clear all filters — both rows return.
  await page.getByLabel("Tracking filter").click()
  await page.getByRole("option", { name: "All tracking" }).click()
  await expect(rowA).toBeVisible()
  await expect(rowB).toBeVisible()
})
