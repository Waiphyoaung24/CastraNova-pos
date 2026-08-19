import { expect, type Page, test } from "@playwright/test"

// A Radix Popover nested inside a Radix Dialog is the classic place focus return
// and stacking break, and the project edit dialog is the only screen where the
// date picker sits inside one. Runs authed as the seeded superuser.

function localISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
]

function display(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

const today = localISO(new Date())

/** Always inside the visible grid: the 42 cells start on or before the 1st, so
 * the leading days cover yesterday even on the first of the month. */
function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return localISO(d)
}

/** Create a customer and a project, then open that project's edit dialog.
 * Mirrors tests/project-edit-flow.spec.ts — the seeded database is not
 * guaranteed to contain a project, so each test makes its own. */
async function openEditDialog(page: Page) {
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  // The create form lives behind a dialog, not inline on the page.
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
  await newProject.getByLabel("Name").fill("E2E Project")
  await newProject.getByRole("combobox").click()
  // Combobox options portal to the body, outside the dialog.
  await page.getByRole("option", { name: customer }).click()
  await newProject.getByRole("button", { name: "Create project" }).click()

  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await expect(dialog).toBeVisible()
  return dialog
}

test("the create dialog picks dates and flags an out-of-order range", async ({
  page,
}) => {
  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()
  const dialog = page.getByRole("dialog", { name: "New project" })
  await expect(dialog).toBeVisible()

  const start = dialog.getByRole("button", { name: /^Start date\b/ })
  await start.click()
  const picker = page.getByRole("dialog", { name: "Choose date" })
  await picker
    .getByRole("gridcell", { name: display(today), exact: true })
    .click()
  await expect(picker).toHaveCount(0)
  await expect(start).toHaveText(display(today))
  // The half-filled form survives selecting a date.
  await expect(dialog).toBeVisible()

  // An end date before the start is rejected, and marks the trigger invalid.
  const end = dialog.getByRole("button", { name: /^End date\b/ })
  await end.click()
  await page
    .getByRole("dialog", { name: "Choose date" })
    .getByRole("gridcell", { name: display(daysAgo(1)), exact: true })
    .click()
  await expect(
    dialog.getByText("End date must be on or after the start date."),
  ).toBeVisible()
  await expect(end).toHaveAttribute("aria-invalid", "true")
})

test("the date picker opens, selects and returns focus inside the dialog", async ({
  page,
}) => {
  const dialog = await openEditDialog(page)

  const start = dialog.getByRole("button", { name: /^Start date\b/ })
  await start.click()

  // The popover stacks above the dialog rather than behind it.
  const picker = page.getByRole("dialog", { name: "Choose date" })
  await expect(picker).toBeVisible()

  await picker
    .getByRole("gridcell", { name: display(today), exact: true })
    .click()
  await expect(picker).toHaveCount(0)
  await expect(start).toHaveText(display(today))

  // Focus came back to the trigger, and the parent dialog is still open —
  // selecting a date must not dismiss the form underneath it.
  await expect(start).toBeFocused()
  await expect(dialog).toBeVisible()
})

test("Escape closes only the picker, not the dialog underneath it", async ({
  page,
}) => {
  const dialog = await openEditDialog(page)
  const end = dialog.getByRole("button", { name: /^End date\b/ })

  await end.click()
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog", { name: "Choose date" })).toHaveCount(0)
  await expect(dialog).toBeVisible()
  await expect(end).toBeFocused()
})
