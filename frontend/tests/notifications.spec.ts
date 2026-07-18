import { expect, type Page, test } from "@playwright/test"

// The grid is pivoted: one row per event, one checkbox column per channel
// (Telegram, LINE, Viber). A channel's checkboxes are disabled until the user
// has an address configured for it -- editing them can never actually
// deliver. Edits are local until Save is clicked: a single PATCH batches
// everything changed, rather than firing one request per checkbox.
//
// Which account holds the real Telegram connection is mutable dev-DB state,
// so anything that depends on a *specific* connected/disconnected state stubs
// it at the network boundary. Tests that hit the real backend assert only
// what holds regardless (LINE/Viber have no enrollment path, so they are
// always disconnected).

// Against the real backend. LINE and Viber have no enrollment path yet (they
// need an inbound follow/subscribe webhook), so no account in this
// environment has an address for them -- their switches must always be
// disabled, since a preference enabled there could never deliver.
test("channels with no address configured have disabled switches", async ({
  page,
}) => {
  await page.goto("/notifications")

  await expect(
    page.getByRole("checkbox", { name: "LINE Low stock" }),
  ).toBeDisabled()
  await expect(
    page.getByRole("checkbox", { name: "Viber Low stock" }),
  ).toBeDisabled()
})

// Whether any given channel is connected is mutable dev-DB state (an
// operator can move a Telegram connection between accounts at any time), so
// the grid is stubbed here to keep this deterministic. That also lets it
// count PATCH calls directly -- asserting "exactly one request, only after
// Save" rather than inferring it from a reload.
test("edits are local until Save, which sends exactly one batched request", async ({
  page,
}) => {
  const gridRow = (
    channel: string,
    event_type: string,
    enabled: boolean,
    channel_connected: boolean,
  ) => ({ id: null, channel, event_type, enabled, channel_connected })

  await page.route("**/notifications/preferences", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        gridRow("TELEGRAM", "LOW_STOCK", false, true),
        gridRow("TELEGRAM", "PULL_SHORT", false, true),
        gridRow("LINE", "LOW_STOCK", false, false),
        gridRow("LINE", "PULL_SHORT", false, false),
      ]),
    })
  })

  const patches: string[] = []
  await page.route("**/notifications/preferences", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback()
    patches.push(route.request().postData() ?? "")
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        gridRow("TELEGRAM", "LOW_STOCK", true, true),
        gridRow("TELEGRAM", "PULL_SHORT", true, true),
        gridRow("LINE", "LOW_STOCK", false, false),
        gridRow("LINE", "PULL_SHORT", false, false),
      ]),
    })
  })

  await page.goto("/notifications")

  const lowStock = page.getByRole("checkbox", { name: "Telegram Low stock" })
  const pullShort = page.getByRole("checkbox", { name: "Telegram Pull short" })
  const saveButton = page.getByRole("button", { name: "Save" })

  // A connected channel is editable; a disconnected one never is.
  await expect(lowStock).toBeEnabled()
  await expect(
    page.getByRole("checkbox", { name: "LINE Low stock" }),
  ).toBeDisabled()
  await expect(saveButton).toBeDisabled()

  // Two edits, no Save yet: nothing may have been sent.
  await lowStock.click()
  await pullShort.click()
  await expect(lowStock).toBeChecked()
  await expect(pullShort).toBeChecked()
  await expect(saveButton).toBeEnabled()
  expect(patches).toHaveLength(0)

  await saveButton.click()
  await expect(page.getByText("Preferences saved.")).toBeVisible()

  // Exactly one request, carrying both edits together.
  expect(patches).toHaveLength(1)
  const sent = JSON.parse(patches[0]).preferences
  expect(sent).toHaveLength(2)
  expect(sent.map((p: { event_type: string }) => p.event_type).sort()).toEqual([
    "LOW_STOCK",
    "PULL_SHORT",
  ])
  expect(sent.every((p: { enabled: boolean }) => p.enabled)).toBe(true)

  // Save goes back to disabled once there's nothing pending.
  await expect(saveButton).toBeDisabled()
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

// The card's button reads "Connect Telegram" or "Reconnect" depending on
// whether this account currently has a chat bound. That's mutable dev-DB
// state (an operator can move a connection between accounts at any time), so
// tests must not hard-code either wording.
const connectButton = (page: Page) =>
  page.getByRole("button", { name: /^(Connect Telegram|Reconnect)$/ })

// Exercises the real connect endpoint end-to-end, including a genuine
// server-rendered QR image. Deliberately never clicks "Send test message":
// TELEGRAM_BOT_TOKEN is configured for real in this dev environment, so that
// would deliver an actual message to a real person on every test run.
test("connect card mints a real QR + deep link", async ({ page }) => {
  await page.goto("/notifications")

  await connectButton(page).click()

  const qr = page.getByRole("img", { name: "Scan to connect Telegram" })
  await expect(qr).toBeVisible()
  await expect(qr).toHaveAttribute("src", /^data:image\/png;base64,/)

  const deepLink = page.locator('a[href*="t.me"]')
  await expect(deepLink).toHaveAttribute("href", /\?start=.+/)
  // The bot username must be configured, or the link is a dead t.me/None.
  await expect(deepLink).not.toHaveAttribute(
    "href",
    /t\.me\/(None|undefined)\?/,
  )
})

// A terminal confirm failure (this Telegram already backs another account)
// must surface as a real message and stop the poll, not run out the clock
// into "Didn't detect a connection" -- which would tell the user to retry
// something retrying cannot fix. The trigger needs a *second* real Telegram
// account to reproduce for real, so the confirm response is stubbed at the
// network boundary; everything downstream of it is the real component.
test("a Telegram already linked elsewhere shows a real error, not a generic timeout", async ({
  page,
}) => {
  const ERROR =
    "This Telegram account is already connected to another user. Disconnect it there first, or use a different Telegram account."

  await page.route("**/notifications/telegram/confirm", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connected: false,
        telegram_username: null,
        error: ERROR,
      }),
    }),
  )

  await page.goto("/notifications")
  await connectButton(page).click()

  await expect(
    page.getByText("Couldn't connect this Telegram account"),
  ).toBeVisible()
  await expect(page.getByText(ERROR)).toBeVisible()
  // The generic timeout copy must not also appear.
  await expect(page.getByText(/Didn't detect a connection/)).toHaveCount(0)
  // Polling stopped, so the QR is torn down rather than left spinning.
  await expect(
    page.getByRole("img", { name: "Scan to connect Telegram" }),
  ).toHaveCount(0)
})

// Connected-state rendering, stubbed so it doesn't depend on which account
// currently owns the real Telegram connection. The username is what makes a
// stale binding visible ("Connected as @who?") rather than a meaningless
// chat id, and delivery_failing is the passive rot warning for a binding
// that broke (bot blocked, chat deleted) since the last send.
test("connected state shows the username, and surfaces a failing binding", async ({
  page,
}) => {
  await page.route("**/notifications/telegram/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connected: true,
        telegram_username: "winthiha",
        delivery_failing: true,
        last_error: "Forbidden: bot was blocked by the user",
      }),
    }),
  )

  await page.goto("/notifications")

  await expect(page.getByText("Connected as @winthiha")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Send test message" }),
  ).toBeVisible()
  await expect(page.getByText("Telegram delivery is failing")).toBeVisible()
  await expect(
    page.getByText("Forbidden: bot was blocked by the user"),
  ).toBeVisible()
})
