import { expect, test } from "@playwright/test"

// Regression coverage: opening a project form dialog must not drop focus (and
// a text cursor) into the first field. That happened because Radix Dialog
// auto-focuses the first tabbable element on open. Mirrors
// tests/product-dialog-focus.spec.ts, which covers the same fix on the
// product dialogs.

test("opening the New project dialog does not autofocus a field", async ({
  page,
}) => {
  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()
  const dialog = page.getByRole("dialog", { name: "New project" })
  await expect(dialog).toBeVisible()
  // Positive half: focus must land on the dialog container itself, not
  // merely "not the Name field".
  await expect(dialog).toBeFocused()
  await expect(dialog.getByLabel("Name")).not.toBeFocused()
})

test("opening the Edit project dialog does not autofocus a field", async ({
  page,
}) => {
  // The seeded database is not guaranteed to contain a project, so make one —
  // same setup as tests/project-date-dialog.spec.ts.
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByRole("button", { name: "New customer" }).click()
  const newCustomer = page.getByRole("dialog", { name: "New customer" })
  await newCustomer.getByLabel("Name").fill(customer)
  await newCustomer.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  const code = `E2E-${Date.now()}`
  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()
  // Scope to the dialog: the Projects page carries its own filter controls,
  // and unscoped label lookups match those instead.
  const newProject = page.getByRole("dialog", { name: "New project" })
  await newProject.getByLabel("Code").fill(code)
  await newProject.getByLabel("Name").fill("E2E Focus Project")
  await newProject.getByRole("combobox").click()
  // Combobox options portal to the body, outside the dialog.
  await page.getByRole("option", { name: customer }).click()
  await newProject.getByRole("button", { name: "Create project" }).click()

  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await expect(dialog).toBeVisible()
  await expect(dialog).toBeFocused()
  await expect(dialog.getByLabel("Name")).not.toBeFocused()
})
