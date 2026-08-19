import { expect, test } from "@playwright/test"

test("editing a project's status updates its row", async ({ page }) => {
  // A customer is required to create a project. The admin customer form lives
  // behind the "New customer" dialog off the page header, not inline on the page.
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByRole("button", { name: "New customer" }).click()
  const createCustomer = page.getByRole("dialog", { name: "New customer" })
  await createCustomer.getByLabel("Name").fill(customer)
  await createCustomer.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  // Create a project against that customer.
  const code = `E2E-${Date.now()}`
  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()
  const createProject = page.getByRole("dialog", { name: "New project" })
  await createProject.getByLabel("Code").fill(code)
  await createProject.getByLabel("Name").fill("E2E Project")
  // Scope the Customer combobox to the dialog — the projects page carries its
  // own filter comboboxes outside it.
  await createProject.getByRole("combobox").click()
  await page.getByRole("option", { name: customer }).click()
  await createProject.getByRole("button", { name: "Create project" }).click()

  // Edit its status to Closed.
  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await dialog.getByLabel("Status").click()
  await page.getByRole("option", { name: "Closed" }).click()
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Project updated.")).toBeVisible()

  // Reload to prove the edit persisted server-side (not just a cache refresh).
  await page.reload()
  await expect(
    page.getByRole("row", { name: new RegExp(code) }).getByText("CLOSED"),
  ).toBeVisible()
})
