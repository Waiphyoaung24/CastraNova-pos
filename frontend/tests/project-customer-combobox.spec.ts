import { expect, test } from "@playwright/test"

// Regression coverage for a bug where the Customer EntityCombobox inside the
// Projects dialogs couldn't be clicked, scrolled, or searched: a modal Radix
// Dialog's focus trap fights the combobox's portalled popover for focus.
// Every other dialog hosting a combobox (customers, suppliers) already sets
// `modal={false}` to avoid this; the Projects dialogs did not.

test("the customer combobox inside the New project dialog is clickable, searchable, and selectable", async ({
  page,
}) => {
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByRole("button", { name: "New customer" }).click()
  await page.getByLabel("Name").fill(customer)
  await page.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()

  const dialog = page.getByRole("dialog", { name: "New project" })
  const trigger = dialog.getByRole("combobox")

  // Click must actually open the popover (proves the trigger receives the
  // click instead of the dialog's focus trap swallowing it).
  await trigger.click()
  const search = page.getByPlaceholder("Search customers…")
  await expect(search).toBeVisible()

  // Typing must reach the input (proves keyboard focus isn't trapped away).
  await search.fill(customer)
  const option = page.getByRole("option", { name: customer })
  await expect(option).toBeVisible()

  // Selecting must close the popover and set the trigger's label.
  await option.click()
  await expect(search).toBeHidden()
  await expect(trigger).toHaveText(customer)
})
