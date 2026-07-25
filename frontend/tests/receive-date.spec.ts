import { expect, test } from "@playwright/test"

// Browser E2E for the Receive date picker (design 2026-07-25). The picker
// exists because holding period is computed from received_at, so a delivery
// keyed in late used to report the wrong age. Covers:
//   1. Both tabs default the date to today (the operator's LOCAL date).
//   2. Both cap at today via the native `max` attribute — no future dates.
//   3. Backdating a Quantity receive mints a batch_no with the BACKDATED
//      YYYYMMDD prefix, proving the picked date reached the server and drove
//      both received_at and the batch label.
// Runs authed as the seeded superuser via storageState (global.setup).

/** Local date as YYYY-MM-DD — must mirror todayISO() in lib/receive-form.ts.
 * Deliberately not toISOString(), which is UTC and would flake either side of
 * UTC midnight. */
function localISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const today = localISO(new Date())

test("both Receive tabs default the date to today and refuse future dates", async ({
  page,
}) => {
  await page.goto("/receive")

  // Serialized is the default tab; its date input carries a static id.
  const serializedDate = page.locator("#receive-date")
  await expect(serializedDate).toHaveValue(today)
  await expect(serializedDate).toHaveAttribute("max", today)

  // The Quantity tab's id is useId-generated, so scope by the visible panel.
  await page.getByRole("tab", { name: "Quantity" }).click()
  const quantityPanel = page.getByRole("tabpanel")
  const quantityDate = quantityPanel.locator('input[type="date"]')
  await expect(quantityDate).toHaveValue(today)
  await expect(quantityDate).toHaveAttribute("max", today)
})

test("a backdated Quantity receive mints a batch_no with the backdated prefix", async ({
  page,
}) => {
  const backdate = new Date()
  backdate.setDate(backdate.getDate() - 10)
  const backdated = localISO(backdate)
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
  await panel.locator('input[type="date"]').fill(backdated)

  await panel.getByRole("button", { name: "Receive" }).click()

  // The success toast carries the minted batch number; its date prefix must be
  // the BACKDATED day, not today.
  await expect(
    page.getByText(new RegExp(`Received batch ${expectedPrefix}-`)),
  ).toBeVisible()
})
