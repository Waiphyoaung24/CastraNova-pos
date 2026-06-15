import { expect, test } from "@playwright/test"

// Browser coverage for the customer-creation UX added for FR-007 + D25:
//   1. Inline "+ New customer" during a Sale auto-selects the new customer.
//   2. The admin Customers screen creates a customer that shows in the list.
// Both run against the shared dev DB (reset by global.setup) authed as the
// seeded superuser (storageState), who is an admin.

/** Random suffix to dodge shared-dev-DB name collisions. */
const rand = () => Math.random().toString(36).slice(2, 10)

test("inline + New customer during a sale auto-selects the new customer", async ({
  page,
}) => {
  const name = `Inline Cust ${rand()}`

  await page.goto("/sale")
  await expect(
    page.getByRole("heading", { name: "Sale", exact: true }),
  ).toBeVisible()

  // Desktop checkout pane is first in the DOM (mobile footer is md:hidden).
  await page.getByRole("button", { name: "New customer" }).first().click()

  // Dialog opens; only Name is required.
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create customer" }).click()

  // The freshly created customer becomes the selected option.
  await expect(
    page.getByRole("combobox", { name: "Customer" }).first(),
  ).toHaveText(name)
})

test("admin Customers screen creates a customer that appears in the list", async ({
  page,
}) => {
  const name = `Admin Cust ${rand()}`

  await page.goto("/customers")
  await expect(
    page.getByRole("heading", { name: "Customers", exact: true }),
  ).toBeVisible()

  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create customer" }).click()

  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible()
})
