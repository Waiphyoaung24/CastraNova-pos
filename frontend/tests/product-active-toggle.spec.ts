import { expect, test } from "@playwright/test"

// Browser E2E for retiring a product from the catalog (admin-only):
//   1. Create a throwaway SERIALIZED product — it starts Active.
//   2. Positive control: the active-only serialized picker on Receive must
//      offer it while still active, so the later absence assertion proves
//      something.
//   3. Retire it via the Edit dialog's Active checkbox.
//   4. The catalog Status column must read Inactive.
//   5. It must vanish from Receive's serialized picker, which fetches
//      { activeOnly: true } — proving the flag reaches the real picker and
//      not just the form.
//   6. Reactivating brings it back (the flag is not one-way).
// Runs against the shared dev DB (reset by global.setup), authed as the
// seeded superuser via storageState — no explicit login needed.

/** Random suffix to dodge shared-dev-DB SKU collisions. */
const rand = () => Math.random().toString(36).slice(2, 8).toUpperCase()

test("an admin can retire a product and bring it back", async ({ page }) => {
  await page.goto("/products")

  // Create a throwaway SERIALIZED product. The create form lives behind the
  // "New product" dialog (ProductCreateDialog), so it must be opened first.
  const sku = `E2E-ACT-${rand()}`
  await page.getByRole("button", { name: "New product" }).click()
  const create = page.getByRole("dialog", { name: "New product" })
  await expect(create).toBeVisible()
  await create.getByLabel("SKU").fill(sku)
  await create.getByLabel("Model name").fill("E2E Retire Target")
  // Radix Select: the trigger carries the "Tracking" label; options are
  // portalled to the body, so query them off `page`, not the dialog. The
  // option text is the raw enum ("SERIALIZED"), not a prettified label.
  await create.getByLabel("Tracking").click()
  await page.getByRole("option", { name: "SERIALIZED" }).click()
  await create.getByLabel("Project price (THB)").fill("1000")
  await create.getByLabel("Repair price (THB)").fill("200")
  await create.getByRole("button", { name: "Create product" }).click()

  // Catalog rows are role="button" with aria-label="Edit {model_name}" (not
  // role="row" — that's overridden), and the label doesn't include the SKU,
  // so filter by the SKU's visible cell text to pick out this run's row.
  const row = page
    .getByRole("button", { name: "Edit E2E Retire Target" })
    .filter({ hasText: sku })
  await expect(row).toBeVisible()
  // A new product starts active.
  await expect(row.getByText("Active", { exact: true })).toBeVisible()

  // Positive control: prove the active-only serialized picker on Receive
  // actually offers this product *before* it's retired, using the exact
  // same combobox/search/option selectors as the post-retire absence
  // assertion below. Without this baseline, that later toHaveCount(0) would
  // also pass for the wrong reason — a broken search box, a selector that
  // silently matches nothing, or the product never populating the picker's
  // list in the first place. Do not delete this as "redundant" with the
  // absence check — it's what makes the absence check meaningful.
  await page.goto("/receive")
  await page.getByRole("combobox", { name: "Product" }).click()
  await page.getByPlaceholder("Search products…").fill(sku)
  const pickerOption = page.getByRole("option", { name: new RegExp(sku) })
  await expect(pickerOption).toHaveCount(1)
  await expect(pickerOption).toBeVisible()
  await page.keyboard.press("Escape")

  // Retire it via the Edit dialog.
  await page.goto("/products")
  await row.click()
  const dialog = page.getByRole("dialog", { name: /Edit product/ })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Active").uncheck()
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()

  // The catalog now reports it as retired.
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible()

  // ...and the active-only serialized picker must no longer offer it.
  // The picker is an EntityCombobox with ariaLabel="Product"; its search box
  // placeholder uses a real ellipsis character, not three dots.
  await page.goto("/receive")
  await page.getByRole("combobox", { name: "Product" }).click()
  await page.getByPlaceholder("Search products…").fill(sku)
  await expect(page.getByRole("option", { name: new RegExp(sku) })).toHaveCount(
    0,
  )
  await page.keyboard.press("Escape")

  // Reactivating restores it — retiring is reversible.
  await page.goto("/products")
  await row.click()
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Active").check()
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()
  await expect(row.getByText("Active", { exact: true })).toBeVisible()
})
