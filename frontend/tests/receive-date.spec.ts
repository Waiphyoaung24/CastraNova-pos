import { expect, type Locator, type Page, test } from "@playwright/test"

// Browser E2E for the Receive date picker (designs 2026-07-25 receive-date-picker
// and 2026-07-25 date-picker-redesign). The picker exists because holding period
// is computed from received_at, so a delivery keyed in late used to report the
// wrong age. Since the redesign the control is a button + popover grid, never an
// `<input type="date">` — no spec may call `.fill()` on a date field.
// Runs authed as the seeded superuser via storageState (global.setup).

/** Local date as YYYY-MM-DD — must mirror todayISO() in lib/date-field.ts.
 * Deliberately not toISOString(), which is UTC and would flake either side of
 * UTC midnight. */
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

/** Mirrors formatDisplay() in lib/date-field.ts: "2026-07-25" -> "25 Jul 2026". */
function display(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return localISO(d)
}

const today = localISO(new Date())

/** Open the picker and click the given day, paging back a month first when the
 * target is not in the month the picker opens on. */
async function pickDate(page: Page, trigger: Locator, iso: string) {
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Choose date" })
  if (iso.slice(0, 7) !== today.slice(0, 7)) {
    await dialog.getByRole("button", { name: "Previous month" }).click()
  }
  await dialog
    .getByRole("gridcell", { name: display(iso), exact: true })
    .click()
}

test("both Receive tabs default the date to today", async ({ page }) => {
  await page.goto("/receive")

  // Serialized is the default tab; its trigger carries a static id.
  await expect(page.locator("#receive-date")).toHaveText(display(today))

  await page.getByRole("tab", { name: "Quantity" }).click()
  const quantityPanel = page.getByRole("tabpanel")
  await expect(quantityPanel.getByLabel("Receive date")).toHaveText(
    display(today),
  )
})

test("a future date cannot be selected on either tab", async ({ page }) => {
  const tomorrow = localISO(new Date(Date.now() + 24 * 60 * 60 * 1000))

  await page.goto("/receive")

  // The 42-cell grid always renders the day after the last of the month, so
  // tomorrow is present regardless of where in the month today falls.
  await page.locator("#receive-date").click()
  const serializedDialog = page.getByRole("dialog", { name: "Choose date" })
  await expect(
    serializedDialog.getByRole("gridcell", {
      name: display(tomorrow),
      exact: true,
    }),
  ).toBeDisabled()
  await page.keyboard.press("Escape")

  await page.getByRole("tab", { name: "Quantity" }).click()
  await page.getByRole("tabpanel").getByLabel("Receive date").click()
  const quantityDialog = page.getByRole("dialog", { name: "Choose date" })
  await expect(
    quantityDialog.getByRole("gridcell", {
      name: display(tomorrow),
      exact: true,
    }),
  ).toBeDisabled()
})

test("a date can be reached and selected with the keyboard alone", async ({
  page,
}) => {
  await page.goto("/receive")

  const trigger = page.locator("#receive-date")
  await trigger.focus()
  await page.keyboard.press("Enter")

  // The popover opens focused on today. Three left arrows walk back three days.
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  // Right arrow is allowed here — three days back is well inside the range.
  await page.keyboard.press("ArrowRight")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(display(daysAgo(2)))
})

test("arrow keys refuse to move past today", async ({ page }) => {
  await page.goto("/receive")

  const trigger = page.locator("#receive-date")
  await trigger.focus()
  await page.keyboard.press("Enter")
  // Focus starts on today, which is also `max` — every forward move is a no-op.
  await page.keyboard.press("ArrowRight")
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(display(today))
})

test("a backdated Quantity receive mints a batch_no with the backdated prefix", async ({
  page,
}) => {
  const backdated = daysAgo(10)
  const expectedPrefix = backdated.replaceAll("-", "")

  await page.goto("/receive")
  await page.getByRole("tab", { name: "Quantity" }).click()
  const panel = page.getByRole("tabpanel")

  // Pick the first available QUANTITY product and any supplier via the
  // EntityCombobox triggers (options are portalled to the body).
  await panel.getByRole("combobox", { name: "Product" }).click()
  await page.getByRole("option").first().click()
  await panel.getByRole("combobox", { name: "Supplier" }).click()
  await page.getByRole("option").first().click()

  await panel.getByLabel("Received qty").fill("4")
  await panel.getByLabel("Unit cost (THB)").fill("7.50")
  await pickDate(page, panel.getByLabel("Receive date"), backdated)

  await panel.getByRole("button", { name: "Receive", exact: true }).click()

  // The success toast carries the minted batch number; its date prefix must be
  // the BACKDATED day, not today.
  await expect(
    page.getByText(new RegExp(`Received batch ${expectedPrefix}-`)),
  ).toBeVisible()
})
