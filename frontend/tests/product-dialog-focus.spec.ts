import { expect, test } from "@playwright/test"

// Regression coverage: opening a product form dialog must not drop focus (and
// a text cursor) into the Model name field. That happened because Radix
// Dialog auto-focuses the first tabbable element on open, and in the Edit
// dialog the fields before Model name (SKU, Tracking) are disabled.

/** Random suffix to dodge shared-dev-DB SKU collisions. */
const rand = () => Math.random().toString(36).slice(2, 8).toUpperCase()

test("opening the New product dialog does not autofocus Model name", async ({
  page,
}) => {
  await page.goto("/products")
  await page.getByRole("button", { name: "New product" }).click()
  const dialog = page.getByRole("dialog", { name: "New product" })
  await expect(dialog).toBeVisible()
  // Positive half: focus must land on the dialog container itself, not
  // merely "not the Model name field".
  await expect(dialog).toBeFocused()
  await expect(dialog.getByLabel("Model name")).not.toBeFocused()
})

test("opening the Edit product dialog does not autofocus Model name", async ({
  page,
}) => {
  await page.goto("/products")

  const sku = `E2E-FOCUS-${rand()}`
  await page.getByRole("button", { name: "New product" }).click()
  const create = page.getByRole("dialog", { name: "New product" })
  await create.getByLabel("SKU").fill(sku)
  await create.getByLabel("Model name").fill("E2E Focus Target")
  await create.getByLabel("Project price (THB)").fill("1000")
  await create.getByLabel("Repair price (THB)").fill("200")
  await create.getByRole("button", { name: "Create product" }).click()

  // Each catalog row's accessible role/name comes from its own aria-label
  // ("Edit {model_name}"), which doesn't include the SKU — filter by the
  // SKU's visible cell text instead to pick out this run's row.
  const row = page
    .getByRole("button", { name: "Edit E2E Focus Target" })
    .filter({ hasText: sku })
  await expect(row).toBeVisible()

  await row.click()
  const dialog = page.getByRole("dialog", { name: /Edit product/ })
  await expect(dialog).toBeVisible()
  // Positive half: focus must land on the dialog container itself, not
  // merely "not the Model name field".
  await expect(dialog).toBeFocused()
  await expect(dialog.getByLabel("Model name")).not.toBeFocused()
})
