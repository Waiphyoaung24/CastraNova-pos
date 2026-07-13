import { expect, test } from "@playwright/test"

test("editing a supplier updates its row", async ({ page }) => {
  await page.goto("/suppliers")

  const name = `E2E-Sup-${Date.now()}`
  await page.getByRole("button", { name: "New supplier" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create supplier" }).click()

  const row = page.getByRole("row", { name: new RegExp(name) })
  await row.getByRole("button", { name: "Edit" }).click()

  const dialog = page.getByRole("dialog", { name: /Edit supplier/ })
  await dialog.getByLabel("Contact").fill("e2e@example.com")
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Supplier updated.")).toBeVisible()

  // Reload to prove the edit persisted server-side (not just a cache refresh).
  await page.reload()
  await expect(
    page
      .getByRole("row", { name: new RegExp(name) })
      .getByText("e2e@example.com"),
  ).toBeVisible()
})

test("picking a country in the register form saves and displays it", async ({
  page,
}) => {
  await page.goto("/suppliers")

  const name = `E2E-Sup-Country-${Date.now()}`
  await page.getByRole("button", { name: "New supplier" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("combobox", { name: "Country", exact: true }).click()
  await page.getByPlaceholder("Search country…").fill("Thailand")
  await page.getByRole("option", { name: "Thailand", exact: true }).click()
  await page.getByRole("button", { name: "Create supplier" }).click()

  const row = page.getByRole("row", { name: new RegExp(name) })
  await expect(row.getByRole("cell", { name: "Thailand" })).toBeVisible()
})

test("country filter narrows the list to matching suppliers", async ({
  page,
}) => {
  await page.goto("/suppliers")

  const name = `E2E-Sup-Filter-${Date.now()}`
  await page.getByRole("button", { name: "New supplier" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("combobox", { name: "Country", exact: true }).click()
  await page.getByPlaceholder("Search country…").fill("Japan")
  await page.getByRole("option", { name: "Japan", exact: true }).click()
  await page.getByRole("button", { name: "Create supplier" }).click()
  await expect(page.getByText("Supplier created.")).toBeVisible()

  // The filter's option list is refetched (["supplier-countries"] invalidated
  // on create) but that refetch races the toast; give it a moment to land.
  await expect(page.getByRole("row", { name: new RegExp(name) })).toBeVisible()

  await page
    .getByRole("combobox", { name: "Country filter", exact: true })
    .click()
  await page.getByPlaceholder("Search country…").fill("Japan")
  await page.getByRole("option", { name: "Japan", exact: true }).click()

  await expect(page.getByRole("row", { name: new RegExp(name) })).toBeVisible()

  await page
    .getByRole("combobox", { name: "Country filter", exact: true })
    .click()
  await page.getByRole("option", { name: "All", exact: true }).click()
})
