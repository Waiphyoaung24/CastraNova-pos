import { expect, type Page, test } from "@playwright/test"

// Regression coverage for EntityCombobox, the single component behind every
// picker in the app (SKU, country, supplier, customer, project).
//
// The bug: PopoverContent was the only element with a height cap, but it
// carried `overflow-hidden`; CommandList — the only element with
// `overflow-y-auto` — was handed `max-h-none`, and Command's `h-full` resolved
// to `auto` against an auto-height parent. So the list rendered at its full
// content height, nothing was scrollable, the mouse wheel did nothing, and the
// "Showing X of Y" footer was clipped ~1200px below the popover's visible box —
// which is why the paging control looked like it didn't exist.
//
// The country picker is the sharpest probe: 249 static options, no DB coupling.

const POPOVER = '[data-slot="popover-content"]'
const LIST = '[data-slot="command-list"]'

async function openCountryPicker(page: Page) {
  await page.goto("/customers")
  await expect(
    page.getByRole("heading", { name: "Customers", exact: true }),
  ).toBeVisible()

  await page.getByRole("button", { name: "New customer" }).first().click()
  // `exact` matters: the list screen also has a "Country filter" combobox.
  await page.getByRole("combobox", { name: "Country", exact: true }).click()
  await expect(page.locator(LIST)).toBeVisible()
}

test("the option list is a bounded scroll container", async ({ page }) => {
  await openCountryPicker(page)

  const list = await page.locator(LIST).evaluate((el) => ({
    clientHeight: el.clientHeight,
    scrollHeight: el.scrollHeight,
    overflowY: getComputedStyle(el).overflowY,
  }))

  expect(list.overflowY).toBe("auto")
  // The list must be shorter than its own content, or it never scrolls.
  expect(list.scrollHeight).toBeGreaterThan(list.clientHeight)

  // ...and nothing may overflow the popover itself, which clips.
  const popover = await page.locator(POPOVER).evaluate((el) => ({
    clientHeight: el.clientHeight,
    scrollHeight: el.scrollHeight,
  }))
  expect(popover.scrollHeight).toBeLessThanOrEqual(popover.clientHeight + 1)
})

test("the mouse wheel scrolls the option list", async ({ page }) => {
  await openCountryPicker(page)
  const list = page.locator(LIST)

  expect(await list.evaluate((el) => el.scrollTop)).toBe(0)

  await list.hover()
  await page.mouse.wheel(0, 400)

  await expect
    .poll(() => list.evaluate((el) => el.scrollTop))
    .toBeGreaterThan(0)
})

test("the footer counter stays inside the popover instead of being clipped", async ({
  page,
}) => {
  await openCountryPicker(page)

  const popover = await page.locator(POPOVER).boundingBox()
  const footer = await page.getByText(/Showing \d+ of 249/).boundingBox()
  if (!popover || !footer) throw new Error("popover or footer has no box")

  // The footer must sit within the popover's painted box; before the fix it
  // rendered ~1270px below it and was invisible.
  expect(footer.y).toBeGreaterThanOrEqual(popover.y - 1)
  expect(footer.y + footer.height).toBeLessThanOrEqual(
    popover.y + popover.height + 1,
  )
})

test("scrolling to the end of the list auto-loads the next page of options", async ({
  page,
}) => {
  await openCountryPicker(page)
  const list = page.locator(LIST)

  await expect(page.getByText("Showing 50 of 249")).toBeVisible()

  await list.evaluate((el) => el.scrollTo(0, el.scrollHeight))
  await expect(page.getByText("Showing 100 of 249")).toBeVisible()

  // Keeps paging, rather than dead-ending after one reveal.
  await list.evaluate((el) => el.scrollTo(0, el.scrollHeight))
  await expect(page.getByText("Showing 150 of 249")).toBeVisible()
})

test("typing filters the options and resets the page window", async ({
  page,
}) => {
  await openCountryPicker(page)

  await page.getByPlaceholder("Search country…").fill("land")
  // Narrow enough to fit in one window, so the footer drops away entirely.
  await expect(page.getByRole("option", { name: "Thailand" })).toBeVisible()
  await expect(page.getByText(/Showing \d+ of 249/)).toBeHidden()
})

test("the list has an absolute height cap, not just an available-space clamp", async ({
  page,
}) => {
  // On tall pages like /audit, the picker's trigger sits near the top with
  // ample space below it, so `--radix-popover-content-available-height` alone
  // let the dropdown stretch to nearly the full viewport. CommandList must
  // also carry its own max-height so it caps out well before that.
  await page.goto("/audit")
  await expect(
    page.getByRole("heading", { name: "Audit ledger" }),
  ).toBeVisible()

  await page.getByRole("combobox", { name: "Filter by SKU" }).click()
  const list = page.locator(LIST)
  await expect(list).toBeVisible()

  const clientHeight = await list.evaluate((el) => el.clientHeight)
  expect(clientHeight).toBeLessThanOrEqual(300)
})
