import { expect, test } from "@playwright/test"

// The two monthly report screens share the MonthPicker, which is the same
// MonthGrid the DatePicker caption drops to. Runs authed as the seeded
// superuser via storageState (global.setup).
//
// Triggers are located by role with an anchored name, never getByLabel: in dev
// mode the TanStack Router devtools put route paths in aria-labels, and short
// words substring-match half of them.

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

const now = new Date()
const thisMonth = `${MONTHS[now.getMonth()]} ${now.getFullYear()}`
const lastYearSameMonth = `${MONTHS[now.getMonth()]} ${now.getFullYear() - 1}`

test("channel margin defaults to this month and picks another one", async ({
  page,
}) => {
  await page.goto("/channel-margin")

  const trigger = page.getByRole("button", { name: /^Month\b/ })
  await expect(trigger).toHaveText(thisMonth)

  // Step back a year, then pick the same month in it.
  await trigger.click()
  const picker = page.getByRole("dialog", { name: "Choose month" })
  await picker.getByRole("button", { name: "Previous year" }).click()
  await picker
    .getByRole("gridcell", { name: lastYearSameMonth, exact: true })
    .click()

  await expect(picker).toHaveCount(0)
  await expect(trigger).toHaveText(lastYearSameMonth)
  // The report re-queries rather than erroring on the new month.
  await expect(
    page.getByRole("heading", { name: "Channel margin" }),
  ).toBeVisible()
})

test("override exceptions picks a month with the keyboard", async ({ page }) => {
  await page.goto("/override-exceptions")

  const trigger = page.getByRole("button", { name: /^Month\b/ })
  await expect(trigger).toHaveText(thisMonth)

  await trigger.focus()
  await page.keyboard.press("Enter")
  // Focus opens on the current month; Home jumps to January of that year.
  await page.keyboard.press("Home")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(`Jan ${now.getFullYear()}`)
})
