import { expect, test } from "@playwright/test"

// The preference grid is generated server-side (one row per channel x
// eligible event) rather than only showing rows the user already saved, so
// the page must never show the old "no channels configured" empty state for
// an authenticated user, and toggling one event must not affect any other
// row (synthetic rows have no id, so the row key must not be `p.id`).

test("preference grid renders all rows and toggling one leaves others unchanged", async ({
  page,
}) => {
  await page.goto("/notifications")

  await expect(
    page.getByText("No notification channels configured."),
  ).toHaveCount(0)

  const rows = page.getByRole("row")
  await expect(rows).not.toHaveCount(0)

  const lineLowStock = page.getByRole("checkbox", {
    name: "LINE Low stock",
  })
  const viberLowStock = page.getByRole("checkbox", {
    name: "Viber Low stock",
  })
  await expect(lineLowStock).toBeVisible()
  await expect(viberLowStock).toBeVisible()

  const viberWasChecked = await viberLowStock.isChecked()
  const lineWasChecked = await lineLowStock.isChecked()

  await lineLowStock.click()
  await expect(lineLowStock).toBeChecked({ checked: !lineWasChecked })
  // A different row must not flip just because we toggled this one.
  await expect(viberLowStock).toBeChecked({ checked: viberWasChecked })

  await page.reload()
  await expect(
    page.getByRole("checkbox", { name: "LINE Low stock" }),
  ).toBeChecked({ checked: !lineWasChecked })

  // Restore original state so the test is repeatable.
  await page.getByRole("checkbox", { name: "LINE Low stock" }).click()
})
