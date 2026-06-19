import { expect, test } from "@playwright/test"

test("editing a project's status updates its row", async ({ page }) => {
  // A customer is required to create a project.
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByLabel("Name").first().fill(customer)
  await page.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  // Create a project against that customer.
  const code = `E2E-${Date.now()}`
  await page.goto("/projects")
  await page.getByLabel("Code").fill(code)
  await page.getByLabel("Name").fill("E2E Project")
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: customer }).click()
  await page.getByRole("button", { name: "Create project" }).click()

  // Edit its status to Closed.
  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await dialog.getByLabel("Status").click()
  await page.getByRole("option", { name: "Closed" }).click()
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Project updated.")).toBeVisible()
  await expect(
    page.getByRole("row", { name: new RegExp(code) }).getByText("CLOSED"),
  ).toBeVisible()
})
