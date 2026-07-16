import { expect, test } from "@playwright/test"

// Browser coverage for FR-012's customer filter on /stock (admin-only):
//   1. A freshly created customer has no purchase/service history, so picking
//      them in the filter must empty the stock list (the backend restricts
//      rows to products the customer has ever bought or had serviced).
//   2. Clearing the filter brings the full list back.
// Runs against the shared dev DB authed as the seeded superuser (admin).

/** Random suffix to dodge shared-dev-DB name collisions. */
const rand = () => Math.random().toString(36).slice(2, 10)

test("customer filter narrows stock to the customer's history and clears", async ({
  page,
}) => {
  const name = `Stock Filter Cust ${rand()}`

  // A brand-new customer — guaranteed zero purchase history.
  await page.goto("/customers")
  await page.getByRole("button", { name: "New customer" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible()

  await page.goto("/stock")
  await expect(
    page.getByRole("heading", { name: "Stock on hand", exact: true }),
  ).toBeVisible()

  // Baseline: the seeded dev DB always has stocked products.
  await expect(page.getByText(/^TST-|^[A-Z]+-/).first()).toBeVisible()

  // Pick the fresh customer; the request must carry ?customer= and the list
  // must go empty (they have never bought or had anything serviced).
  const filter = page.getByRole("combobox", { name: "Customer filter" })
  await expect(filter).toBeVisible()
  await filter.click()
  await page.getByPlaceholder("Search customers…").fill(name)
  const withCustomer = page.waitForRequest((r) =>
    r.url().includes("/dashboards/stock-on-hand?customer="),
  )
  await page.getByRole("option", { name }).click()
  await withCustomer
  await expect(page.getByText("No stock matches these filters.")).toBeVisible()

  // Clearing the filter restores the list.
  await filter.click()
  await page.getByRole("option", { name: "All" }).click()
  await expect(page.getByText(/^TST-|^[A-Z]+-/).first()).toBeVisible()
})
