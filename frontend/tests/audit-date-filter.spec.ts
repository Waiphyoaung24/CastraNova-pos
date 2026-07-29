import { expect, test } from "@playwright/test"

// The audit ledger's From/To filters are the app's only OPTIONAL date fields,
// so they are where the Clear affordance gets proven. Runs authed as the seeded
// superuser via storageState (global.setup).

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

test("From and To are set from the grid and cleared again", async ({ page }) => {
  await page.goto("/audit")

  // The trigger names itself "<label> <value>", e.g. "To Any date". Anchor on
  // the label: a bare "To" substring-matches half the dev-tools chrome.
  const from = page.getByRole("button", { name: /^From\b/ })
  const to = page.getByRole("button", { name: /^To\b/ })
  const picker = page.getByRole("dialog", { name: "Choose date" })

  // Unset fields show the placeholder, not a date.
  await expect(from).toHaveText("Any date")

  // Today's cell is reachable in both pickers without paging.
  await from.click()
  await picker
    .getByRole("gridcell", { name: display(today), exact: true })
    .click()
  await expect(from).toHaveText(display(today))
  // Radix keeps the closing popover mounted through its exit animation, so the
  // next picker must not open until this one has actually gone.
  await expect(picker).toHaveCount(0)

  await to.click()
  await picker.getByRole("button", { name: "Today" }).click()
  await expect(to).toHaveText(display(today))
  await expect(picker).toHaveCount(0)

  // The ledger keeps rendering under the filter rather than erroring out.
  await expect(
    page.getByRole("heading", { name: "Audit ledger" }),
  ).toBeVisible()

  // Clear is offered because these fields are optional.
  await from.click()
  await picker.getByRole("button", { name: "Clear" }).click()
  await expect(from).toHaveText("Any date")
})

test("Escape closes the picker and returns focus to the trigger", async ({
  page,
}) => {
  await page.goto("/audit")

  const from = page.getByRole("button", { name: /^From\b/ })
  await from.click()
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeHidden()
  await expect(from).toBeFocused()
})
