import { expect, test } from "@playwright/test"

test("editing a supplier updates its row", async ({ page }) => {
  await page.goto("/suppliers")

  const name = `E2E-Sup-${Date.now()}`
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create supplier" }).click()

  const row = page.getByRole("row", { name: new RegExp(name) })
  await row.getByRole("button", { name: "Edit" }).click()

  const dialog = page.getByRole("dialog", { name: /Edit supplier/ })
  await dialog.getByLabel("Contact").fill("e2e@example.com")
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Supplier updated.")).toBeVisible()

  // Reload to prove the edit persisted server-side (not just a cache refresh).
  await page.reload()
  await expect(
    page
      .getByRole("row", { name: new RegExp(name) })
      .getByText("e2e@example.com"),
  ).toBeVisible()
})
