import { expect, test } from "@playwright/test"
import { randomEmail, randomPassword } from "./utils/random"

// E2E coverage for the three-tier role UX (FR-role-tiering).
// Tests run as the superuser (storageState injected by playwright.config.ts setup).

test.describe("Role select in Add User dialog", () => {
  test("Role select offers only Admin and Staff — no Superuser option", async ({
    page,
  }) => {
    await page.goto("/admin")
    await page.getByRole("button", { name: "Add User" }).click()

    // Open the Role combobox (scoped to the dialog)
    const dialog = page.getByRole("dialog")
    await dialog.getByRole("combobox").click()

    // Admin and Staff must be visible
    await expect(page.getByRole("option", { name: "Admin" })).toBeVisible()
    await expect(page.getByRole("option", { name: "Staff" })).toBeVisible()

    // Superuser must NOT be offered as a role option
    await expect(page.getByRole("option", { name: "Superuser" })).toHaveCount(0)
  })

  test("Superuser creates an Admin user via the role select and tier badge is shown", async ({
    page,
  }) => {
    const email = randomEmail()
    const password = randomPassword()

    await page.goto("/admin")
    await page.getByRole("button", { name: "Add User" }).click()

    // Fill the form
    await page.getByPlaceholder("Email").fill(email)
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)

    // Select "Admin" in the Role combobox (default is Staff, so we change it)
    await page.getByRole("dialog").getByRole("combobox").click()
    await page.getByRole("option", { name: "Admin" }).click()

    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User created successfully")).toBeVisible()
    await expect(page.getByRole("dialog")).not.toBeVisible()

    // The new user's row must display an "Admin" tier badge
    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow).toBeVisible()
    await expect(userRow.getByText("Admin", { exact: true })).toBeVisible()
  })
})
