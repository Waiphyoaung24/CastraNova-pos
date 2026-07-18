import { expect, test } from "@playwright/test"

// The grid is pivoted: one row per event, one checkbox column per channel
// (Telegram, LINE, Viber). A channel's checkboxes are disabled until the user
// has an address configured for it -- editing them can never actually
// deliver. Edits are local until Save is clicked: a single PATCH batches
// everything changed, rather than firing one request per checkbox.
//
// The seeded superuser already has a real telegram_chat_id (connected) and no
// line_user_id/viber_user_id (disconnected), so this exercises both states
// without needing to mutate user data for setup.

test("channel columns are gated by connection; Save batches, doesn't fire per click", async ({
  page,
}) => {
  await page.goto("/notifications")

  const telegramLowStock = page.getByRole("checkbox", {
    name: "Telegram Low stock",
  })
  const lineLowStock = page.getByRole("checkbox", { name: "LINE Low stock" })
  const viberLowStock = page.getByRole("checkbox", { name: "Viber Low stock" })

  await expect(telegramLowStock).toBeVisible()
  await expect(telegramLowStock).toBeEnabled()
  // No address configured for LINE/Viber -- their switches must be disabled,
  // regardless of any (impossible) opted-in state.
  await expect(lineLowStock).toBeDisabled()
  await expect(viberLowStock).toBeDisabled()

  const saveButton = page.getByRole("button", { name: "Save" })
  await expect(saveButton).toBeDisabled()

  const wasChecked = await telegramLowStock.isChecked()

  // Toggle without saving: the checkbox flips locally, Save becomes
  // available, but reloading before Save must revert it -- proving no
  // request fired on click.
  await telegramLowStock.click()
  await expect(telegramLowStock).toBeChecked({ checked: !wasChecked })
  await expect(saveButton).toBeEnabled()

  await page.reload()
  await expect(
    page.getByRole("checkbox", { name: "Telegram Low stock" }),
  ).toBeChecked({ checked: wasChecked })

  // Toggle again and actually Save this time.
  await page.getByRole("checkbox", { name: "Telegram Low stock" }).click()
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Preferences saved.")).toBeVisible()

  await page.reload()
  await expect(
    page.getByRole("checkbox", { name: "Telegram Low stock" }),
  ).toBeChecked({ checked: !wasChecked })

  // Restore original state so the test is repeatable.
  await page.getByRole("checkbox", { name: "Telegram Low stock" }).click()
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Preferences saved.")).toBeVisible()
})

// Regression coverage for two rendering bugs found via screenshot: checkboxes
// weren't centered under their column headers, and a short (non-scrolling)
// grid left a transparent gap at the right edge of the row hover highlight --
// ListTable's scrollbar-gutter reservation was unconditional even when no
// scrollbar was ever going to appear. Both are geometry bugs invisible to
// role/text assertions, so this reads actual bounding boxes.
test("Low stock row has no gap in its hover highlight, and its checkboxes are centered", async ({
  page,
}) => {
  await page.goto("/notifications")
  const row = page.getByRole("row", { name: /Low stock/ })
  await row.hover()

  const geometry = await row.evaluate((el) => {
    const tr = el as HTMLTableRowElement
    const table = tr.closest("table") as HTMLTableElement
    const scrollWrapper = table.parentElement as HTMLElement
    const tableRight = table.getBoundingClientRect().right
    const wrapperRight = scrollWrapper.getBoundingClientRect().right

    const cellGaps = [...tr.querySelectorAll("td")]
      .filter((td) => td.querySelector('[role="checkbox"]'))
      .map((td) => {
        const cellRect = td.getBoundingClientRect()
        const cbRect = (
          td.querySelector('[role="checkbox"]') as HTMLElement
        ).getBoundingClientRect()
        return {
          left: cbRect.left - cellRect.left,
          right: cellRect.right - cbRect.right,
        }
      })

    return {
      // The unused scrollbar gutter this grid (4 rows, no scrolling needed)
      // used to reserve, leaving the row's hover background short of the
      // container's true right edge.
      unusedGutterGap: wrapperRight - tableRight,
      cellGaps,
    }
  })

  expect(geometry.unusedGutterGap).toBeLessThan(1)
  for (const { left, right } of geometry.cellGaps) {
    expect(Math.abs(left - right)).toBeLessThan(1)
  }
})
