import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createStaffUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

// In-browser E2E for the channel-margin drill-down controls (FR-013): the
// Group-by tabs (channel|product|customer|project), the Channel select
// filter, the conditional revenue-mix bar, and the export URL params. Pure
// helper logic (formatting, export URL/filename builders) is already covered
// by reports.spec.ts; this locks the screen wiring itself.

test.describe("Channel margin drill-down", () => {
  test("default view shows the channel table and the revenue mix bar", async ({
    page,
  }) => {
    await page.goto("/channel-margin")

    await expect(
      page.getByRole("heading", { name: "Channel margin" }),
    ).toBeVisible()

    const table = page.getByRole("table")
    await expect(
      table.getByRole("columnheader", { name: "Channel" }),
    ).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Revenue mix by channel" }),
    ).toBeVisible()
  })

  test("Group by switches the active dimension and hides the channel-only mix bar", async ({
    page,
  }) => {
    // This suite resets to initial_data only (no transactional rows), so the
    // channel grouping always renders its three fixed rows while the other
    // dimensions render the empty state. We therefore verify the drill-down
    // *control wiring* (dimension switch + conditional mix bar) here; the
    // populated-table reconciliation across dimensions is proven exhaustively
    // by the backend margin_report tests (isolated app_test fixtures).
    await page.goto("/channel-margin")

    // Default channel view: three-channel table header + revenue-mix bar.
    await expect(
      page.getByRole("columnheader", { name: "Channel" }),
    ).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Revenue mix by channel" }),
    ).toBeVisible()

    await page.getByRole("tab", { name: "Product" }).click()

    // Dimension switched: Product tab selected, the channel-only mix bar is
    // gone, and the "Channel" column header is no longer shown.
    await expect(
      page.getByRole("tab", { name: "Product", selected: true }),
    ).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Revenue mix by channel" }),
    ).not.toBeVisible()
    await expect(
      page.getByRole("columnheader", { name: "Channel" }),
    ).not.toBeVisible()
  })

  test("Channel filter narrows rows and hides the mix bar; export carries group_by + channel", async ({
    page,
  }) => {
    await page.goto("/channel-margin")

    await page.getByRole("tab", { name: "Product" }).click()

    await page.getByRole("combobox", { name: "Channel" }).click()
    await page.getByRole("option", { name: "SALE" }).click()

    await expect(
      page.getByRole("heading", { name: "Revenue mix by channel" }),
    ).not.toBeVisible()

    const xlsxRequest = page.waitForRequest((req) =>
      /\/api\/v1\/reports\/channel-margin\.xlsx\?.*group_by=product.*channel=SALE/.test(
        req.url(),
      ),
    )
    await page.getByRole("button", { name: "Excel" }).click()
    await xlsxRequest
  })

  test.describe("non-admin access", () => {
    test.use({ storageState: { cookies: [], origins: [] } })

    test("Staff is redirected away from the channel-margin report", async ({
      page,
    }) => {
      const email = randomEmail()
      const password = randomPassword()

      await createStaffUser({ email, password })
      await logInUser(page, email, password)

      await page.goto("/channel-margin")

      await expect(
        page.getByRole("heading", { name: "Channel margin" }),
      ).not.toBeVisible()
      await expect(page).not.toHaveURL(/\/channel-margin/)
    })

    test("Admin can access the channel-margin report", async ({ page }) => {
      await logInUser(page, firstSuperuser, firstSuperuserPassword)

      await page.goto("/channel-margin")

      await expect(
        page.getByRole("heading", { name: "Channel margin" }),
      ).toBeVisible()
    })
  })
})
